from hub.ids import new_id
from hub.models import Job
from tests.conftest import now


async def _friend(deps, alice, handle="bob"):
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        return await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600),
            handle=handle, display_name=handle.title())


async def _job(deps, *, sender_handle, recipient_id, state):
    async with deps.sessionmaker() as s:
        s.add(Job(id=new_id("job"), sender_handle=sender_handle, recipient_id=recipient_id,
                  state=state, kind="document", payload={"document": {}},
                  sent_at=now(), created_at=now(), lease_expires_at=None, leased_by=None))
        await s.commit()


async def test_history_view_renders_sent_and_received(web_client):
    client, deps, alice = web_client
    bob = await _friend(deps, alice)
    await _job(deps, sender_handle="alice", recipient_id=bob.printer_id, state="printed")
    await _job(deps, sender_handle="bob", recipient_id=alice.printer_id, state="queued")

    r = await client.get("/history")
    assert r.status_code == 200
    assert 'data-testid="history-view"' in r.text
    assert 'data-testid="history-sent"' in r.text
    assert 'data-testid="history-received"' in r.text
    assert 'data-status="printed"' in r.text
    assert 'data-status="queued"' in r.text


async def test_history_unknown_partial_warns_and_offers_no_resend(web_client):
    client, deps, alice = web_client
    bob = await _friend(deps, alice)
    await _job(deps, sender_handle="alice", recipient_id=bob.printer_id,
               state="printer_unknown_partial")

    r = await client.get("/history")
    assert 'data-status="printer_unknown_partial"' in r.text
    assert 'data-testid="partial-warning"' in r.text
    # Hard requirement: NO resend control anywhere in the History view.
    assert "resend" not in r.text.lower()


async def test_history_requires_session(app_client):
    client, _ = app_client
    r = await client.get("/history", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/console/login" in r.headers["location"]
