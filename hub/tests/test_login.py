import asyncio

import pytest
from sqlalchemy import select

from hub.auth import TokenKind, authenticate
from hub.db import init_models, make_engine, make_sessionmaker
from hub.invites import create_invite, redeem_invite
from hub.login import LoginLinkError, consume_login_link, create_login_link
from hub.models import Token


async def _join(s, handle):
    code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
    return await redeem_invite(s, code=code, handle=handle, display_name=handle.title())


async def test_login_link_mints_console_token(sm):
    async with sm() as s:
        await _join(s, "alice")
        link = await create_login_link(s, handle="alice", ttl_s=600)
        console_token = await consume_login_link(s, code=link)
        # the minted token authenticates ONLY as CONSOLE for that printer
        me = await authenticate(s, console_token, required=TokenKind.CONSOLE)
        assert me.handle == "alice"
        with pytest.raises(PermissionError):
            await authenticate(s, console_token, required=TokenKind.API)


async def test_login_link_is_single_use(sm):
    async with sm() as s:
        await _join(s, "alice")
        link = await create_login_link(s, handle="alice", ttl_s=600)
        await consume_login_link(s, code=link)
        with pytest.raises(LoginLinkError):
            await consume_login_link(s, code=link)


async def test_reused_login_link_mints_no_second_token(sm):
    # Single-use at the side-effect level: a second consume of a used link raises
    # AND mints no second CONSOLE token. With the redundant read-guard removed, the
    # conditional UPDATE is the sole gate, so this serial second consume genuinely
    # reaches the rowcount==0 branch -- a regression to a non-atomic set would mint
    # a second token and fail this test. (True concurrent racing is Postgres-only.)
    async with sm() as s:
        await _join(s, "alice")
        link = await create_login_link(s, handle="alice", ttl_s=600)
        await consume_login_link(s, code=link)
        with pytest.raises(LoginLinkError):
            await consume_login_link(s, code=link)
        console_tokens = (
            await s.execute(
                select(Token).where(Token.kind == TokenKind.CONSOLE.value)
            )
        ).scalars().all()
        assert len(console_tokens) == 1


async def test_concurrent_consume_single_login_link_mints_one_console_token(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'hub.db'}")
    await init_models(engine)
    sm = make_sessionmaker(engine)
    try:
        async with sm() as s:
            await _join(s, "alice")
            link = await create_login_link(s, handle="alice", ttl_s=600)

        async def consume():
            async with sm() as s:
                try:
                    return await consume_login_link(s, code=link)
                except LoginLinkError as exc:
                    return exc

        results = await asyncio.gather(consume(), consume())
        tokens = [result for result in results if isinstance(result, str)]
        errors = [result for result in results if isinstance(result, LoginLinkError)]
        assert len(tokens) == 1
        assert len(errors) == 1

        async with sm() as s:
            console_tokens = (
                await s.execute(select(Token).where(Token.kind == TokenKind.CONSOLE.value))
            ).scalars().all()
            assert len(console_tokens) == 1
    finally:
        await engine.dispose()


async def test_consume_login_link_uses_one_commit_for_claim_and_console_token(sm):
    async with sm() as s:
        await _join(s, "alice")
        link = await create_login_link(s, handle="alice", ttl_s=600)

    async with sm() as s:
        commits = 0
        original_commit = s.commit

        async def counted_commit():
            nonlocal commits
            commits += 1
            await original_commit()

        s.commit = counted_commit
        await consume_login_link(s, code=link)
        assert commits == 1


async def test_login_link_expiry_rejected(sm):
    async with sm() as s:
        await _join(s, "alice")
        link = await create_login_link(s, handle="alice", ttl_s=-1)
        with pytest.raises(LoginLinkError):
            await consume_login_link(s, code=link)


async def test_login_link_unknown_handle_rejected(sm):
    async with sm() as s:
        with pytest.raises(LoginLinkError):
            await create_login_link(s, handle="ghost", ttl_s=600)
