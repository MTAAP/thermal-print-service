import pytest

from hub.capabilities import upsert_capability
from hub.invites import create_invite, redeem_invite
from hub.jobs.wakeup import WakeupRegistry
from hub.schemas import SendReq
from hub.send import send_document

SCHEMA = {
    "type": "object",
    "properties": {"blocks": {"type": "array", "items": {
        "type": "object", "properties": {"type": {"enum": ["paragraph"]}},
        "required": ["type"]}}},
    "required": ["blocks"],
}


async def _join(s, handle, issuer=None):
    code = await create_invite(s, issuer_printer_id=issuer, ttl_s=3600)
    return await redeem_invite(s, code=code, handle=handle, display_name=handle)


async def _two_friends_with_caps(s):
    alice = await _join(s, "alice")
    bob = await _join(s, "bob", issuer=alice.printer_id)
    await upsert_capability(s, printer_id=bob.printer_id, renderer_version="1.0.0",
                            blocks_schema=SCHEMA, block_types=["paragraph"])
    return alice, bob


async def test_send_to_friend_queues_and_signals(sm):
    wake = WakeupRegistry()
    signalled = []
    # spy on signal by wrapping
    orig = wake.signal
    wake.signal = lambda pid: (signalled.append(pid), orig(pid))[1]  # type: ignore
    async with sm() as s:
        alice, bob = await _two_friends_with_caps(s)
        resp = await send_document(
            s, wake, sender_handle="alice", to=["bob"],
            document={"blocks": [{"type": "paragraph"}]},
            idempotency_key=None, sender_rate_per_min=30,
        )
        assert resp.results[0].status == "queued"
        assert resp.results[0].job_id is not None
        assert bob.printer_id in signalled


async def test_partial_results_not_friend_and_unknown(sm):
    wake = WakeupRegistry()
    async with sm() as s:
        alice, bob = await _two_friends_with_caps(s)
        await _join(s, "carol")  # exists but not a friend of alice
        resp = await send_document(
            s, wake, sender_handle="alice", to=["bob", "carol", "ghost"],
            document={"blocks": [{"type": "paragraph"}]},
            idempotency_key=None, sender_rate_per_min=30,
        )
        by = {r.to: r.status for r in resp.results}
        assert by == {"bob": "queued", "carol": "not_friend", "ghost": "recipient_unknown"}


async def test_incompatible_block_rejected_at_send(sm):
    wake = WakeupRegistry()
    async with sm() as s:
        alice, bob = await _two_friends_with_caps(s)
        resp = await send_document(
            s, wake, sender_handle="alice", to=["bob"],
            document={"blocks": [{"type": "drop_cap"}]},
            idempotency_key=None, sender_rate_per_min=30,
        )
        assert resp.results[0].status == "incompatible"
        assert resp.results[0].detail is not None


async def test_idempotent_send_returns_same_job_ids(sm):
    wake = WakeupRegistry()
    async with sm() as s:
        alice, bob = await _two_friends_with_caps(s)
        doc = {"blocks": [{"type": "paragraph"}]}
        r1 = await send_document(s, wake, sender_handle="alice", to=["bob"],
                                 document=doc, idempotency_key="k1", sender_rate_per_min=30)
        r2 = await send_document(s, wake, sender_handle="alice", to=["bob"],
                                 document=doc, idempotency_key="k1", sender_rate_per_min=30)
        assert r1.results[0].job_id == r2.results[0].job_id


async def test_idempotent_send_replays_full_partial_result_set(sm):
    # Idempotency is send-level, not job-only: replay the exact per-recipient
    # outcome list, including failures that did not create jobs.
    wake = WakeupRegistry()
    async with sm() as s:
        _alice, _bob = await _two_friends_with_caps(s)
        await _join(s, "carol")  # exists but is not alice's friend
        doc = {"blocks": [{"type": "paragraph"}]}
        r1 = await send_document(
            s, wake, sender_handle="alice", to=["bob", "carol", "ghost"],
            document=doc, idempotency_key="k2", sender_rate_per_min=30)
        r2 = await send_document(
            s, wake, sender_handle="alice", to=["bob", "carol", "ghost"],
            document=doc, idempotency_key="k2", sender_rate_per_min=30)

        assert r2.model_dump() == r1.model_dump()
        assert [r.status for r in r2.results] == ["queued", "not_friend", "recipient_unknown"]


async def test_raw_send_queues_raw_job_payload(sm):
    wake = WakeupRegistry()
    async with sm() as s:
        _alice, _bob = await _two_friends_with_caps(s)
        resp = await send_document(
            s, wake, sender_handle="alice", to=["bob"],
            document=None, raw_png_b64="aGk=", idempotency_key=None, sender_rate_per_min=30)
        assert resp.results[0].status == "queued"

        from hub.models import Job

        job = await s.get(Job, resp.results[0].job_id)
        assert job.kind == "raw"
        assert job.payload == {"raw_png_b64": "aGk="}


def test_sendreq_requires_exactly_one_payload():
    doc = {"blocks": [{"type": "paragraph"}]}
    # neither
    with pytest.raises(ValueError):
        SendReq(to=["bob"])
    # both
    with pytest.raises(ValueError):
        SendReq(to=["bob"], document=doc, raw_png_b64="aGk=")
    # invalid base64 for the raw path
    with pytest.raises(ValueError):
        SendReq(to=["bob"], raw_png_b64="not valid base64!!")
    # Empty string raw / empty dict document are FALSY -> "absent". send_document
    # branches on truthiness, so an identity (`is None`) check here would let
    # raw_png_b64="" slip through and queue {"document": None} (an empty job the
    # relay can't render). Both must be rejected as "neither".
    with pytest.raises(ValueError):
        SendReq(to=["bob"], raw_png_b64="")
    with pytest.raises(ValueError):
        SendReq(to=["bob"], document={})
    # each valid form on its own
    assert SendReq(to=["bob"], document=doc).raw_png_b64 is None
    assert SendReq(to=["bob"], raw_png_b64="aGk=").document is None


async def test_send_route_conflicts_on_same_key_changed_request(app_client):
    client, deps = app_client
    async with deps.sessionmaker() as s:
        alice, _bob = await _two_friends_with_caps(s)

    first = await client.post(
        "/send",
        headers={"Authorization": f"Bearer {alice.api_token}"},
        json={
            "to": ["bob"],
            "document": {"blocks": [{"type": "paragraph"}]},
            "idempotency_key": "same-key",
        },
    )
    assert first.status_code == 202

    changed_recipients = await client.post(
        "/send",
        headers={"Authorization": f"Bearer {alice.api_token}"},
        json={
            "to": ["bob", "ghost"],
            "document": {"blocks": [{"type": "paragraph"}]},
            "idempotency_key": "same-key",
        },
    )
    assert changed_recipients.status_code == 409

    changed_payload = await client.post(
        "/send",
        headers={"Authorization": f"Bearer {alice.api_token}"},
        json={
            "to": ["bob"],
            "document": {"blocks": []},
            "idempotency_key": "same-key",
        },
    )
    assert changed_payload.status_code == 409


async def test_sender_throttle(sm):
    wake = WakeupRegistry()
    async with sm() as s:
        alice, bob = await _two_friends_with_caps(s)
        doc = {"blocks": [{"type": "paragraph"}]}
        last = None
        for _ in range(3):
            last = await send_document(s, wake, sender_handle="alice", to=["bob"],
                                       document=doc, idempotency_key=None,
                                       sender_rate_per_min=2)
        assert last.results[0].status == "sender_throttled"
