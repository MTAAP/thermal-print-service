from datetime import timedelta

from sqlalchemy import update

from hub.ids import new_id
from hub.jobs.lease import ack_delivered, lease_next, report_terminal, sweep
from hub.jobs.store import map_local_status
from hub.models import Job
from tests.conftest import now


async def test_can_persist_a_job(sm):
    async with sm() as s:
        s.add(Job(
            id=new_id("job"), sender_handle="alice", recipient_id="prn_bob",
            state="queued", kind="document", payload={"document": {}},
            sent_at=now(), created_at=now(),
            lease_expires_at=None, leased_by=None,
        ))
        await s.commit()
    async with sm() as s:
        from sqlalchemy import select
        got = (await s.execute(select(Job))).scalars().all()
        assert len(got) == 1 and got[0].state == "queued"


async def _queued(s, recipient_id="prn_bob", sender="alice"):
    j = Job(id=new_id("job"), sender_handle=sender, recipient_id=recipient_id,
            state="queued", kind="document", payload={"document": {}},
            sent_at=now(), created_at=now(), lease_expires_at=None, leased_by=None)
    s.add(j)
    await s.commit()
    return j


async def test_lease_then_ack_delivered(sm):
    async with sm() as s:
        j = await _queued(s)
        leased = await lease_next(s, recipient_id="prn_bob", poll_id="p1", visibility_s=60)
        assert leased.id == j.id and leased.state == "leased"
        assert await ack_delivered(s, job_id=j.id, poll_id="p1") is True
        assert (await s.get(Job, j.id)).state == "delivered"


async def test_only_one_poll_leases_a_job(sm):
    async with sm() as s:
        await _queued(s)
        a = await lease_next(s, recipient_id="prn_bob", poll_id="p1", visibility_s=60)
        b = await lease_next(s, recipient_id="prn_bob", poll_id="p2", visibility_s=60)
        assert a is not None and b is None  # second poll finds nothing queued


async def test_expired_lease_is_reclaimed(sm):
    async with sm() as s:
        j = await _queued(s)
        await lease_next(s, recipient_id="prn_bob", poll_id="p1", visibility_s=60)
        # force the lease into the past
        await s.execute(update(Job).where(Job.id == j.id)
                        .values(lease_expires_at=now() - timedelta(seconds=1)))
        await s.commit()
        stats = await sweep(s, job_ttl_s=24 * 3600)
        assert stats["reclaimed"] == 1
        assert (await s.get(Job, j.id)).state == "queued"


async def test_ttl_expiry_marks_relay_expired(sm):
    async with sm() as s:
        j = await _queued(s)
        await s.execute(update(Job).where(Job.id == j.id)
                        .values(created_at=now() - timedelta(days=2)))
        await s.commit()
        stats = await sweep(s, job_ttl_s=24 * 3600)
        assert stats["relay_expired"] == 1
        assert (await s.get(Job, j.id)).state == "relay_expired"


async def test_report_terminal_maps_local_unknown_partial(sm):
    async with sm() as s:
        j = await _queued(s)
        await lease_next(s, recipient_id="prn_bob", poll_id="p1", visibility_s=60)
        await ack_delivered(s, job_id=j.id, poll_id="p1")
        hub_status = map_local_status("unknown_partial")
        assert hub_status == "printer_unknown_partial"
        assert await report_terminal(s, job_id=j.id, status=hub_status) is True
        assert (await s.get(Job, j.id)).state == "printer_unknown_partial"
