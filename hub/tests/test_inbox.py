import asyncio


async def test_inbox_returns_queued_job_then_ack(app_client):
    client, deps = app_client
    # Build state directly via the session for clarity.
    from hub.capabilities import upsert_capability
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        alice_code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
        alice = await redeem_invite(s, code=alice_code, handle="alice", display_name="Alice")
        bob_code = await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600)
        bob = await redeem_invite(s, code=bob_code, handle="bob", display_name="Bob")
        await upsert_capability(s, printer_id=bob.printer_id, renderer_version="1.0.0",
                                blocks_schema={"type": "object"}, block_types=["paragraph"])

    # alice sends to bob
    r = await client.post("/send", headers={"Authorization": f"Bearer {alice.api_token}"},
                          json={"to": ["bob"], "document": {"blocks": []}})
    assert r.status_code == 202
    job_id = r.json()["results"][0]["job_id"]

    # bob polls inbox (job already queued -> immediate return)
    r = await client.get("/inbox?wait=1", headers={"Authorization": f"Bearer {bob.device_token}"})
    assert r.status_code == 200
    assert r.json()["job"]["job_id"] == job_id

    # bob acks delivered
    r = await client.post(f"/jobs/{job_id}/ack",
                          headers={"Authorization": f"Bearer {bob.device_token}"})
    assert r.status_code == 200


async def test_inbox_long_poll_wakes_on_send(app_client):
    client, deps = app_client
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        alice_code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
        alice = await redeem_invite(s, code=alice_code, handle="alice", display_name="Alice")
        bob_code = await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600)
        bob = await redeem_invite(s, code=bob_code, handle="bob", display_name="Bob")

    async def poll():
        return await client.get("/inbox?wait=5",
                                headers={"Authorization": f"Bearer {bob.device_token}"})

    poll_task = asyncio.create_task(poll())
    await asyncio.sleep(0.2)  # ensure the poll is waiting
    await client.post("/send", headers={"Authorization": f"Bearer {alice.api_token}"},
                      json={"to": ["bob"], "document": {"blocks": []}})
    r = await poll_task
    assert r.status_code == 200 and r.json()["job"] is not None


async def test_inbox_empty_poll_times_out(app_client):
    client, deps = app_client
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        bob_code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
        bob = await redeem_invite(s, code=bob_code, handle="bob", display_name="Bob")
    r = await client.get("/inbox?wait=1", headers={"Authorization": f"Bearer {bob.device_token}"})
    assert r.status_code == 200 and r.json()["job"] is None


async def test_ack_and_status_reject_non_owner_device(app_client):
    """A device may only ack / report status on jobs addressed to it. A stranger
    device with a valid token must get 404 (not 403, to avoid leaking job
    existence), while the rightful recipient still succeeds. Regression guard for
    the IDOR on /jobs/{id}/ack and /jobs/{id}/status."""
    client, deps = app_client
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        alice = await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="alice", display_name="Alice")
        bob = await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600),
            handle="bob", display_name="Bob")
        # carol holds a valid device token but is not the job's recipient.
        carol = await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="carol", display_name="Carol")

    # alice -> bob; bob leases it so it is in 'leased' state.
    r = await client.post("/send", headers={"Authorization": f"Bearer {alice.api_token}"},
                          json={"to": ["bob"], "document": {"blocks": []}})
    job_id = r.json()["results"][0]["job_id"]
    r = await client.get("/inbox?wait=1", headers={"Authorization": f"Bearer {bob.device_token}"})
    assert r.json()["job"]["job_id"] == job_id

    # carol must not ack or report status on bob's job.
    r = await client.post(f"/jobs/{job_id}/ack",
                          headers={"Authorization": f"Bearer {carol.device_token}"})
    assert r.status_code == 404
    r = await client.post(f"/jobs/{job_id}/status", json={"status": "printed"},
                          headers={"Authorization": f"Bearer {carol.device_token}"})
    assert r.status_code == 404

    # the rightful recipient still succeeds, and an unknown job id is 404 (not 409).
    r = await client.post(f"/jobs/{job_id}/ack",
                          headers={"Authorization": f"Bearer {bob.device_token}"})
    assert r.status_code == 200
    r = await client.post("/jobs/job_does_not_exist/status", json={"status": "printed"},
                          headers={"Authorization": f"Bearer {bob.device_token}"})
    assert r.status_code == 404
