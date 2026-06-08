import asyncio

import pytest
from sqlalchemy import select

from hub.auth import TokenKind, authenticate
from hub.db import init_models, make_engine, make_sessionmaker
from hub.ids import new_id
from hub.invites import InviteError, create_invite, redeem_invite
from hub.models import Friendship, Printer, Token
from tests.conftest import now


async def _printer(s, handle):
    p = Printer(id=new_id("prn"), handle=handle, display_name=handle,
                renderer_version=None, last_seen_at=None, created_at=now())
    s.add(p)
    await s.commit()
    return p


async def test_admin_bootstrap_invite_creates_printer_no_friendship(sm):
    async with sm() as s:
        code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
        reg = await redeem_invite(s, code=code, handle="alice", display_name="Alice")
        assert reg.inviter_handle is None
        # the minted device token authenticates as the new printer
        p = await authenticate(s, reg.device_token, required=TokenKind.DEVICE)
        assert p.handle == "alice"
        # no friendships for a bootstrap invite
        assert (await s.execute(select(Friendship))).scalars().first() is None


async def test_member_invite_establishes_mutual_friendship(sm):
    async with sm() as s:
        alice = await _printer(s, "alice")
        code = await create_invite(s, issuer_printer_id=alice.id, ttl_s=3600)
        reg = await redeem_invite(s, code=code, handle="bob", display_name="Bob")
        assert reg.inviter_handle == "alice"
        pairs = {(f.owner_id, f.friend_id)
                 for f in (await s.execute(select(Friendship))).scalars().all()}
        bob_id = reg.printer_id
        assert (alice.id, bob_id) in pairs and (bob_id, alice.id) in pairs


async def test_invite_single_use_and_expiry(sm):
    async with sm() as s:
        code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
        await redeem_invite(s, code=code, handle="alice", display_name="A")
        with pytest.raises(InviteError):
            await redeem_invite(s, code=code, handle="carol", display_name="C")  # reused

        expired = await create_invite(s, issuer_printer_id=None, ttl_s=-1)
        with pytest.raises(InviteError):
            await redeem_invite(s, code=expired, handle="dave", display_name="D")


async def test_reused_invite_creates_no_second_printer(sm):
    # Single-use at the side-effect level: a second redeem of a claimed invite
    # raises AND creates no second printer/token-pair from the one invite. This
    # verifies the serial PROPERTY (the redeemed_by guard); the FOR UPDATE row
    # lock that makes it hold under CONCURRENT redeems is a Postgres-only no-op on
    # this serial SQLite harness, so that hardening is not exercised here.
    async with sm() as s:
        code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
        await redeem_invite(s, code=code, handle="alice", display_name="Alice")
        with pytest.raises(InviteError):
            await redeem_invite(s, code=code, handle="bob", display_name="Bob")
        printers = (await s.execute(select(Printer))).scalars().all()
        assert [p.handle for p in printers] == ["alice"]


async def test_concurrent_redeem_single_invite_creates_one_printer_and_token_pair(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'hub.db'}")
    await init_models(engine)
    sm = make_sessionmaker(engine)
    try:
        async with sm() as s:
            code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)

        async def redeem(handle: str):
            async with sm() as s:
                try:
                    return await redeem_invite(
                        s, code=code, handle=handle, display_name=handle.title()
                    )
                except InviteError as exc:
                    return exc

        results = await asyncio.gather(redeem("alice"), redeem("bob"))
        winners = [result for result in results if not isinstance(result, InviteError)]
        losers = [result for result in results if isinstance(result, InviteError)]
        assert len(winners) == 1
        assert len(losers) == 1

        async with sm() as s:
            printers = (
                await s.execute(select(Printer).where(Printer.handle.in_(("alice", "bob"))))
            ).scalars().all()
            assert [p.handle for p in printers] == [winners[0].handle]
            token_rows = (
                await s.execute(select(Token).where(Token.printer_id == winners[0].printer_id))
            ).scalars().all()
            assert sorted(t.kind for t in token_rows) == [
                TokenKind.API.value,
                TokenKind.DEVICE.value,
            ]
    finally:
        await engine.dispose()


async def test_duplicate_handle_rejected(sm):
    async with sm() as s:
        await _printer(s, "alice")
        code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
        with pytest.raises(InviteError):
            await redeem_invite(s, code=code, handle="alice", display_name="A2")


async def test_friendship_records_origin_invite_id(sm):
    from hub.friends import list_friends
    async with sm() as s:
        alice = await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="alice", display_name="Alice")
        code = await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600)
        from hub.auth import hash_token
        from hub.models import Invite
        inv = await s.get(Invite, hash_token(code))
        await redeem_invite(s, code=code, handle="bob", display_name="Bob")

        # alice's view of bob carries the originating invite id
        friends = await list_friends(s, alice.printer_id, online_ids=set())
        assert friends[0].handle == "bob"
        assert friends[0].via_invite_id == inv.id
