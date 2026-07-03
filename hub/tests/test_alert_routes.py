from __future__ import annotations


async def test_device_can_set_and_clear_alert_topic(app_client):
    client, deps = app_client
    from hub.invites import create_invite, redeem_invite
    from hub.models import Printer

    async with deps.sessionmaker() as s:
        bob = await redeem_invite(
            s,
            code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="bob",
            display_name="Bob",
        )

    auth = {"Authorization": f"Bearer {bob.device_token}"}
    r = await client.put(
        "/printers/me/alerts",
        headers=auth,
        json={"ntfy_topic": "example-alert-topic"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "ntfy_topic": "example-alert-topic"}

    async with deps.sessionmaker() as s:
        assert (await s.get(Printer, bob.printer_id)).alert_ntfy_topic == "example-alert-topic"

    r = await client.put("/printers/me/alerts", headers=auth, json={"ntfy_topic": "   "})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "ntfy_topic": None}

    async with deps.sessionmaker() as s:
        assert (await s.get(Printer, bob.printer_id)).alert_ntfy_topic is None


async def test_alert_topic_endpoint_requires_device_token(app_client):
    client, deps = app_client
    from hub.invites import create_invite, redeem_invite

    async with deps.sessionmaker() as s:
        bob = await redeem_invite(
            s,
            code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="bob",
            display_name="Bob",
        )

    r = await client.put(
        "/printers/me/alerts",
        headers={"Authorization": f"Bearer {bob.api_token}"},
        json={"ntfy_topic": "example-alert-topic"},
    )
    assert r.status_code == 403
