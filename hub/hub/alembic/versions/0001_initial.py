"""baseline schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-02 00:00:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "capabilities",
        sa.Column("renderer_version", sa.String(), nullable=False),
        sa.Column("blocks_schema", sa.JSON(), nullable=False),
        sa.Column("block_types", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("renderer_version"),
    )
    op.create_table(
        "printers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("handle", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("renderer_version", sa.String(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_printers_handle"), "printers", ["handle"], unique=True)
    op.create_table(
        "friendships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("friend_id", sa.String(), nullable=False),
        sa.Column("origin_invite_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["friend_id"], ["printers.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["printers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "friend_id", name="uq_friend_pair"),
    )
    op.create_index(op.f("ix_friendships_friend_id"), "friendships", ["friend_id"])
    op.create_index(op.f("ix_friendships_owner_id"), "friendships", ["owner_id"])
    op.create_table(
        "invites",
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("issuer_printer_id", sa.String(), nullable=True),
        sa.Column("redeemed_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["issuer_printer_id"], ["printers.id"]),
        sa.ForeignKeyConstraint(["redeemed_by"], ["printers.id"]),
        sa.PrimaryKeyConstraint("code_hash"),
    )
    op.create_index(op.f("ix_invites_id"), "invites", ["id"], unique=True)
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("sender_handle", sa.String(), nullable=False),
        sa.Column("recipient_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("leased_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["recipient_id"], ["printers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_recipient_id"), "jobs", ["recipient_id"])
    op.create_index(op.f("ix_jobs_sender_handle"), "jobs", ["sender_handle"])
    op.create_index(op.f("ix_jobs_state"), "jobs", ["state"])
    op.create_table(
        "login_links",
        sa.Column("code_hash", sa.String(), nullable=False),
        sa.Column("printer_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["printer_id"], ["printers.id"]),
        sa.PrimaryKeyConstraint("code_hash"),
    )
    op.create_index(op.f("ix_login_links_printer_id"), "login_links", ["printer_id"])
    op.create_table(
        "send_receipts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sender_handle", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("job_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sender_handle", "idempotency_key", name="uq_send_idem"),
    )
    op.create_index(op.f("ix_send_receipts_sender_handle"), "send_receipts", ["sender_handle"])
    op.create_table(
        "tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("printer_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["printer_id"], ["printers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tokens_printer_id"), "tokens", ["printer_id"])
    op.create_index(op.f("ix_tokens_token_hash"), "tokens", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_tokens_token_hash"), table_name="tokens")
    op.drop_index(op.f("ix_tokens_printer_id"), table_name="tokens")
    op.drop_table("tokens")
    op.drop_index(op.f("ix_send_receipts_sender_handle"), table_name="send_receipts")
    op.drop_table("send_receipts")
    op.drop_index(op.f("ix_login_links_printer_id"), table_name="login_links")
    op.drop_table("login_links")
    op.drop_index(op.f("ix_jobs_state"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_sender_handle"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_recipient_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_invites_id"), table_name="invites")
    op.drop_table("invites")
    op.drop_index(op.f("ix_friendships_owner_id"), table_name="friendships")
    op.drop_index(op.f("ix_friendships_friend_id"), table_name="friendships")
    op.drop_table("friendships")
    op.drop_index(op.f("ix_printers_handle"), table_name="printers")
    op.drop_table("printers")
    op.drop_table("capabilities")
