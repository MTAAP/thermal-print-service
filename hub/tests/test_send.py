import asyncio

import pytest

from hub.capabilities import upsert_capability
from hub.invites import create_invite, redeem_invite
from hub.jobs.wakeup import WakeupRegistry
from hub.schemas import SendReq
from hub.send import SendConflict, SendLimits, send_document

# Generous caps matching the config defaults -- these tests exercise behaviour,
# not the limit boundaries (those live in their own tests below).
LIMITS = SendLimits(
    max_recipients=50, max_document_bytes=256 * 1024, max_raw_png_b64_bytes=8 * 1024 * 1024
)

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
            idempotency_key=None, sender_rate_per_min=30, limits=LIMITS,
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
            idempotency_key=None, sender_rate_per_min=30, limits=LIMITS,
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
            idempotency_key=None, sender_rate_per_min=30, limits=LIMITS,
        )
        assert resp.results[0].status == "incompatible"
        assert resp.results[0].detail is not None


async def test_idempotent_send_returns_same_job_ids(sm):
    wake = WakeupRegistry()
    async with sm() as s:
        alice, bob = await _two_friends_with_caps(s)
        doc = {"blocks": [{"type": "paragraph"}]}
        r1 = await send_document(s, wake, sender_handle="alice", to=["bob"], document=doc,
                                 idempotency_key="k1", sender_rate_per_min=30, limits=LIMITS)
        r2 = await send_document(s, wake, sender_handle="alice", to=["bob"], document=doc,
                                 idempotency_key="k1", sender_rate_per_min=30, limits=LIMITS)
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
            document=doc, idempotency_key="k2", sender_rate_per_min=30, limits=LIMITS)
        r2 = await send_document(
            s, wake, sender_handle="alice", to=["bob", "carol", "ghost"],
            document=doc, idempotency_key="k2", sender_rate_per_min=30, limits=LIMITS)

        assert r2.model_dump() == r1.model_dump()
        assert [r.status for r in r2.results] == ["queued", "not_friend", "recipient_unknown"]


async def test_raw_send_queues_raw_job_payload(sm):
    wake = WakeupRegistry()
    async with sm() as s:
        _alice, _bob = await _two_friends_with_caps(s)
        resp = await send_document(
            s, wake, sender_handle="alice", to=["bob"], document=None, raw_png_b64="aGk=",
            idempotency_key=None, sender_rate_per_min=30, limits=LIMITS)
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
                                       sender_rate_per_min=2, limits=LIMITS)
        assert last.results[0].status == "sender_throttled"


async def test_send_rejects_too_many_recipients(sm):
    # The recipient fan-out is capped at the boundary, before any rows are made.
    from hub.send import SendValidationError

    tight = SendLimits(max_recipients=3, max_document_bytes=256 * 1024,
                       max_raw_png_b64_bytes=8 * 1024 * 1024)
    wake = WakeupRegistry()
    async with sm() as s:
        await _two_friends_with_caps(s)
        with pytest.raises(SendValidationError):
            await send_document(
                s, wake, sender_handle="alice", to=["bob", "carol", "dave", "erin"],
                document={"blocks": []}, idempotency_key=None,
                sender_rate_per_min=30, limits=tight)


async def test_send_rejects_oversized_raw_png(sm):
    # An oversized raw PNG blob is refused before it can be written to jobs.payload.
    import base64

    from hub.send import SendValidationError

    tight = SendLimits(max_recipients=50, max_document_bytes=256 * 1024,
                       max_raw_png_b64_bytes=64)
    wake = WakeupRegistry()
    big = base64.b64encode(b"\x00" * 1024).decode("ascii")  # well over the 64-byte cap
    async with sm() as s:
        await _two_friends_with_caps(s)
        with pytest.raises(SendValidationError):
            await send_document(
                s, wake, sender_handle="alice", to=["bob"], document=None,
                raw_png_b64=big, idempotency_key=None, sender_rate_per_min=30, limits=tight)


async def test_send_rejects_oversized_document(sm):
    # A document serialized over the byte cap is refused (structured blocks are
    # never bulk bytes, so a real composition never trips this).
    from hub.send import SendValidationError

    tight = SendLimits(max_recipients=50, max_document_bytes=128,
                       max_raw_png_b64_bytes=8 * 1024 * 1024)
    wake = WakeupRegistry()
    big_doc = {"blocks": [{"type": "paragraph", "text": "x" * 500}]}
    async with sm() as s:
        await _two_friends_with_caps(s)
        with pytest.raises(SendValidationError):
            await send_document(
                s, wake, sender_handle="alice", to=["bob"], document=big_doc,
                idempotency_key=None, sender_rate_per_min=30, limits=tight)


async def test_send_route_oversized_payload_returns_422(app_client):
    # End-to-end: the JSON /send route maps SendValidationError to a 422 with a
    # clear detail, and creates no job.
    from sqlalchemy import select

    from hub.models import Job

    client, deps = app_client
    deps.config = deps.config.__class__.from_env(
        {"HUB_SESSION_HTTPS_ONLY": "false", "HUB_MAX_RECIPIENTS": "1"}
    )
    async with deps.sessionmaker() as s:
        alice, _bob = await _two_friends_with_caps(s)
    r = await client.post(
        "/send", headers={"Authorization": f"Bearer {alice.api_token}"},
        json={"to": ["bob", "carol"], "document": {"blocks": []}})
    assert r.status_code == 422
    async with deps.sessionmaker() as s:
        assert (await s.execute(select(Job))).scalars().first() is None


async def test_concurrent_same_key_send_dedups_to_one_receipt(tmp_path):
    # Two concurrent same-key sends race the SendReceipt unique constraint: the
    # IntegrityError loser must roll back and replay the winner's result instead
    # of double-creating jobs. A file-backed sqlite gives real cross-session
    # isolation so the two sessions actually contend (the in-memory :memory: pool
    # would share one connection). Mirrors test_invite_register's gather pattern.
    from sqlalchemy import select

    from hub.db import init_models, make_engine, make_sessionmaker
    from hub.models import Job, SendReceipt

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'hub.db'}")
    await init_models(engine)
    sm = make_sessionmaker(engine)
    wake = WakeupRegistry()
    doc = {"blocks": [{"type": "paragraph"}]}
    try:
        async with sm() as s:
            await _two_friends_with_caps(s)

        async def send(payload):
            async with sm() as s:
                try:
                    return await send_document(
                        s, wake, sender_handle="alice", to=["bob"], document=payload,
                        idempotency_key="dup-key", sender_rate_per_min=30, limits=LIMITS)
                except SendConflict as exc:
                    return exc

        r1, r2 = await asyncio.gather(send(doc), send(doc))
        # Both succeeded and returned the SAME job id -- the loser replayed the
        # winner's receipt rather than creating a second job.
        assert not isinstance(r1, SendConflict) and not isinstance(r2, SendConflict)
        assert r1.results[0].job_id == r2.results[0].job_id

        async with sm() as s:
            receipts = (await s.execute(select(SendReceipt))).scalars().all()
            jobs = (await s.execute(select(Job))).scalars().all()
            assert len(receipts) == 1
            assert len(jobs) == 1

        # Same key, CHANGED payload -> a real conflict, on both the cache-hit path
        # and (had it raced) the IntegrityError path.
        async with sm() as s:
            with pytest.raises(SendConflict):
                await send_document(
                    s, wake, sender_handle="alice", to=["bob"],
                    document={"blocks": []}, idempotency_key="dup-key",
                    sender_rate_per_min=30, limits=LIMITS)
    finally:
        await engine.dispose()
