from printer.relay.hub_client import HubClient
from printer.relay.local_client import LocalClient, SubmitOutcome


async def test_hub_client_get_inbox_and_ack(mock_hub, hub_http):
    mock_hub.inbox.append({
        "job_id": "hj1", "sender": "alice", "kind": "document",
        "sent_at": "2026-06-03T14:32:00+00:00", "payload": {"document": {"blocks": []}},
    })
    hub = HubClient(hub_http, device_token="dev-token", api_token="api-token")
    job = await hub.get_inbox(wait_s=1)
    assert job["job_id"] == "hj1"
    await hub.ack("hj1")
    assert mock_hub.acked == ["hj1"]
    assert mock_hub.auth_seen[-1] == "Bearer dev-token"


async def test_hub_client_post_status_and_capabilities(mock_hub, hub_http):
    hub = HubClient(hub_http, device_token="dev-token", api_token="api-token")
    await hub.post_status("hj1", "printed")
    assert mock_hub.statuses == [("hj1", "printed")]
    await hub.put_capabilities(renderer_version="1.0.0", blocks_schema={"x": 1},
                               block_types=["paragraph"])
    assert mock_hub.capabilities[-1]["renderer_version"] == "1.0.0"


async def test_hub_client_post_status_409_does_not_raise(mock_hub, hub_http):
    # The hub returns 409 when a job is already terminal in a DIFFERENT state.
    # post_status must treat that as success (Fix A): a raised HTTPStatusError
    # here would crash-loop the relay during startup replay.
    hub = HubClient(hub_http, device_token="dev-token", api_token="api-token")
    await hub.post_status("hj1", "printed")           # first status wins
    await hub.post_status("hj1", "printer_expired")   # conflicting -> hub 409
    # No exception propagated; the conflicting attempt was still recorded by the
    # mock, but post_status returned normally so callers advance the JobMap.
    assert ("hj1", "printer_expired") in mock_hub.statuses


async def test_hub_client_post_status_same_status_is_idempotent(mock_hub, hub_http):
    # Re-posting the identical terminal status returns 200 (the hub is idempotent
    # for the same status); this is what makes the Fix C double-post safe.
    hub = HubClient(hub_http, device_token="dev-token", api_token="api-token")
    await hub.post_status("hj2", "printed")
    await hub.post_status("hj2", "printed")  # must not raise
    assert mock_hub.statuses.count(("hj2", "printed")) == 2


async def test_hub_client_create_invite_uses_api_token(mock_hub, hub_http):
    hub = HubClient(hub_http, device_token="dev-token", api_token="api-token")
    # POST /invites returns {code, invite_id, expires_at}; the relay needs both
    # the code (to show the user) and the invite_id (to record locally).
    code, invite_id = await hub.create_invite()
    assert code.startswith("CODE")
    assert invite_id.startswith("inv_")
    assert mock_hub.auth_seen[-1] == "Bearer api-token"


async def test_local_client_maps_status_codes(fake_deps):
    # Reuse the real local service via the existing lifespan_client fixture.
    from tests.conftest import lifespan_client

    doc = {"blocks": [{"type": "paragraph", "text": "hi"}]}
    async with lifespan_client(fake_deps) as ac:
        local = LocalClient(ac)
        res = await local.print_document(doc, sender="friend:alice", idempotency_key="hj1")
        assert res.outcome is SubmitOutcome.ACCEPTED
        assert res.local_job_id is not None
        # GET /jobs/{id} round-trips
        status = await local.get_job_status(res.local_job_id)
        assert status in {"queued", "printed", "expired", "retry_timeout", "unknown_partial"}
