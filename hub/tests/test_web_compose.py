async def _friend(deps, alice, handle="bob"):
    from hub.capabilities import upsert_capability
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        bob = await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600),
            handle=handle, display_name=handle.title())
        # a permissive schema so the common-core doc validates
        await upsert_capability(s, printer_id=bob.printer_id, renderer_version="1.0.0",
                                blocks_schema={"type": "object"}, block_types=["paragraph"])
    return bob


async def test_compose_get_lists_friends_as_recipients(web_client):
    client, deps, alice = web_client
    await _friend(deps, alice)
    r = await client.get("/compose")
    assert r.status_code == 200
    assert 'data-testid="compose-view"' in r.text
    assert 'value="bob"' in r.text  # selectable recipient


async def test_compose_post_sends_and_shows_per_recipient_results(web_client):
    client, deps, alice = web_client
    await _friend(deps, alice)
    r = await client.post("/compose", data={
        "to": ["bob"], "title": "", "message": "thinking of you",
    })
    assert r.status_code == 200
    assert 'data-testid="send-results"' in r.text
    assert 'data-result-to="bob"' in r.text
    assert 'data-result-status="queued"' in r.text


async def test_compose_post_multi_recipient_partial(web_client):
    client, deps, alice = web_client
    await _friend(deps, alice, handle="bob")
    # carol exists but is NOT alice's friend
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="carol", display_name="Carol")

    r = await client.post("/compose", data={
        "to": ["bob", "carol", "ghost"], "title": "Hi", "message": "hello",
    })
    assert 'data-result-to="bob"' in r.text and 'data-result-status="queued"' in r.text
    assert 'data-result-to="carol"' in r.text and 'data-result-status="not_friend"' in r.text
    assert 'data-result-to="ghost"' in r.text and 'data-result-status="recipient_unknown"' in r.text


async def test_compose_requires_session(app_client):
    client, _ = app_client
    r = await client.get("/compose", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/console/login" in r.headers["location"]
