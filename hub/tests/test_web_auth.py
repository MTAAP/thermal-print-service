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


def _console_token_from_cookie(client, deps) -> str:
    """Recover the CONSOLE token plaintext riding in the signed session cookie.

    The plaintext is minted server-side and never returned in a response body, so
    the only way to assert revoke-on-logout end-to-end is to unsign the cookie the
    login walk set -- exactly as SessionMiddleware does on the way back in."""
    import base64
    import json

    import itsdangerous

    from hub.web_auth import SESSION_TOKEN_KEY

    raw = client.cookies["session"]
    signer = itsdangerous.TimestampSigner(deps.config.session_secret)
    data = signer.unsign(raw.encode())
    return json.loads(base64.b64decode(data))[SESSION_TOKEN_KEY]


async def test_logout_revokes_console_token_server_side(web_client):
    # Logout must do more than clear the cookie: it must REVOKE the CONSOLE token
    # in the DB so a leaked/captured plaintext can never authenticate again.
    import pytest
    from sqlalchemy import select

    from hub.auth import TokenKind, authenticate, hash_token
    from hub.models import Token

    client, deps, _alice = web_client
    plaintext = _console_token_from_cookie(client, deps)

    # Sanity: the captured plaintext authenticates as a CONSOLE token pre-logout.
    async with deps.sessionmaker() as s:
        await authenticate(s, plaintext, required=TokenKind.CONSOLE)

    r = await client.post("/console/logout", follow_redirects=False)
    assert r.status_code in (302, 303)

    async with deps.sessionmaker() as s:
        with pytest.raises(PermissionError):
            await authenticate(s, plaintext, required=TokenKind.CONSOLE)
        row = (
            await s.execute(select(Token).where(Token.token_hash == hash_token(plaintext)))
        ).scalar_one()
        assert row.revoked_at is not None


async def test_session_cookie_is_lax_httponly(web_client):
    # SameSite=Lax + HttpOnly on the session cookie IS the entire CSRF model for
    # authed console POSTs, so both attributes are load-bearing. The login walk
    # already set the cookie; re-trigger a Set-Cookie by hitting a session-writing
    # route and inspect its attributes.
    client, _deps, _alice = web_client
    r = await client.get("/")
    set_cookie = r.headers.get("set-cookie", "")
    if "session=" not in set_cookie:
        # The cookie was set during the login walk in the fixture; replay it.
        r = await client.post("/console/logout", follow_redirects=False)
        set_cookie = r.headers.get("set-cookie", "")
    assert "session=" in set_cookie
    lowered = set_cookie.lower()
    assert "samesite=lax" in lowered
    assert "httponly" in lowered


async def _login_walk(app_client, handle="alice"):
    """Run the real login walk and return the response that set the cookie, so a
    test can inspect the Set-Cookie attributes the prod path emits. The handle is
    parameterized so one shared engine can host more than one walk."""
    client, deps = app_client
    from hub.invites import create_invite, redeem_invite
    from hub.login import create_login_link

    async with deps.sessionmaker() as s:
        await redeem_invite(
            s, code=await create_invite(s, issuer_printer_id=None, ttl_s=3600),
            handle=handle, display_name=handle.title())
        link = await create_login_link(s, handle=handle, ttl_s=600)
    return await client.get(f"/console/login?lt={link}", follow_redirects=False)


async def test_session_cookie_secure_flag_follows_https_only(sm):
    # The Secure flag must track HUB_SESSION_HTTPS_ONLY: on behind TLS (prod), off
    # for local HTTP dev. Build the app both ways and assert the cookie attribute.
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from hub.app import create_app
    from hub.config import HubConfig
    from hub.jobs.wakeup import WakeupRegistry
    from hub.presence import Presence
    from hub.routes import AppDeps

    async def cookie_for(https_only: str, handle: str) -> str:
        deps = AppDeps(config=HubConfig.from_env({"HUB_SESSION_HTTPS_ONLY": https_only}),
                       sessionmaker=sm, wake=WakeupRegistry(), online=Presence())
        app = create_app(deps, run_sweeper=False)
        async with LifespanManager(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://hub") as c:
                r = await _login_walk((c, deps), handle=handle)
                return r.headers.get("set-cookie", "")

    secure_cookie = await cookie_for("true", "secureuser")
    assert "session=" in secure_cookie
    assert "secure" in secure_cookie.lower()

    insecure_cookie = await cookie_for("false", "plainuser")
    assert "session=" in insecure_cookie
    assert "secure" not in insecure_cookie.lower()
