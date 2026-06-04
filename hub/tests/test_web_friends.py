async def test_no_session_redirects_to_login(app_client):
    client, _ = app_client
    r = await client.get("/", follow_redirects=False)
    # Unauthenticated console view -> redirect to the login landing.
    assert r.status_code in (302, 303)
    assert "/console/login" in r.headers["location"]


async def test_bearer_token_cannot_reach_console_view(app_client):
    client, deps = app_client
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        alice = await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle="alice", display_name="Alice")
    # An Authorization header must be IGNORED by web routes (cookie-only).
    r = await client.get("/", follow_redirects=False,
                         headers={"Authorization": f"Bearer {alice.api_token}"})
    assert r.status_code in (302, 303)
    assert "/console/login" in r.headers["location"]
    # The device token is equally powerless against console views.
    r2 = await client.get("/", follow_redirects=False,
                          headers={"Authorization": f"Bearer {alice.device_token}"})
    assert r2.status_code in (302, 303)


async def test_valid_session_reaches_friends(web_client):
    client, _deps, _alice = web_client
    r = await client.get("/")
    assert r.status_code == 200
    assert 'data-testid="friends-view"' in r.text


async def test_logout_then_friends_redirects_to_login(web_client):
    client, _deps, _alice = web_client
    await client.post("/console/logout", follow_redirects=False)
    # After logout the session is gone -> Friends redirects to login again.
    r = await client.get("/", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/console/login" in r.headers["location"]


async def test_friends_view_lists_friends_with_status(web_client):
    client, deps, alice = web_client
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        bob = await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600),
            handle="bob", display_name="Bob")
        # mark bob online via the presence set
        deps.online.add(bob.printer_id)

    r = await client.get("/")
    assert r.status_code == 200
    assert 'data-testid="friends-view"' in r.text
    # the friend row exists and carries a stable status hook
    assert 'data-friend="bob"' in r.text
    assert 'data-online="true"' in r.text


async def test_friends_view_offline_friend(web_client):
    client, deps, alice = web_client
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600),
            handle="bob", display_name="Bob")
    r = await client.get("/")
    assert 'data-friend="bob"' in r.text
    assert 'data-online="false"' in r.text


async def test_invite_button_htmx_returns_code_fragment_only(web_client):
    client, _deps, _alice = web_client
    r = await client.post("/friends/invite", headers={"HX-Request": "true"})
    assert r.status_code == 200
    # the generated invite code is surfaced in a stable hook
    assert 'data-testid="invite-code"' in r.text
    # Both onboarding paths are offered: a shareable web /join link (Pi-less
    # friend) and the raw code for the Pi CLI (`printer-svc hub join <code>`).
    assert 'data-testid="invite-join-url"' in r.text
    assert "/join?code=" in r.text
    assert "printer-svc hub join" in r.text
    # Fragment only -- the full friends page (shell, nav, friends-view) must NOT
    # come back into the #invite-slot innerHTML swap (the duplicate-UI bug).
    for marker in ("app-shell", 'data-testid="nav"', 'data-testid="friends-view"'):
        assert marker not in r.text, f"HTMX fragment leaked full-page marker {marker!r}"


async def test_invite_button_no_js_returns_full_page(web_client):
    client, _deps, _alice = web_client
    r = await client.post("/friends/invite")
    assert r.status_code == 200
    assert 'data-testid="invite-code"' in r.text
    # No-JS fallback: the whole friends page, code rendered in its slot.
    assert 'data-testid="friends-view"' in r.text
    assert "app-shell" in r.text
