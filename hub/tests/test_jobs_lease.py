from hub.ids import new_id
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
