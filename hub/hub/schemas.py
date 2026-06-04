from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CreateInviteResp(BaseModel):
    code: str
    invite_id: str
    expires_at: str


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


class SendResult(BaseModel):
    to: str
    status: Literal[
        "queued", "not_friend", "recipient_unknown", "incompatible", "sender_throttled"
    ]
    job_id: str | None = None
    detail: dict[str, Any] | None = None


class SendResp(BaseModel):
    results: list[SendResult]
