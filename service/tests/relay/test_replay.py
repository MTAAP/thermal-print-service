from printer.relay.config import RelayConfig
from printer.relay.hub_client import HubClient
from printer.relay.local_client import LocalClient
from printer.relay.loop import RelayClient
from printer.relay.store import JobMap


def _cfg(relay_paths):
    return RelayConfig.from_env({
        "HUB_URL": "http://hub.test",
        "PRINTER_RELAY_STATE_DIR": str(relay_paths.root),
    })


async def test_replay_reports_terminal_for_delivered_then_printed(
    relay_paths, mock_hub, hub_http, fake_deps,
):
    from tests.conftest import lifespan_client

    async with lifespan_client(fake_deps) as local_ac:
        # Submit a real local job so it reaches `printed`, then simulate a crash
        # by recording the map at 'delivered' and constructing a fresh relay.
        local = LocalClient(local_ac)
        from printer.relay.from_tag import from_header_block
        doc = from_header_block(
            {"blocks": [{"type": "paragraph", "text": "hi"}]},
            sender="alice", sent_at="2026-06-03T14:32:00+00:00",
        )
        res = await local.print_document(doc, sender="friend:alice", idempotency_key="hj1")
        # Pre-seed the map as if we crashed right after the delivered ACK.
        JobMap(relay_paths.jobmap_path).put(
            "hj1", local_job_id=res.local_job_id, last_status="delivered"
        )

        # Give the worker a moment to print.
        import asyncio
        for _ in range(20):
            if await local.get_job_status(res.local_job_id) == "printed":
                break
            await asyncio.sleep(0.05)

        client = RelayClient(
            _cfg(relay_paths), relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=local,
        )
        await client.replay_unfinished()

    assert ("hj1", "printed") in mock_hub.statuses
    assert JobMap(relay_paths.jobmap_path).get("hj1")["last_status"] == "printed"


async def test_replay_reports_printer_expired_when_local_job_gone(
    relay_paths, mock_hub, hub_http, fake_deps,
):
    from tests.conftest import lifespan_client

    # Map references a local job id that never existed -> GET /jobs/{id} 404.
    JobMap(relay_paths.jobmap_path).put(
        "hjghost", local_job_id="job_does_not_exist", last_status="delivered"
    )
    async with lifespan_client(fake_deps) as local_ac:
        client = RelayClient(
            _cfg(relay_paths), relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=LocalClient(local_ac),
        )
        await client.replay_unfinished()
    assert ("hjghost", "printer_expired") in mock_hub.statuses


async def test_replay_tolerates_hub_409_and_advances_jobmap(
    relay_paths, mock_hub, hub_http, fake_deps,
):
    # Fix A regression: a job stuck at 'delivered' whose hub already considers it
    # terminal in a DIFFERENT state. Before Fix A the 409 raised out of replay
    # (which runs at startup) and crash-looped the relay permanently, since the
    # map never advanced past 'delivered'. Now replay must swallow the 409 and
    # move the map to terminal so the job is never retried again.
    from tests.conftest import lifespan_client

    # Pre-seed the hub with a DIFFERENT terminal status so replay's later
    # 'printed' post conflicts -> 409 (a same-status re-post would be an
    # idempotent 200 and never exercise the 409 branch).
    mock_hub._terminal_status["hjconf"] = "printer_expired"
    async with lifespan_client(fake_deps) as local_ac:
        local = LocalClient(local_ac)
        from printer.relay.from_tag import from_header_block
        doc = from_header_block(
            {"blocks": [{"type": "paragraph", "text": "hi"}]},
            sender="alice", sent_at="2026-06-03T14:32:00+00:00",
        )
        res = await local.print_document(doc, sender="friend:alice", idempotency_key="hjconf")
        JobMap(relay_paths.jobmap_path).put(
            "hjconf", local_job_id=res.local_job_id, last_status="delivered"
        )

        import asyncio
        for _ in range(20):
            if await local.get_job_status(res.local_job_id) == "printed":
                break
            await asyncio.sleep(0.05)

        client = RelayClient(
            _cfg(relay_paths), relay_paths,
            hub=HubClient(hub_http, device_token="dev-token", api_token="api-token"),
            local=local,
        )
        # Must not raise even though the hub returns 409 for the conflicting post.
        await client.replay_unfinished()

    # The map advanced past 'delivered' (to the locally-observed terminal status),
    # so a subsequent restart would not re-trigger the 409.
    assert JobMap(relay_paths.jobmap_path).get("hjconf")["last_status"] == "printed"
