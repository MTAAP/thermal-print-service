async def test_login_link_invalid_shows_landing(app_client):
    client, _ = app_client
    r = await client.get("/console/login?lt=not-a-real-link", follow_redirects=False)
    # Invalid link -> render the login landing (200), not a redirect loop.
    assert r.status_code == 200
    assert 'data-testid="login-landing"' in r.text


async def test_login_landing_without_link(app_client):
    client, _ = app_client
    r = await client.get("/console/login", follow_redirects=False)
    assert r.status_code == 200
    assert 'data-testid="login-landing"' in r.text


async def test_valid_login_link_sets_session_cookie_and_redirects(app_client):
    client, deps = app_client
    from hub.invites import create_invite, redeem_invite
    from hub.login import create_login_link
    async with deps.sessionmaker() as s:
        await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="alice", display_name="Alice")
        link = await create_login_link(s, handle="alice", ttl_s=600)
    r = await client.get(f"/console/login?lt={link}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    # the signed session cookie was set
    assert "session" in r.headers.get("set-cookie", "")


async def test_logout_redirects_to_login(web_client):
    client, _deps, _alice = web_client
    r = await client.post("/console/logout", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/console/login" in r.headers["location"]
