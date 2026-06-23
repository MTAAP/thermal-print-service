from __future__ import annotations

import json
import logging
from typing import Any

import mcp.types as mcp_types
from mcp.server import Server

from printer_mcp.client import PrintServiceClient
from printer_mcp.config import McpConfig
from printer_mcp.errors import PrintServiceError, format_for_agent
from printer_mcp.hub_client import HubClient
from printer_mcp.schema_cache import SchemaCache

log = logging.getLogger(__name__)


def build_print_document_input_schema(document_schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap the live ``Document`` JSON Schema so it becomes the ``document``
    property of the MCP tool's input.

    Pydantic-generated schemas keep their ``$defs`` at the schema root,
    and ``$ref`` values like ``#/$defs/...`` resolve from the nearest
    JSON Schema resource. We hoist ``$defs`` to the wrapper root so the
    embedded refs keep resolving when the schema is one level deeper.
    """
    doc = dict(document_schema)
    defs = doc.pop("$defs", None)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "document": doc,
            "idempotency_key": {
                "type": "string",
                "description": (
                    "Optional idempotency key. Set this with X-Sender to "
                    "dedupe retries within 24h. Same key + same payload "
                    "returns the original 202 with duplicate=true; same key "
                    "+ different payload is a 409 conflict."
                ),
            },
        },
        "required": ["document"],
        "additionalProperties": False,
    }
    if defs:
        schema["$defs"] = defs
    return schema


def build_print_image_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "png_base64": {
                "type": "string",
                "description": (
                    "PNG image, base64-encoded. Must decode as a valid PNG "
                    "and be exactly 576 pixels wide (the print head's full "
                    "dot count). Use this escape hatch for pixel-controlled "
                    "art, photos, or anything the block schema can't express."
                ),
            },
            "idempotency_key": {
                "type": "string",
                "description": "Optional idempotency key (24h TTL).",
            },
        },
        "required": ["png_base64"],
        "additionalProperties": False,
    }


def build_send_to_friend_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": (
                    "Friend handles to send to (e.g. ['alice', 'bob']). "
                    "Multi-select is just listing more than one. Use "
                    "list_friends to see who you can send to."
                ),
            },
            "document": {
                # Generic object on purpose: MCP tool input schemas are frozen
                # at list_tools() time, so this cannot reshape per recipient.
                # The hub validates the document against the RECIPIENT's actual
                # schema at send time and returns incompatible.detail. Call
                # get_friend_schema(handle) first to compose a valid document.
                "type": "object",
                "additionalProperties": True,
                "description": (
                    "The print document (same block schema the recipient's "
                    "printer speaks). Call get_friend_schema(handle) first to "
                    "learn the recipient's available blocks/fields. If a "
                    "recipient comes back 'incompatible', read result.detail "
                    "(offending field + valid_values) and retry."
                ),
            },
            "idempotency_key": {
                "type": "string",
                "description": (
                    "Optional. Same key + same payload returns the original "
                    "per-recipient job ids instead of re-queuing."
                ),
            },
        },
        "required": ["to", "document"],
        "additionalProperties": False,
    }


def build_message_friend_input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": (
                    "Friend handles to send to (e.g. ['alice', 'bob']). Use "
                    "list_friends to see who you can send to."
                ),
            },
            "text": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "The message body. Printed as a paragraph on each "
                    "recipient's printer, under an optional title."
                ),
            },
            "title": {
                "type": "string",
                "description": "Optional bold title printed above the message.",
            },
            "idempotency_key": {
                "type": "string",
                "description": (
                    "Optional. Same key + same payload returns the original "
                    "per-recipient job ids instead of re-queuing."
                ),
            },
        },
        "required": ["to", "text"],
        "additionalProperties": False,
    }


def _compose_text_document(title: str, text: str) -> dict[str, Any]:
    # Common-core only (header + paragraph): these block types are stable across
    # EVERY renderer version (hub spec §6.2), so a plain-text message needs no
    # get_friend_schema round-trip -- any friend's printer accepts it. Mirrors
    # the hub web console's compose document exactly (header iff a title, then a
    # paragraph; field name is `text`, not `content`).
    blocks: list[dict[str, Any]] = []
    if title.strip():
        blocks.append({"type": "header", "text": title.strip()})
    blocks.append({"type": "paragraph", "text": text})
    return {"blocks": blocks}


def _ok(payload: Any) -> list[mcp_types.TextContent]:
    if isinstance(payload, dict) and "ok" in payload:
        body = payload
    else:
        body = {"ok": True, "result": payload}
    return [mcp_types.TextContent(type="text", text=json.dumps(body, indent=2))]


def _err(exc: PrintServiceError) -> list[mcp_types.TextContent]:
    return [mcp_types.TextContent(type="text", text=json.dumps(format_for_agent(exc), indent=2))]


def build_server(
    cfg: McpConfig,
    client: PrintServiceClient,
    cache: SchemaCache,
    hub_client: HubClient,
) -> Server:
    """Construct and wire the low-level MCP server.

    The low-level ``Server`` is used (rather than ``FastMCP``) because
    ``print_document``'s input schema is generated from a runtime fetch.
    The Printer Pals friend tools (send_to_friend / list_friends /
    get_friend_schema) live on this same server and talk to ``hub_client``;
    because MCP input schemas are frozen at list_tools() time, send_to_friend
    takes a generic ``document`` and the hub validates it per-recipient.
    """
    server: Server = Server("thermal-printer")

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        # If we're in fallback mode (Pi was unreachable at boot), try one
        # more refresh now — Claude only calls list_tools once at boot of
        # an MCP session, so this is our chance to recover.
        if cache.snapshot.is_fallback:
            try:
                await cache.refresh()
            except PrintServiceError as exc:
                log.warning("schema refresh on list_tools failed: %s", exc)

        snap = cache.snapshot
        renderer = snap.renderer_version
        block_hint = (
            f" Available block types: {', '.join(snap.block_types)}."
            if snap.block_types
            else " (block-type catalog not yet loaded; restart MCP after "
            "the print service is reachable to populate it.)"
        )

        return [
            mcp_types.Tool(
                name="print_document",
                description=(
                    "Print a structured document on the thermal receipt printer. "
                    "Compose the document from blocks (header, paragraph, checklist, "
                    "qr, image, etc.) and the renderer turns it into typeset paper. "
                    f"Renderer version: {renderer}.{block_hint} "
                    "Returns 202 with id + estimated_paper_mm on success; "
                    "structured 400 with valid_values + migration_hint on schema errors."
                ),
                inputSchema=build_print_document_input_schema(snap.document_schema),
            ),
            mcp_types.Tool(
                name="print_image",
                description=(
                    "Print a raw PNG image. Escape hatch for pixel-controlled "
                    "output (photos with custom dithering, generative art, ASCII "
                    "pieces the block schema can't express). The PNG must be "
                    "exactly 576px wide. Use print_document with an `image` "
                    "block for typical embedded images — this tool bypasses "
                    "the renderer entirely."
                ),
                inputSchema=build_print_image_input_schema(),
            ),
            mcp_types.Tool(
                name="get_status",
                description=(
                    "Get the printer's current health: connected, paper present, "
                    "cover closed, queue depth, last print time, uptime, clock sync. "
                    "Use this before printing if the agent wants to confirm the "
                    "printer is ready, or to diagnose why a job hasn't printed."
                ),
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            mcp_types.Tool(
                name="list_recent_jobs",
                description=(
                    "List the most recent print jobs with their status, sender, "
                    "document type, and reprint info. Useful for 'what did the "
                    "printer just do?' or finding a job id to reprint."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "default": 20,
                        }
                    },
                    "additionalProperties": False,
                },
            ),
            mcp_types.Tool(
                name="reprint_job",
                description=(
                    "Reprint a previous job by id. Default reprint mode replays "
                    "the cached PNG byte-for-byte (use this when the cat knocked "
                    "the paper). Set force_json=true to re-render from JSON at the "
                    "current renderer version, useful when typography has improved "
                    "since the original print. Returns 410 if both PNG and JSON "
                    "have aged out of cache."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Job id from list_recent_jobs."},
                        "force_json": {"type": "boolean", "default": False},
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
            ),
            mcp_types.Tool(
                name="print_test",
                description=(
                    "Print the bundled test page (a hello-world sample exercising "
                    "every block type). Use after a hardware move, when debugging, "
                    "or to verify the printer is alive without composing a document."
                ),
                inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
            ),
            mcp_types.Tool(
                name="get_design_guidelines",
                description=(
                    "Return the thermal-design rulebook (live print width, "
                    "DPMM, available fonts, lint rules summary, and the full "
                    "tprint-design CLI workflow). Call this once at the start "
                    "of an HTML-design session to load the rules into context. "
                    "For the CLI itself, see the design package's tprint-design "
                    "binary."
                ),
                inputSchema={"type": "object", "properties": {},
                             "additionalProperties": False},
            ),
            mcp_types.Tool(
                name="send_to_friend",
                description=(
                    "Send a print to one or more friends on the Printer Pals "
                    "network (their printer, their tailnet). The recipient's "
                    "printer renders it with a visible FROM tag. The `document` "
                    "is the same block schema a printer speaks, but different "
                    "friends may run different renderer versions -- call "
                    "get_friend_schema(handle) first to compose a valid "
                    "document. Returns a per-recipient results array; a "
                    "recipient may come back 'queued' (with a job_id), "
                    "'not_friend', 'recipient_unknown', 'incompatible' (with "
                    "detail.valid_values so you can fix and retry), or "
                    "'sender_throttled'."
                ),
                inputSchema=build_send_to_friend_input_schema(),
            ),
            mcp_types.Tool(
                name="message_friend",
                description=(
                    "Send a quick text message to one or more friends on the "
                    "Printer Pals network -- no document composition needed. "
                    "Give `text` (and an optional `title`) and it prints as a "
                    "titled note on each recipient's printer with a FROM tag. "
                    "Uses only common-core blocks (header + paragraph) that "
                    "EVERY renderer version accepts, so unlike send_to_friend "
                    "you do NOT need get_friend_schema first. Reach for "
                    "send_to_friend when you need richer blocks (lists, qr, "
                    "images). Returns the same per-recipient results array as "
                    "send_to_friend (queued / not_friend / recipient_unknown / "
                    "sender_throttled)."
                ),
                inputSchema=build_message_friend_input_schema(),
            ),
            mcp_types.Tool(
                name="list_friends",
                description=(
                    "List the friends you can send to: handle, display name, "
                    "renderer_version (a schema fingerprint -- friends sharing "
                    "a version share a schema), and whether they're currently "
                    "online. Call this before send_to_friend to pick "
                    "recipients."
                ),
                inputSchema={"type": "object", "properties": {},
                             "additionalProperties": False},
            ),
            mcp_types.Tool(
                name="get_friend_schema",
                description=(
                    "Fetch a friend's block catalog/schema (renderer_version, "
                    "blocks_schema, block_types) so you can compose a document "
                    "that recipient's printer will accept BEFORE sending. Use "
                    "this to avoid 'incompatible' results from send_to_friend."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "handle": {"type": "string",
                                   "description": "Friend handle from list_friends."},
                    },
                    "required": ["handle"],
                    "additionalProperties": False,
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[mcp_types.TextContent]:
        args = arguments or {}
        try:
            if name == "print_document":
                return await _call_print_document(client, args)
            if name == "print_image":
                return await _call_print_image(client, args)
            if name == "get_status":
                return _ok(await client.get_status())
            if name == "list_recent_jobs":
                limit = int(args.get("limit", 20))
                return _ok(await client.list_jobs(limit=limit))
            if name == "reprint_job":
                job_id = str(args["id"])
                force_json = bool(args.get("force_json", False))
                return _ok(await client.post_reprint(job_id, force_json=force_json))
            if name == "print_test":
                return _ok(await client.post_test())
            if name == "get_design_guidelines":
                from printer_mcp.design_guidelines import payload
                return _ok(payload())
            if name == "send_to_friend":
                return await _call_send_to_friend(cfg, hub_client, args)
            if name == "message_friend":
                return await _call_message_friend(cfg, hub_client, args)
            if name == "list_friends":
                _require_hub_token(cfg)
                return _ok(await hub_client.list_friends())
            if name == "get_friend_schema":
                _require_hub_token(cfg)
                handle = str(args["handle"])
                return _ok(await hub_client.get_friend_schema(handle))
        except PrintServiceError as exc:
            return _err(exc)
        except KeyError as exc:
            return _err(PrintServiceError(
                status=400,
                message=f"missing required argument: {exc.args[0]}",
            ))

        return _err(PrintServiceError(status=404, message=f"unknown tool: {name}"))

    return server


def _require_hub_token(cfg: McpConfig) -> None:
    """Loud-fail at call time (not boot) when HUB_API_TOKEN is unset, so the
    friend tools still LIST (matching print_document's always-list behavior)
    but a call returns a crisp error instead of an unauthenticated request."""
    if not cfg.hub_api_token:
        raise PrintServiceError(
            status=400,
            message="HUB_API_TOKEN not set -- export it to send to friends",
        )


async def _call_send_to_friend(
    cfg: McpConfig, hub_client: HubClient, args: dict[str, Any]
) -> list[mcp_types.TextContent]:
    _require_hub_token(cfg)
    to = args.get("to")
    if not isinstance(to, list) or not to or not all(isinstance(h, str) for h in to):
        raise PrintServiceError(
            status=400, message="argument 'to' must be a non-empty list of handles"
        )
    document = args.get("document")
    if not isinstance(document, dict):
        raise PrintServiceError(status=400, message="argument 'document' must be an object")
    idem = args.get("idempotency_key")
    idem_str = str(idem) if idem else None
    # The hub returns {results:[...]} for both 202 (partial) and 400 (all-failed);
    # surface it verbatim so the agent sees per-recipient status + incompatible.detail.
    return _ok(await hub_client.send(to=to, document=document, idempotency_key=idem_str))


async def _call_message_friend(
    cfg: McpConfig, hub_client: HubClient, args: dict[str, Any]
) -> list[mcp_types.TextContent]:
    _require_hub_token(cfg)
    to = args.get("to")
    if not isinstance(to, list) or not to or not all(isinstance(h, str) for h in to):
        raise PrintServiceError(
            status=400, message="argument 'to' must be a non-empty list of handles"
        )
    text = args.get("text")
    if not isinstance(text, str) or not text:
        raise PrintServiceError(
            status=400, message="argument 'text' must be a non-empty string"
        )
    title = args.get("title")
    title_str = str(title) if title else ""
    idem = args.get("idempotency_key")
    idem_str = str(idem) if idem else None
    # Compose the common-core document here, then reuse the same hub /send path
    # as send_to_friend -- message_friend is purely an ergonomic wrapper.
    document = _compose_text_document(title_str, text)
    return _ok(await hub_client.send(to=to, document=document, idempotency_key=idem_str))


async def _call_print_document(
    client: PrintServiceClient, args: dict[str, Any]
) -> list[mcp_types.TextContent]:
    document = args.get("document")
    if not isinstance(document, dict):
        raise PrintServiceError(status=400, message="argument 'document' must be an object")
    idem = args.get("idempotency_key")
    idem_str = str(idem) if idem else None
    return _ok(await client.post_print(document, idempotency_key=idem_str))


async def _call_print_image(
    client: PrintServiceClient, args: dict[str, Any]
) -> list[mcp_types.TextContent]:
    png_b64 = args.get("png_base64")
    if not isinstance(png_b64, str) or not png_b64:
        raise PrintServiceError(
            status=400, message="argument 'png_base64' must be a non-empty string"
        )
    png_bytes = client.decode_png_base64(png_b64)
    idem = args.get("idempotency_key")
    idem_str = str(idem) if idem else None
    return _ok(await client.post_print_raw(png_bytes, idempotency_key=idem_str))
