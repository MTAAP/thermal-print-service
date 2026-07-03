from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# libpq URL query params that asyncpg's DBAPI rejects as unknown connect kwargs.
# Railway's internal DATABASE_URL omits them, but the proxy/public form (or a
# future platform change) can append ?sslmode=require, which would crash
# create_async_engine on the first connection rather than loudly at config time.
_ASYNC_INCOMPATIBLE_QUERY = {"sslmode", "channel_binding"}
_BASELINE_REVISION = "0001_initial"
_HEAD_REVISION = "head"


def _normalize_async_url(url: str) -> str:
    """Coerce a libpq-style Postgres URL into SQLAlchemy's asyncpg form.

    Railway (and Heroku-style) Postgres hand out ``postgres://`` / ``postgresql://``
    with the implicit sync psycopg2 driver. SQLAlchemy's async engine needs an
    explicit async driver, so pin ``+asyncpg`` and drop the libpq-only query
    params asyncpg cannot accept. Non-Postgres URLs (our ``sqlite+aiosqlite``
    dev/test default) already name an async driver and pass through untouched.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    elif not scheme.startswith("postgresql+"):
        return url
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _ASYNC_INCOMPATIBLE_QUERY
    ]
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def make_engine(database_url: str) -> AsyncEngine:
    # pool_pre_ping: managed Postgres (Railway) recycles idle connections, so a
    # long-idle hub would otherwise serve a dead connection on the next request.
    return create_async_engine(
        _normalize_async_url(database_url), future=True, pool_pre_ping=True
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine: AsyncEngine) -> None:
    import hub.models  # noqa: F401  (register mappers before migrations)

    async with engine.connect() as conn:
        await conn.run_sync(_upgrade_schema)


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "hub:alembic")
    cfg.set_main_option("prepend_sys_path", ".")
    cfg.set_main_option("path_separator", "os")
    return cfg


def _upgrade_schema(connection) -> None:
    cfg = _alembic_config()
    cfg.attributes["connection"] = connection
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    has_recorded_version = False
    if "alembic_version" in tables:
        has_recorded_version = (
            connection.execute(text("select 1 from alembic_version limit 1")).first()
            is not None
        )

    if not has_recorded_version and "printers" in tables:
        printer_columns = {col["name"] for col in inspector.get_columns("printers")}
        revision = _HEAD_REVISION if "alert_ntfy_topic" in printer_columns else _BASELINE_REVISION
        command.stamp(cfg, revision)

    command.upgrade(cfg, _HEAD_REVISION)
    if connection.in_transaction():
        connection.commit()


async def session_scope(
    sm: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with sm() as session:
        yield session
