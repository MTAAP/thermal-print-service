from hub.friends import are_friends, list_friends, resolve_handles, unfriend
from hub.invites import create_invite, redeem_invite


async def _join(s, handle, issuer=None):
    code = await create_invite(s, issuer_printer_id=issuer, ttl_s=3600)
    return await redeem_invite(s, code=code, handle=handle, display_name=handle.title())


async def test_friendship_and_listing(sm):
    async with sm() as s:
        alice = await _join(s, "alice")
        bob = await _join(s, "bob", issuer=alice.printer_id)
        assert await are_friends(s, alice.printer_id, bob.printer_id) is True

        friends = await list_friends(s, alice.printer_id, online_ids=set())
        assert [f.handle for f in friends] == ["bob"]
        assert friends[0].online is False


async def test_unfriend_is_mutual(sm):
    async with sm() as s:
        alice = await _join(s, "alice")
        bob = await _join(s, "bob", issuer=alice.printer_id)
        await unfriend(s, alice.printer_id, bob.printer_id)
        assert await are_friends(s, alice.printer_id, bob.printer_id) is False
        assert await list_friends(s, bob.printer_id, online_ids=set()) == []


async def test_resolve_handles_partitions_known_unknown(sm):
    async with sm() as s:
        alice = await _join(s, "alice")
        bob = await _join(s, "bob", issuer=alice.printer_id)
        known, unknown = await resolve_handles(s, ["bob", "ghost"])
        assert known["bob"] == bob.printer_id and unknown == ["ghost"]
