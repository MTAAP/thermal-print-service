from hub.capabilities import upsert_capability


async def _join_pair(deps):
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        alice = await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="alice", display_name="Alice")
        bob = await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600),
            handle="bob", display_name="Bob")
    return alice, bob


async def test_friend_schema_returns_caps(app_client):
    client, deps = app_client
    alice, bob = await _join_pair(deps)
    async with deps.sessionmaker() as s:
        await upsert_capability(s, printer_id=bob.printer_id, renderer_version="1.0.0",
                                blocks_schema={"type": "object"}, block_types=["paragraph"])
    r = await client.get("/friends/bob/schema",
                         headers={"Authorization": f"Bearer {alice.api_token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["renderer_version"] == "1.0.0" and body["block_types"] == ["paragraph"]


async def test_friend_schema_404_for_non_friend(app_client):
    client, deps = app_client
    alice, bob = await _join_pair(deps)
    async with deps.sessionmaker() as s:
        from hub.invites import create_invite, redeem_invite
        await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="carol", display_name="Carol")
    r = await client.get("/friends/carol/schema",
                         headers={"Authorization": f"Bearer {alice.api_token}"})
    assert r.status_code == 404


async def test_friend_schema_nulls_when_no_caps(app_client):
    client, deps = app_client
    alice, bob = await _join_pair(deps)
    r = await client.get("/friends/bob/schema",
                         headers={"Authorization": f"Bearer {alice.api_token}"})
    assert r.status_code == 200 and r.json()["renderer_version"] is None
