from __future__ import annotations

import json
import logging
from typing import Any

import mcp.types as mcp_types
from mcp.server import Server

from printer_mcp.client import PrintServiceClient
from printer_mcp.config import McpConfig
from printer_mcp.errors import PrintServiceError, format_for_agent
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


def _ok(payload: Any) -> list[mcp_types.TextContent]:
    if isinstance(payload, dict) and "ok" in payload:
        body = payload
    else:
        body = {"ok": True, "result": payload}
    return [mcp_types.TextContent(type="text", text=json.dumps(body, indent=2))]


def _err(exc: PrintServiceError) -> list[mcp_types.TextContent]:
    return [mcp_types.TextContent(type="text", text=json.dumps(format_for_agent(exc), indent=2))]


def build_server(cfg: McpConfig, client: PrintServiceClient, cache: SchemaCache) -> Server:
    """Construct and wire the low-level MCP server.

    The low-level ``Server`` is used (rather than ``FastMCP``) because
    ``print_document``'s input schema is generated from a runtime fetch,
    not a static type annotation — the spec's whole point is that
    Claude's tool catalog is the live block-type catalog.
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
        except PrintServiceError as exc:
            return _err(exc)
        except KeyError as exc:
            return _err(PrintServiceError(
                status=400,
                message=f"missing required argument: {exc.args[0]}",
            ))

        return _err(PrintServiceError(status=404, message=f"unknown tool: {name}"))

    return server


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
