from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from hub.db import Base


class Printer(Base):
    __tablename__ = "printers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    handle: Mapped[str] = mapped_column(String, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String)
    renderer_version: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Token(Base):
    __tablename__ = "tokens"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    printer_id: Mapped[str] = mapped_column(ForeignKey("printers.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # 'device' | 'console' | 'api'
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Invite(Base):
    __tablename__ = "invites"
    code_hash: Mapped[str] = mapped_column(String, primary_key=True)
    # Stable, non-secret handle the relay records locally to gate auto-allow-listing
    # (relay §5); separate from the secret code_hash PK.
    id: Mapped[str] = mapped_column(String, unique=True, index=True)
    # issuer null == admin bootstrap (creates a printer with no inviter friendship)
    issuer_printer_id: Mapped[str | None] = mapped_column(
        ForeignKey("printers.id"), nullable=True
    )
    redeemed_by: Mapped[str | None] = mapped_column(
        ForeignKey("printers.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Friendship(Base):
    """One row per ordered pair; a mutual friendship is two rows."""
    __tablename__ = "friendships"
    __table_args__ = (UniqueConstraint("owner_id", "friend_id", name="uq_friend_pair"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("printers.id"), index=True)
    friend_id: Mapped[str] = mapped_column(ForeignKey("printers.id"), index=True)
    # The invite this friendship was redeemed from, so the relay can match it
    # against the invite ids it issued locally (relay §5). Null for legacy rows.
    origin_invite_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LoginLink(Base):
    """One-time, short-lived console login link. Plaintext is hashed at rest like
    an invite code; consuming it mints a CONSOLE token (§9.1, §13)."""
    __tablename__ = "login_links"
    code_hash: Mapped[str] = mapped_column(String, primary_key=True)
    printer_id: Mapped[str] = mapped_column(ForeignKey("printers.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Capability(Base):
    """Cached full /schema keyed by renderer_version (the fingerprint, §6.2)."""
    __tablename__ = "capabilities"
    renderer_version: Mapped[str] = mapped_column(String, primary_key=True)
    blocks_schema: Mapped[dict] = mapped_column(JSON)
    block_types: Mapped[list] = mapped_column(JSON)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    sender_handle: Mapped[str] = mapped_column(String, index=True)
    recipient_id: Mapped[str] = mapped_column(ForeignKey("printers.id"), index=True)
    state: Mapped[str] = mapped_column(String, index=True)  # see jobs/store.STATES
    kind: Mapped[str] = mapped_column(String)  # 'document' | 'raw'
    payload: Mapped[dict] = mapped_column(JSON)  # {"document": {...}} or {"raw_png_b64": "..."}
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # immutable (FROM basis)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    leased_by: Mapped[str | None] = mapped_column(String, nullable=True)


class SendReceipt(Base):
    """Send-level idempotency: (sender, key) -> the job ids it created."""
    __tablename__ = "send_receipts"
    __table_args__ = (UniqueConstraint("sender_handle", "idempotency_key", name="uq_send_idem"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sender_handle: Mapped[str] = mapped_column(String, index=True)
    idempotency_key: Mapped[str] = mapped_column(String)
    payload_hash: Mapped[str] = mapped_column(String)
    job_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
