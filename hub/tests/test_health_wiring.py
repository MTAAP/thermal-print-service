def test_package_imports():
    import hub
    assert hub.__version__ == "0.1.0"


async def test_healthz(app_client):
    client, _ = app_client
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


async def test_build_default_app_boots_and_mounts_all_routers(monkeypatch):
    """Boot the REAL production factory (build_default_app -> create_app with the
    default run_sweeper=True) through the lifespan. The app_client fixture uses
    run_sweeper=False and hand-built deps, so this is the only test that exercises
    the actual entrypoint wiring: the supervised sweeper task starting + cancelling
    cleanly, and every router being mounted on the real factory."""
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from hub.app import build_default_app

    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("HUB_SESSION_HTTPS_ONLY", "false")

    app = await build_default_app()
    # LifespanManager starts (and on exit cancels) the supervised sweeper task.
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://hub") as c,
    ):
        assert (await c.get("/healthz")).json() == {"ok": True}
        # One route per mounted router. A 404 means the router is not wired;
        # auth/validation rejections (401/403/422/redirect) all prove mounted.
        for method, path in [
            ("GET", "/friends"),          # friends (api)
            ("POST", "/admin/invites"),   # admin
            ("POST", "/register"),        # register
            ("PUT", "/capabilities"),     # capabilities (device)
            ("POST", "/send"),            # send (api/console)
            ("GET", "/inbox"),            # inbox (device)
            ("GET", "/console/login"),    # console_login
            ("GET", "/"),                 # web console index
            ("GET", "/compose"),          # web compose view
        ]:
            r = await c.request(method, path)
            assert r.status_code != 404, f"{method} {path} is not mounted"
