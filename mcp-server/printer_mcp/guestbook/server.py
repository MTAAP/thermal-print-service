"""A one-tool MCP server that lets a stranger send the owner a printed note.

Exposed over streamable HTTP so a chat host (LibreChat and friends) can reach
it by URL. It deliberately exposes nothing but the send: no status, no job
list, no reprint, no raw image path. A guest gets to put text on paper and
nothing else.

Every control lives here or further down the chain, never in the model: the
caps and the quota are enforced before the hub is called, and the recipient's
own relay holds an allow-list and a per-sender hourly ceiling underneath that."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from printer_mcp.documents import compose_art_document, compose_text_document
from printer_mcp.errors import PrintServiceError
from printer_mcp.guestbook.config import GuestbookConfig
from printer_mcp.guestbook.quota import QuotaExceeded, QuotaStore
from printer_mcp.guestbook.sanitize import (
    RejectedText,
    clean_art,
    clean_message,
    clean_name,
)
from printer_mcp.hub_client import HubClient

logger = logging.getLogger("printer.guestbook")

_ANONYMOUS_GUEST = "anonymous"


def _instructions(cfg: GuestbookConfig) -> str:
    return (
        f"This server sends a short handwritten-style note to {cfg.owner_name} "
        "on a physical receipt printer. Before calling the tool, ask the guest "
        "what they are called and what they want to say, and read the message "
        f"back to them for confirmation. Never invent a name. Once {cfg.owner_name} "
        "has the note there is no way to take it back, because it is paper."
    )


def _tool_description(cfg: GuestbookConfig) -> str:
    return (
        f"Send a short message to {cfg.owner_name} on a real thermal receipt "
        "printer, which prints it on paper. "
        "Only call this after the guest has told you, in this conversation, both "
        "their name and what they want to say. Never invent, guess or substitute "
        "a name. If the guest will not give a name, do not call this tool. "
        "Tell the guest the note is physical and cannot be unsent. "
        "Set preformatted=true for ASCII art, a diagram, a table or anything "
        "whose exact line breaks and spacing matter, and keep every line to "
        f"{cfg.max_art_cols} characters or fewer, because the paper is that wide "
        "and longer lines are cut off at the edge. Leave preformatted=false for "
        "ordinary prose, which is reflowed to fit the paper."
    )


def _guest_id(ctx: Context, header: str) -> str:
    """Identify the chat session, so one runaway conversation cannot flood.

    The header is set by the chat host from its own user record. A guest who can
    reach this server directly can send any value they like, which is exactly
    why the daily total is capped independently of it."""
    try:
        request = ctx.request_context.request
    except (AttributeError, LookupError, ValueError):
        return _ANONYMOUS_GUEST
    if request is None:
        return _ANONYMOUS_GUEST
    value = request.headers.get(header, "")
    return value.strip()[:64] or _ANONYMOUS_GUEST


def _idempotency_key(guest_id: str, name: str, message: str) -> str:
    # The hub dedups on (sender_handle, key) and the sender handle is the same
    # for every guest, so the guest id has to be inside the key or two people
    # saying "hello" would collapse into one note.
    digest = hashlib.sha256(
        "\x00".join((guest_id, name, message)).encode()
    ).hexdigest()
    return f"guestbook-{digest[:32]}"


def build_app(cfg: GuestbookConfig, *, hub_client: HubClient | None = None):
    """Build the Starlette app. Returns (app, aclose) so a caller owns shutdown."""
    mcp = FastMCP(name="guestbook", instructions=_instructions(cfg),
                  host=cfg.host, port=cfg.port, stateless_http=True, json_response=True)
    hub = hub_client or HubClient(cfg.hub_url, cfg.hub_api_token, timeout_s=cfg.timeout_s)
    quota = QuotaStore(cfg.state_dir / "quota.json",
                       per_guest_per_hour=cfg.per_guest_per_hour,
                       global_per_day=cfg.global_per_day)

    @mcp.tool(name=cfg.tool_name, description=_tool_description(cfg))
    async def send_message(
        from_name: str, message: str, ctx: Context, preformatted: bool = False
    ) -> str:
        """Send the guest's note to the owner's printer.

        Args:
            from_name: The name the guest gave for themselves, exactly as they
                said it. Ask them if they have not said. Never invent one.
            message: What the guest wants to say, in their own words.
            preformatted: True when the message is ASCII art, a diagram or a
                table, so its spacing and line breaks must survive to the paper.
                False for prose, which is reflowed to the paper width.
        """
        guest_id = _guest_id(ctx, cfg.guest_id_header)
        try:
            name = clean_name(from_name, max_chars=cfg.max_name_chars)
            if preformatted:
                body = clean_art(message, max_chars=cfg.max_art_chars,
                                 max_lines=cfg.max_art_lines,
                                 max_cols=cfg.max_art_cols)
            else:
                body = clean_message(message, max_chars=cfg.max_message_chars,
                                     max_lines=cfg.max_message_lines)
        except RejectedText as exc:
            logger.info("guestbook: rejected input from guest=%s: %s", guest_id, exc)
            return f"Not sent. {exc}"

        try:
            quota.check_and_record(guest_id)
        except QuotaExceeded as exc:
            logger.info("guestbook: quota block for guest=%s: %s", guest_id, exc)
            return f"Not sent. {exc}"

        title = f"Message for {cfg.owner_name}"
        if preformatted:
            document = compose_art_document(title, f"From: {name}", body)
        else:
            document = compose_text_document(title, f"From: {name}\n\n{body}")
        try:
            result = await hub.send(
                to=[cfg.recipient_handle],
                document=document,
                idempotency_key=_idempotency_key(guest_id, name, body),
            )
        except PrintServiceError as exc:
            logger.error("guestbook: hub send failed for guest=%s: %s", guest_id, exc)
            return (
                "The printer could not be reached just now, so nothing was sent. "
                "Tell the guest to try again in a moment."
            )

        queued = _queued(result)
        logger.info(
            "guestbook: guest=%s name=%s chars=%d preformatted=%s queued=%s counts=%s",
            guest_id, name, len(body), preformatted, queued, quota.snapshot(),
        )
        if not queued:
            return (
                "The printer refused the note, so nothing was printed. "
                "Tell the guest to try again later."
            )
        return (
            f"Sent. The note from {name} is queued for {cfg.owner_name}'s printer and "
            "prints as soon as it is switched on. It is on paper now, so it cannot be unsent."
        )

    return mcp.streamable_http_app(), hub.aclose


def _queued(result: Any) -> bool:
    results = result.get("results") if isinstance(result, dict) else None
    if not isinstance(results, list):
        return False
    return any(isinstance(r, dict) and r.get("status") == "queued" for r in results)
