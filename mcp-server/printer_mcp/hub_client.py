from __future__ import annotations

from typing import Any

import httpx

from printer_mcp.config import McpConfig
from printer_mcp.errors import PrintServiceError


class HubClient:
    """Async HTTP client for the Printer Pals hub (the public relay).

    Distinct from PrintServiceClient: it talks to a *different* service
    (the hub, base_url=HUB_URL) with a *different* auth scheme (a per-person
    Bearer API token, spec §9.1) and carries the idempotency key in the
    POST /send JSON body rather than an X-Idempotency-Key header.

    One httpx.AsyncClient is reused for the MCP server's lifetime so
    connection pooling kicks in across tool invocations.
    """

    def __init__(self, cfg: McpConfig, *, http: httpx.AsyncClient | None = None) -> None:
        self._cfg = cfg
        self._http = http or httpx.AsyncClient(
            base_url=cfg.hub_url,
            timeout=cfg.timeout_s,
            headers={"Authorization": f"Bearer {cfg.hub_api_token}"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def send(
        self,
        *,
        to: list[str],
        document: dict[str, Any] | None,
        idempotency_key: str | None,
        raw_png_b64: str | None = None,
    ) -> dict[str, Any]:
        """POST /send. Returns the per-recipient results body.

        The hub returns 202 when >=1 recipient queued and 400 when every
        recipient failed (spec §6.1) -- BOTH carry the full {results:[...]}
        body, including incompatible.detail for self-correction. So a body
        with `results` is a normal outcome regardless of HTTP status; only
        auth (401/403), 5xx, or a transport failure are real errors that
        raise. raw_png_b64 is accepted for completeness but the MCP
        send_to_friend tool is document-only (raw is the web composer's job).
        """
        body: dict[str, Any] = {"to": to}
        if document is not None:
            body["document"] = document
        if raw_png_b64 is not None:
            body["raw_png_b64"] = raw_png_b64
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return await self._request_results("POST", "/send", json=body)

    async def list_friends(self) -> list[dict[str, Any]]:
        """GET /friends -> [{handle, display_name, renderer_version, online}]."""
        return await self._request_json("GET", "/friends")

    async def get_friend_schema(self, handle: str) -> dict[str, Any]:
        """GET /friends/{handle}/schema -> {renderer_version, blocks_schema, block_types}."""
        return await self._request_json("GET", f"/friends/{handle}/schema")

    async def _request_results(self, method: str, path: str, **kwargs: Any) -> Any:
        """Like _request_json, but a 4xx whose body carries `results` is a
        normal /send outcome (partial/total per-recipient failure), not an
        error. Only auth/5xx/transport raise."""
        r = await self._send(method, path, **kwargs)
        body = _parse_body(r)
        if isinstance(body, dict) and "results" in body:
            return body
        if r.is_success:
            return body
        raise PrintServiceError(
            status=r.status_code,
            message=_summarize(r.status_code, body),
            body=body,
        )

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        r = await self._send(method, path, **kwargs)
        body = _parse_body(r)
        if r.is_success:
            return body
        raise PrintServiceError(
            status=r.status_code,
            message=_summarize(r.status_code, body),
            body=body,
        )

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # Transport failure: DNS (the .invalid placeholder), TLS, network.
            # Surface as the agent-readable status-0 error, same as the Pi client.
            raise PrintServiceError(
                status=0,
                message=(
                    f"could not reach hub at {self._cfg.hub_url}: "
                    f"{exc.__class__.__name__}: {exc}"
                ),
            ) from exc


def _parse_body(r: httpx.Response) -> Any:
    if r.status_code == 204:
        return {}
    try:
        return r.json()
    except ValueError:
        return r.text or None


def _summarize(status: int, body: Any | None) -> str:
    if isinstance(body, dict):
        if "detail" in body:
            return f"{status} {body['detail']}"
        if "reason" in body:
            return f"{status} {body['reason']}"
    return f"{status} error"
