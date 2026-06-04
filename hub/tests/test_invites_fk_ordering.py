"""Regression: invite redemption must satisfy FK constraints in flush order.

SQLite leaves foreign-key enforcement OFF by default, so the original
redeem_invite (which set invites.redeemed_by before the new printer row was
flushed) passed every test yet failed on Postgres with a ForeignKeyViolation.
This fixture turns SQLite FK enforcement ON so the same ordering bug is caught
in CI, on both the root path and the friendship path.
"""
import pytest_asyncio
from sqlalchemy import event

from hub.db import Base, make_engine, make_sessionmaker
from hub.invites import create_invite, redeem_invite


@pytest_asyncio.fixture
async def fk_sm():
    engine = make_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _enforce_fks(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    import hub.models  # noqa: F401  register mappers before create_all
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield make_sessionmaker(engine)
    await engine.dispose()


async def test_root_redeem_satisfies_fks(fk_sm):
    async with fk_sm() as s:
        code = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
    async with fk_sm() as s:
        reg = await redeem_invite(s, code=code, handle="alice", display_name="Alice")
    assert reg.handle == "alice" and reg.inviter_handle is None


async def test_friend_redeem_satisfies_fks(fk_sm):
    # The friendship path adds the most FK-bearing rows: two Friendship rows
    # (owner_id/friend_id -> printers) plus the invite redeemed_by + tokens.
    async with fk_sm() as s:
        root = await create_invite(s, issuer_printer_id=None, ttl_s=3600)
    async with fk_sm() as s:
        alice = await redeem_invite(s, code=root, handle="alice", display_name="Alice")
    async with fk_sm() as s:
        code = await create_invite(s, issuer_printer_id=alice.printer_id, ttl_s=3600)
    async with fk_sm() as s:
        bob = await redeem_invite(s, code=code, handle="bob", display_name="Bob")
    assert bob.inviter_handle == "alice"
