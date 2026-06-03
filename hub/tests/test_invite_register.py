import pytest
from sqlalchemy import select

from hub.auth import TokenKind, authenticate
from hub.ids import new_id
from hub.invites import InviteError, create_invite, redeem_invite
from hub.models import Friendship, Printer
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


async def test_duplicate_handle_rejected(sm):
    async with sm() as s:
        await _printer(s, "alice")
        code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
        with pytest.raises(InviteError):
            await redeem_invite(s, code=code, handle="alice", display_name="A2")
