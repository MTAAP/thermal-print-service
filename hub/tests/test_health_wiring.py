import pytest

from hub import config as hub_config


@pytest.fixture(autouse=True)
def clear_build_git_sha_cache():
    hub_config.build_git_sha.cache_clear()
    yield
    hub_config.build_git_sha.cache_clear()


def test_package_imports():
    import hub
    assert hub.__version__ == "0.1.0"


def test_build_git_sha_returns_unknown_when_build_info_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(hub_config, "BUILD_INFO_PATH", tmp_path / "build_info.txt")

    assert hub_config.build_git_sha() == "unknown"


def test_build_git_sha_reads_and_caches_build_info(tmp_path, monkeypatch):
    build_info = tmp_path / "build_info.txt"
    build_info.write_text("abc123\n", encoding="utf-8")
    monkeypatch.setattr(hub_config, "BUILD_INFO_PATH", build_info)

    assert hub_config.build_git_sha() == "abc123"

    build_info.write_text("def456\n", encoding="utf-8")
    assert hub_config.build_git_sha() == "abc123"


def test_build_git_sha_reads_env_path_for_installed_hub(tmp_path, monkeypatch):
    package_parent = tmp_path / "site-packages"
    package_parent.mkdir()
    monkeypatch.setattr(hub_config, "BUILD_INFO_PATH", package_parent / "build_info.txt")
    build_info = tmp_path / "app" / "build_info.txt"
    build_info.parent.mkdir()
    build_info.write_text("deploy-sha\n", encoding="utf-8")
    monkeypatch.setenv("HUB_BUILD_INFO_PATH", str(build_info))

    assert hub_config.build_git_sha() == "deploy-sha"


async def test_healthz(app_client):
    client, _ = app_client
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "git_sha": "unknown", "version": "0.1.0"}


async def test_init_models_runs_migrations_to_head(tmp_path):
    from sqlalchemy import inspect, text

    from hub.db import init_models, make_engine

    db_path = tmp_path / "hub.sqlite"
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")
    await init_models(engine)

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
        columns = await conn.run_sync(
            lambda sync_conn: [
                col["name"] for col in inspect(sync_conn).get_columns("printers")
            ]
        )
        version = (
            await conn.execute(text("select version_num from alembic_version"))
        ).scalar_one()

    await engine.dispose()
    assert "alembic_version" in tables
    assert "alert_ntfy_topic" in columns
    assert version is not None


async def test_init_models_adopts_legacy_baseline_database(tmp_path):
    from alembic import command
    from sqlalchemy import inspect, text

    from hub.db import _alembic_config, init_models, make_engine

    db_path = tmp_path / "legacy-hub.sqlite"
    engine = make_engine(f"sqlite+aiosqlite:///{db_path}")

    def make_legacy(sync_conn):
        cfg = _alembic_config()
        cfg.attributes["connection"] = sync_conn
        command.upgrade(cfg, "0001_initial")
        sync_conn.execute(text("delete from alembic_version"))
        sync_conn.commit()

    async with engine.connect() as conn:
        await conn.run_sync(make_legacy)

    await init_models(engine)

    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: [
                col["name"] for col in inspect(sync_conn).get_columns("printers")
            ]
        )
        version = (
            await conn.execute(text("select version_num from alembic_version"))
        ).scalar_one()

    await engine.dispose()
    assert "alert_ntfy_topic" in columns
    assert version == "0002_add_alert_ntfy_topic"


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

    app = build_default_app()  # synchronous; lifespan opens the DB on uvicorn's loop
    # LifespanManager starts (and on exit cancels) the supervised sweeper task.
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://hub") as c,
    ):
        assert (await c.get("/healthz")).json() == {
            "ok": True,
            "git_sha": "unknown",
            "version": "0.1.0",
        }
        # One route per mounted router. A 404 means the router is not wired;
        # auth/validation rejections (401/403/422/redirect) all prove mounted.
        for method, path in [
            ("GET", "/friends"),          # friends (api)
            ("POST", "/admin/invites"),   # admin
            ("POST", "/register"),        # register
            ("PUT", "/capabilities"),     # capabilities (device)
            ("POST", "/send"),            # send (api/console)
            ("GET", "/inbox"),            # inbox (device)
            ("PUT", "/printers/me/alerts"),  # alerts (device)
            ("GET", "/console/login"),    # console_login
            ("GET", "/"),                 # web console index
            ("GET", "/compose"),          # web compose view
        ]:
            r = await c.request(method, path)
            assert r.status_code != 404, f"{method} {path} is not mounted"
