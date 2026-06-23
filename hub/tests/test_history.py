from hub.history import list_jobs
from hub.ids import new_id
from hub.invites import create_invite, redeem_invite
from hub.models import Job
from tests.conftest import now


async def _join(s, handle, issuer=None):
    code = await create_invite(s, issuer_printer_id=issuer, ttl_s=3600)
    return await redeem_invite(s, code=code, handle=handle, display_name=handle.title())


async def _job(s, *, sender_handle, recipient_id, state):
    j = Job(id=new_id("job"), sender_handle=sender_handle, recipient_id=recipient_id,
            state=state, kind="document", payload={"document": {}},
            sent_at=now(), created_at=now(), lease_expires_at=None, leased_by=None)
    s.add(j)
    await s.commit()
    return j


async def test_list_jobs_partitions_sent_and_received(sm):
    async with sm() as s:
        alice = await _join(s, "alice")
        bob = await _join(s, "bob", issuer=alice.printer_id)
        # alice -> bob (sent from alice's view, received from bob's view)
        await _job(s, sender_handle="alice", recipient_id=bob.printer_id, state="printed")
        # bob -> alice
        await _job(s, sender_handle="bob", recipient_id=alice.printer_id, state="queued")

        alice_hist = await list_jobs(s, owner_id=alice.printer_id, handle="alice")
        sent_peers = {r.peer for r in alice_hist.sent}
        recv_peers = {r.peer for r in alice_hist.received}
        # sent side joins recipient_id -> handle, so peer is a handle not an id
        assert sent_peers == {"bob"}
        assert recv_peers == {"bob"}
        assert alice_hist.sent[0].status == "printed"
        assert alice_hist.received[0].status == "queued"


async def test_list_jobs_surfaces_unknown_partial_status(sm):
    async with sm() as s:
        alice = await _join(s, "alice")
        bob = await _join(s, "bob", issuer=alice.printer_id)
        await _job(s, sender_handle="alice", recipient_id=bob.printer_id,
                   state="printer_unknown_partial")
        hist = await list_jobs(s, owner_id=alice.printer_id, handle="alice")
        assert hist.sent[0].status == "printer_unknown_partial"
