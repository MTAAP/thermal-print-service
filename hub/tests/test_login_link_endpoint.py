async def _register(deps, handle="pi"):
    from hub.invites import create_invite, redeem_invite
    async with deps.sessionmaker() as s:
        return await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle=handle, display_name=handle.title())


async def test_login_link_minted_with_device_token_actually_logs_in(app_client):
    client, deps = app_client
    pi = await _register(deps)
    r = await client.post(
        "/login-links", headers={"Authorization": f"Bearer {pi.device_token}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in_s"] == deps.config.login_link_ttl_s
    assert body["url"].startswith(f"{deps.config.public_url}/console/login?lt=")
    # The minted link is real: walking /console/login with it establishes a
    # console session (303 redirect to Friends), proving the device-printed link
    # is end-to-end usable, not just a well-formed string.
    code = body["url"].rsplit("lt=", 1)[1]
    login = await client.get(f"/console/login?lt={code}", follow_redirects=False)
    assert login.status_code == 303


async def test_login_link_is_single_use(app_client):
    client, deps = app_client
    pi = await _register(deps)
    r = await client.post(
        "/login-links", headers={"Authorization": f"Bearer {pi.device_token}"}
    )
    code = r.json()["url"].rsplit("lt=", 1)[1]
    first = await client.get(f"/console/login?lt={code}", follow_redirects=False)
    assert first.status_code == 303
    # A second consumption of the same code must fail (the link is consumed).
    second = await client.get(f"/console/login?lt={code}", follow_redirects=False)
    assert second.status_code != 303


async def test_login_link_rejects_api_token(app_client):
    # A login link is bearer-equivalent to a console session, so only the
    # device that owns the handle may mint one. The API token (member actions)
    # must be refused, not silently allowed to mint a session for the handle.
    client, deps = app_client
    pi = await _register(deps)
    r = await client.post(
        "/login-links", headers={"Authorization": f"Bearer {pi.api_token}"}
    )
    assert r.status_code == 403


async def test_login_link_requires_a_token(app_client):
    client, _deps = app_client
    r = await client.post("/login-links")
    assert r.status_code == 401
