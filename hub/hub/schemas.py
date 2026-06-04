from __future__ import annotations

import base64
import binascii
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class CreateInviteResp(BaseModel):
    code: str
    invite_id: str
    expires_at: str


class LoginLinkResp(BaseModel):
    # A ready-to-print console login URL plus how long it stays valid. The Pi
    # prints `url` (as a QR + text) and uses `expires_in_s` for the human note;
    # a relative TTL is clock-sync-independent, which matters on a Pi whose clock
    # may not yet be synchronized.
    url: str
    expires_in_s: int


class RegisterReq(BaseModel):
    code: str
    handle: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_-]+$")
    display_name: str = Field(min_length=1, max_length=80)


class RegisterResp(BaseModel):
    printer_id: str
    handle: str
    device_token: str   # plaintext, shown once
    api_token: str      # plaintext, shown once
    inviter_handle: str | None


class FriendOut(BaseModel):
    handle: str
    display_name: str
    renderer_version: str | None
    online: bool
    via_invite_id: str | None = None
    last_seen_at: str | None = None


class SendReq(BaseModel):
    to: list[str] = Field(min_length=1)
    document: dict[str, Any] | None = None
    raw_png_b64: str | None = None
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def _exactly_one_payload(self) -> SendReq:
        # A job carries EITHER a document OR a raw PNG, never both and never
        # neither. Test with TRUTHINESS, not `is None`: send_document branches on
        # truthiness too (`"raw" if raw_png_b64 else "document"`), so the two
        # layers MUST agree on the empty cases. An identity check would let
        # raw_png_b64="" (or document={}) slip through here, then send_document
        # would treat it as the OTHER kind and queue {"document": None} -- an empty
        # job that crashes the recipient's relay. Rejecting at the request boundary
        # turns it into a clean 422, not a silently-broken queued job.
        if bool(self.document) == bool(self.raw_png_b64):
            raise ValueError("provide exactly one of `document` or `raw_png_b64`")
        if self.raw_png_b64:
            # Validate the base64 here so a malformed blob is a 422 at send time,
            # not a decode crash on the recipient's relay much later.
            try:
                base64.b64decode(self.raw_png_b64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError(f"raw_png_b64 is not valid base64: {exc}") from exc
        return self


class SendResult(BaseModel):
    to: str
    status: Literal[
        "queued", "not_friend", "recipient_unknown", "incompatible", "sender_throttled"
    ]
    job_id: str | None = None
    detail: dict[str, Any] | None = None


class SendResp(BaseModel):
    results: list[SendResult]
