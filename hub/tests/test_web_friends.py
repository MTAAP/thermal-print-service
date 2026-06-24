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


async def test_invite_button_htmx_without_session_redirects_browser(app_client):
    client, _ = app_client
    r = await client.post(
        "/friends/invite",
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert r.headers["HX-Redirect"] == "/console/login"
    assert r.text == ""


# ----- handle disambiguation (same display name, different handles) -----


async def _seed_friend(deps, alice, handle, display_name):
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        return await redeem_invite(
            s,
            code=await create_invite(
                s, issuer_printer_id=alice.printer_id, ttl_s=3600
            ),
            handle=handle, display_name=display_name,
        )


async def test_friends_view_shows_handle_not_just_display_name(web_client):
    client, deps, alice = web_client
    # Two friends with the SAME display name -- the exact case that rendered an
    # indistinguishable "double Robin" before. The handle must be visible text.
    await _seed_friend(deps, alice, "robin", "Robin")
    await _seed_friend(deps, alice, "rdbeerman", "Robin")
    r = await client.get("/")
    assert r.status_code == 200
    assert "@robin" in r.text
    assert "@rdbeerman" in r.text


async def test_compose_shows_handle_not_just_display_name(web_client):
    client, deps, alice = web_client
    await _seed_friend(deps, alice, "robin", "Robin")
    await _seed_friend(deps, alice, "rdbeerman", "Robin")
    r = await client.get("/compose")
    assert r.status_code == 200
    assert "@robin" in r.text
    assert "@rdbeerman" in r.text


# ----- remove friend (unfriend) -----


async def test_friends_list_has_remove_control(web_client):
    client, deps, alice = web_client
    await _seed_friend(deps, alice, "bob", "Bob")
    r = await client.get("/")
    assert 'data-testid="remove-friend"' in r.text
    assert "/friends/bob/remove" in r.text


async def test_remove_friend_htmx_deletes_and_returns_fragment(web_client):
    client, deps, alice = web_client
    await _seed_friend(deps, alice, "bob", "Bob")
    assert 'data-friend="bob"' in (await client.get("/")).text

    r = await client.post("/friends/bob/remove", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert 'data-friend="bob"' not in r.text
    # Fragment only -- never nest the full console (the duplicate-UI bug).
    for marker in ("app-shell", 'data-testid="nav"', 'data-testid="friends-view"'):
        assert marker not in r.text, f"remove fragment leaked full-page marker {marker!r}"
    # Gone from the canonical friends view too.
    assert 'data-friend="bob"' not in (await client.get("/")).text


async def test_remove_friend_no_js_returns_full_page(web_client):
    client, deps, alice = web_client
    await _seed_friend(deps, alice, "bob", "Bob")
    r = await client.post("/friends/bob/remove")  # no HX-Request header
    assert r.status_code == 200
    assert 'data-testid="friends-view"' in r.text
    assert "app-shell" in r.text
    assert 'data-friend="bob"' not in r.text


async def test_remove_targets_handle_not_display_name(web_client):
    client, deps, alice = web_client
    # The whole point: two friends share display "Robin"; removing by handle must
    # drop ONLY that handle and leave the other intact.
    await _seed_friend(deps, alice, "robin", "Robin")
    await _seed_friend(deps, alice, "rdbeerman", "Robin")
    r = await client.post("/friends/robin/remove", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert 'data-friend="robin"' not in r.text
    assert 'data-friend="rdbeerman"' in r.text


async def test_remove_unknown_handle_is_noop(web_client):
    client, _deps, _alice = web_client
    # A handle that is not a friend (or not a printer at all) must not 500.
    r = await client.post("/friends/ghost/remove", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert 'data-testid="friends-list"' in r.text


async def test_remove_friend_requires_session(app_client):
    client, _ = app_client
    r = await client.post(
        "/friends/bob/remove", headers={"HX-Request": "true"}, follow_redirects=False
    )
    assert r.status_code == 204
    assert r.headers["HX-Redirect"] == "/console/login"
