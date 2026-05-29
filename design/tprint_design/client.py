"""Thin HTTP client to the Pi /print/raw endpoint."""
from __future__ import annotations

from typing import Any

import httpx


class PrintClientError(RuntimeError):
    pass


def post_print_raw(
    client: httpx.Client,
    png_bytes: bytes,
    *,
    idempotency_key: str | None,
    dry_run: bool,
    sender: str = "tprint-design",
) -> dict[str, Any]:
    headers: dict[str, str] = {
        "Content-Type": "image/png",
        "X-Sender": sender,
    }
    if idempotency_key:
        headers["X-Idempotency-Key"] = idempotency_key
    params = {"dry_run": "true"} if dry_run else None
    r = client.post("/print/raw", content=png_bytes, headers=headers, params=params)
    if r.is_success:
        ct = r.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if ct == "image/png":
            return {
                "dry_run": True,
                "estimated_paper_mm": int(r.headers.get("X-Estimated-Paper-Mm", "0")),
                "renderer_version": r.headers.get("X-Renderer-Version"),
            }
        return r.json()
    body = _safe_json(r)
    summary = _summarize(r.status_code, body)
    raise PrintClientError(f"{r.status_code}: {summary}")


def _safe_json(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return r.text


def _summarize(status: int, body: Any) -> str:
    if isinstance(body, dict):
        if "reason" in body:
            return body["reason"]
        if "errors" in body and body["errors"]:
            return body["errors"][0].get("message", str(body["errors"][0]))
    return str(body)
