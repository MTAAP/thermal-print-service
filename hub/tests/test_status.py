async def _join_pair(deps):
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        alice_code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
        alice = await redeem_invite(s, code=alice_code, handle="alice", display_name="Alice")
        bob_code = await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600)
        bob = await redeem_invite(s, code=bob_code, handle="bob", display_name="Bob")
    return alice, bob


async def test_status_callback_records_printer_unknown_partial(app_client):
    client, deps = app_client
    alice, bob = await _join_pair(deps)
    send = await client.post("/send", headers={"Authorization": f"Bearer {alice.api_token}"},
                             json={"to": ["bob"], "document": {"blocks": []}})
    job_id = send.json()["results"][0]["job_id"]
    bob_auth = {"Authorization": f"Bearer {bob.device_token}"}
    await client.get("/inbox?wait=1", headers=bob_auth)
    await client.post(f"/jobs/{job_id}/ack", headers=bob_auth)

    r = await client.post(f"/jobs/{job_id}/status",
                          headers={"Authorization": f"Bearer {bob.device_token}"},
                          json={"status": "printer_unknown_partial"})
    assert r.status_code == 200
    from hub.models import Job
    async with deps.sessionmaker() as s:
        assert (await s.get(Job, job_id)).state == "printer_unknown_partial"


async def test_device_token_cannot_send(app_client):
    client, deps = app_client
    alice, bob = await _join_pair(deps)
    # using bob's DEVICE token to /send must be rejected (send needs api/console)
    r = await client.post("/send", headers={"Authorization": f"Bearer {bob.device_token}"},
                          json={"to": ["alice"], "document": {"blocks": []}})
    assert r.status_code == 403


async def test_api_token_cannot_poll_inbox(app_client):
    client, deps = app_client
    alice, bob = await _join_pair(deps)
    r = await client.get("/inbox?wait=1", headers={"Authorization": f"Bearer {bob.api_token}"})
    assert r.status_code == 403
