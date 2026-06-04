async def _make_invite(deps, issuer=None, ttl_s=3600):
    from hub.invites import create_invite
    async with deps.sessionmaker() as s:
        return await create_invite(s, issuer_printer_id=issuer, ttl_s=ttl_s)


async def test_join_get_prefills_code(app_client):
    client, _deps = app_client
    r = await client.get("/join?code=ABC123")
    assert r.status_code == 200
    assert 'data-testid="join-view"' in r.text
    assert 'value="ABC123"' in r.text  # the shared link prefills the code


async def test_join_get_without_code_renders_empty_form(app_client):
    client, _deps = app_client
    r = await client.get("/join")
    assert r.status_code == 200
    assert 'data-testid="join-code"' in r.text


async def test_join_redeems_invite_and_signs_in(app_client):
    # The core of the web-only path: redeem -> instant console session, no Pi.
    client, deps = app_client
    code = await _make_invite(deps)
    r = await client.post("/join", follow_redirects=False, data={
        "code": code, "handle": "newbie", "display_name": "New Bie",
    })
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    # The cookie jar now carries a console session: Friends loads without any
    # login link, proving join established the session directly.
    home = await client.get("/")
    assert home.status_code == 200
    assert 'data-testid="friends-view"' in home.text
    # And the session is bound to the NEWLY created handle, not some other account.
    assert 'data-testid="current-handle"' in home.text
    assert ">newbie<" in home.text


async def test_join_unknown_code_rerenders_with_error(app_client):
    client, _deps = app_client
    r = await client.post("/join", follow_redirects=False, data={
        "code": "nope-not-a-real-code", "handle": "x", "display_name": "X",
    })
    assert r.status_code == 200
    assert 'data-testid="join-error"' in r.text  # no redirect, error shown


async def test_join_taken_handle_rerenders_with_error(app_client):
    client, deps = app_client
    from hub.invites import redeem_invite
    async with deps.sessionmaker() as s:
        await redeem_invite(s, code=await _make_invite(deps), handle="dup", display_name="Dup")
    # A different, valid invite but the same handle -> rejected.
    r = await client.post("/join", follow_redirects=False, data={
        "code": await _make_invite(deps), "handle": "dup", "display_name": "Dup Two",
    })
    assert r.status_code == 200
    assert 'data-testid="join-error"' in r.text


async def test_join_bad_handle_format_rerenders_with_error(app_client):
    # Reuses the RegisterReq contract: uppercase/spaces/punctuation are rejected
    # exactly as the JSON /register path would reject them.
    client, deps = app_client
    r = await client.post("/join", follow_redirects=False, data={
        "code": await _make_invite(deps), "handle": "Bad Handle!", "display_name": "Bad",
    })
    assert r.status_code == 200
    assert 'data-testid="join-error"' in r.text


async def test_join_bad_display_name_rerenders_with_error(app_client):
    # display_name has no client-side maxlength guarantee server-side, so an
    # over-length value must still be caught and shown as an error (not crash).
    client, deps = app_client
    r = await client.post("/join", follow_redirects=False, data={
        "code": await _make_invite(deps), "handle": "okhandle", "display_name": "x" * 81,
    })
    assert r.status_code == 200
    assert 'data-testid="join-error"' in r.text


async def test_join_rejects_cross_origin_post(app_client):
    # Login-CSRF guard: a form POST from another origin is refused before any
    # account/session is created.
    client, deps = app_client
    r = await client.post("/join", follow_redirects=False,
                          headers={"Origin": "https://evil.example"}, data={
        "code": await _make_invite(deps), "handle": "victim", "display_name": "Victim",
    })
    assert r.status_code == 403


async def test_join_allows_same_origin_post(app_client):
    # A matching Origin (our own public_url host) is accepted normally.
    client, deps = app_client
    r = await client.post("/join", follow_redirects=False,
                          headers={"Origin": "https://hub.example.invalid"}, data={
        "code": await _make_invite(deps), "handle": "samesite", "display_name": "Same Site",
    })
    assert r.status_code == 303
