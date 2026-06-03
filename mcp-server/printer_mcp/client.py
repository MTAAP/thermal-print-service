from __future__ import annotations

import base64
from typing import Any

import httpx

from printer_mcp.config import McpConfig
from printer_mcp.errors import PrintServiceError


class PrintServiceClient:
    """Async HTTP client for the Pi-side print service.

    One ``httpx.AsyncClient`` is reused for the lifetime of the MCP server
    so connection pooling kicks in — the same client makes one request
    per tool invocation.

    All requests carry ``X-Sender`` so the Pi's ``/jobs`` log groups MCP
    prints under a single sender (default ``mcp``; override via
    ``PRINT_SENDER`` if multiple agentic surfaces share the same Pi).
    """

    def __init__(self, cfg: McpConfig, *, http: httpx.AsyncClient | None = None) -> None:
        self._cfg = cfg
        self._http = http or httpx.AsyncClient(
            base_url=cfg.print_service_url,
            timeout=cfg.timeout_s,
            headers={"X-Sender": cfg.sender},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def base_url(self) -> str:
        return self._cfg.print_service_url

    async def get_schema(self) -> dict[str, Any]:
        return await self._get_json("/schema")

    async def get_status(self) -> dict[str, Any]:
        return await self._get_json("/healthz")

    async def list_jobs(self, *, limit: int = 20) -> Any:
        return await self._get_json("/jobs", params={"limit": limit})

    async def post_test(self) -> dict[str, Any]:
        return await self._post_json("/test")

    async def post_print(
        self, document: dict[str, Any], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        headers = {}
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        return await self._post_json("/print", json=document, headers=headers)

    async def post_print_raw(
        self, png_bytes: bytes, *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        headers = {"Content-Type": "image/png"}
        if idempotency_key:
            headers["X-Idempotency-Key"] = idempotency_key
        return await self._post_json("/print/raw", content=png_bytes, headers=headers)

    async def post_reprint(self, job_id: str, *, force_json: bool = False) -> dict[str, Any]:
        params = {"force": "json"} if force_json else None
        return await self._post_json(f"/jobs/{job_id}/reprint", params=params)

    def decode_png_base64(self, data: str) -> bytes:
        # Reject oversized payloads BEFORE decoding so a huge agent-supplied
        # string never lands as full RSS. Base64 encodes 3 bytes per 4
        # chars (+ padding), so the decoded size is at most ``len(data) *
        # 3 // 4``. A char-length cap is the tightest pre-decode bound.
        cap = self._cfg.max_print_image_bytes
        max_chars = (cap * 4) // 3 + 4
        if len(data) > max_chars:
            raise PrintServiceError(
                status=413,
                message=(
                    f"png_base64 exceeds {cap}-byte cap "
                    f"(set PRINT_MAX_IMAGE_BYTES to raise it)"
                ),
            )
        try:
            return base64.b64decode(data, validate=True)
        except (base64.binascii.Error, ValueError) as exc:  # type: ignore[attr-defined]
            raise PrintServiceError(
                status=400,
                message=f"png_base64 is not valid base64: {exc}",
            ) from exc

    async def _get_json(self, path: str, **kwargs: Any) -> Any:
        return await self._request("GET", path, **kwargs)

    async def _post_json(self, path: str, **kwargs: Any) -> Any:
        return await self._request("POST", path, **kwargs)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            r = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # Transport failure: network down, DNS resolve failed, TLS
            # handshake error, etc. Surface as the executor-style error so
            # the agent gets actionable text rather than a stack trace.
            raise PrintServiceError(
                status=0,
                message=(
                    f"could not reach print service at {self._cfg.print_service_url}: "
                    f"{exc.__class__.__name__}: {exc}"
                ),
            ) from exc

        # 204 No Content is theoretical here but cheap to handle.
        if r.status_code == 204:
            return {}

        body: Any | None
        try:
            body = r.json()
        except ValueError:
            body = r.text or None

        if r.is_success:
            return body

        # Pi 4xx (validation, queue full, conflict): preserve the structured
        # body verbatim — that's the spec-mandated migration_hint surface.
        raise PrintServiceError(
            status=r.status_code,
            message=_summarize_error(r.status_code, body),
            body=body,
        )


def _summarize_error(status: int, body: Any | None) -> str:
    """Plain-English headline derived from the response body when possible."""
    if isinstance(body, dict):
        if "reason" in body:
            return f"{status} {body['reason']}"
        if "errors" in body and body["errors"]:
            first = body["errors"][0]
            if isinstance(first, dict) and "message" in first:
                return f"{status} {first['message']}"
        if "detail" in body:
            return f"{status} {body['detail']}"
    return f"{status} error"
