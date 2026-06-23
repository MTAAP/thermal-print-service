from __future__ import annotations

import enum
from dataclasses import dataclass

import httpx


class SubmitOutcome(enum.Enum):
    ACCEPTED = "accepted"            # 202: durable, has a local job id
    INCOMPATIBLE = "incompatible"   # 400: terminal, do NOT retry
    TOO_LARGE = "too_large"         # 413: terminal failed
    QUEUE_FULL = "queue_full"       # 503: retryable -> let the lease redeliver
    IDEMPOTENCY_MISMATCH = "idempotency_mismatch"  # 409: determinism canary


@dataclass
class SubmitResult:
    outcome: SubmitOutcome
    local_job_id: str | None = None
    detail: dict | None = None  # carry the Pi's 400 error body for rejected_incompatible


class LocalClient:
    """Thin async wrapper over the LOCAL service (127.0.0.1). The relay is a
    client of the existing /print, /print/raw, /jobs/{id} endpoints."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._c = client

    def _headers(self, sender: str, idempotency_key: str) -> dict[str, str]:
        # sender namespaced 'friend:<handle>' so friend idempotency scopes never
        # collide with local senders' (spec 14 idempotency-namespacing item).
        return {"X-Sender": sender, "X-Idempotency-Key": idempotency_key}

    def _classify(self, r: httpx.Response) -> SubmitResult:
        if r.status_code == 202:
            return SubmitResult(SubmitOutcome.ACCEPTED, local_job_id=r.json()["id"])
        if r.status_code == 400:
            # Only parse the 400 body when it is JSON; the rejected_incompatible
            # path forwards this detail back to the hub for the sender.
            is_json = r.headers.get("content-type", "").startswith("application/json")
            body = r.json() if is_json else None
            return SubmitResult(SubmitOutcome.INCOMPATIBLE, detail=body)
        if r.status_code == 413:
            return SubmitResult(SubmitOutcome.TOO_LARGE)
        if r.status_code == 503:
            return SubmitResult(SubmitOutcome.QUEUE_FULL)
        if r.status_code == 409:
            return SubmitResult(SubmitOutcome.IDEMPOTENCY_MISMATCH)
        # Any other status is treated as a clean failure (no job created).
        return SubmitResult(SubmitOutcome.TOO_LARGE)

    async def print_document(self, document: dict, *, sender: str,
                             idempotency_key: str) -> SubmitResult:
        r = await self._c.post("/print", json=document,
                               headers=self._headers(sender, idempotency_key))
        return self._classify(r)

    async def print_raw(self, png_bytes: bytes, *, sender: str,
                        idempotency_key: str) -> SubmitResult:
        headers = self._headers(sender, idempotency_key)
        headers["Content-Type"] = "image/png"
        r = await self._c.post("/print/raw", content=png_bytes, headers=headers)
        return self._classify(r)

    async def get_job_status(self, local_job_id: str) -> str | None:
        r = await self._c.get(f"/jobs/{local_job_id}")
        if r.status_code == 404:
            return None  # local job gone (log pruned) -> caller maps to failed/expired
        r.raise_for_status()
        return r.json()["status"]

    async def get_schema(self) -> dict:
        r = await self._c.get("/schema")
        r.raise_for_status()
        return r.json()
