from hub.db import _normalize_async_url


def test_railway_postgresql_scheme_gets_asyncpg_driver():
    out = _normalize_async_url("postgresql://u:p@host.railway.internal:5432/railway")
    assert out == "postgresql+asyncpg://u:p@host.railway.internal:5432/railway"


def test_heroku_style_postgres_scheme_gets_asyncpg_driver():
    out = _normalize_async_url("postgres://u:p@host:5432/db")
    assert out == "postgresql+asyncpg://u:p@host:5432/db"


def test_libpq_only_query_params_are_stripped():
    # asyncpg's DBAPI rejects sslmode / channel_binding; they must not survive
    # into the connect kwargs or the engine crashes on first connect.
    out = _normalize_async_url(
        "postgresql://u:p@host:5432/db?sslmode=require&channel_binding=prefer"
    )
    assert out == "postgresql+asyncpg://u:p@host:5432/db"


def test_benign_query_params_are_preserved():
    out = _normalize_async_url(
        "postgresql://u:p@host:5432/db?application_name=hub&sslmode=require"
    )
    assert out == "postgresql+asyncpg://u:p@host:5432/db?application_name=hub"


def test_already_async_url_keeps_driver_but_still_strips_incompatible_params():
    out = _normalize_async_url("postgresql+asyncpg://u:p@host:5432/db?sslmode=require")
    assert out == "postgresql+asyncpg://u:p@host:5432/db"


def test_sqlite_async_default_is_untouched():
    url = "sqlite+aiosqlite:///./hub.db"
    assert _normalize_async_url(url) == url
