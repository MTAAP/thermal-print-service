"""Thin HTTP client to the Pi /print/raw endpoint."""
from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import Any

import httpx


class PrintClientError(RuntimeError):
    pass


def derive_idempotency_key(png_bytes: bytes) -> str:
    """Stable hash-derived idempotency key for a PNG payload.

    Used when the caller doesn't supply ``--idempotency-key`` explicitly.
    Re-running the same print becomes naturally idempotent: identical
    bytes hash the same, the server's idempotency cache returns the
    original 202 with ``duplicate: true`` instead of printing a second
    copy. Different content (a new design iteration) hashes differently,
    so iteration isn't accidentally deduped.
    """
    return hashlib.sha256(png_bytes).hexdigest()[:16]


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


def post_print_raw_with_retry(
    client: httpx.Client,
    png_bytes: bytes,
    *,
    idempotency_key: str | None,
    dry_run: bool,
    sender: str = "tprint-design",
    attempts: int = 3,
    backoff_base_s: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """``post_print_raw`` with backoff retry on transport-layer errors.

    Only retries ``httpx.HTTPError`` (transport-level failures: connect
    refused, DNS, timeout, mid-stream RST) — i.e. the "Pi unreachable
    / tailnet flapping" pattern observed in production. ``PrintClientError``
    (a structured 4xx/5xx from the service) bubbles immediately because
    those are decisive rejections, not transient.

    ``idempotency_key`` should be set: the server-side cache makes
    duplicate POSTs across retries idempotent. Without a key, a slow
    network where the first request actually succeeded but the response
    timed out could lead to a duplicate print on retry. The CLI defaults
    the key to ``derive_idempotency_key(png_bytes)`` for exactly this
    reason.
    """
    last_exc: httpx.HTTPError | None = None
    for i in range(attempts):
        try:
            return post_print_raw(
                client, png_bytes,
                idempotency_key=idempotency_key,
                dry_run=dry_run,
                sender=sender,
            )
        except httpx.HTTPError as exc:
            last_exc = exc
            if i + 1 < attempts:
                sleep(backoff_base_s * (4 ** i))
    assert last_exc is not None
    raise last_exc


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
