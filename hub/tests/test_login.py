import pytest

from hub.auth import TokenKind, authenticate
from hub.invites import create_invite, redeem_invite
from hub.login import LoginLinkError, consume_login_link, create_login_link


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
