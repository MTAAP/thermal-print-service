from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class HubConfig:
    database_url: str = "sqlite+aiosqlite:///./hub.db"
    admin_token: str | None = None
    long_poll_wait_s: float = 25.0
    lease_visibility_timeout_s: float = 60.0
    job_ttl_s: int = 24 * 3600
    sender_rate_per_min: int = 30
    # /send payload bounds. These gate what one friend can push into the shared
    # Postgres jobs.payload. They are GENEROUS on purpose -- the worst-case real
    # print is a 576px-wide job at the Pi's 2000mm max_length (16000px tall): a
    # near-incompressible 1-bit PNG of that size is ~2MB binary, ~2.7MB base64, so
    # an 8 MiB base64 ceiling clears every legitimate print ~3x over while still
    # stopping a multi-megabyte-blob flood. A document is structured blocks, never
    # bulk bytes, so 256 KiB is already far above any real composition.
    max_raw_png_b64_bytes: int = 8 * 1024 * 1024
    max_document_bytes: int = 256 * 1024
    max_recipients: int = 50
    # Global request-body ceiling enforced by ASGI middleware before routing. Set
    # just above max_raw_png_b64_bytes to leave room for the JSON envelope (the
    # `to` list, idempotency_key, field names) around a max-size raw payload, so a
    # legitimate max raw print never trips it while an oversized body 413s early.
    max_request_body_bytes: int = 8 * 1024 * 1024 + 64 * 1024
    # Web console session signing key. A real value MUST be set in prod via
    # HUB_SESSION_SECRET; the dev default is intentionally obvious so an
    # unconfigured deploy is visibly insecure rather than silently weak.
    session_secret: str = "dev-insecure-session-secret"
    # One-time console login link lifetime (short — it is a bearer-equivalent).
    login_link_ttl_s: int = 600
    # Public base URL of the hub (scheme + host). The single source of truth for
    # building console login URLs that get printed/shared. The default is a loud
    # placeholder so an unconfigured deploy yields obviously-broken links rather
    # than silently-wrong ones (mirrors the relay/MCP .invalid convention).
    public_url: str = "https://hub.example.invalid"
    # Send the session cookie's Secure attribute (HTTPS-only). Defaults True so a
    # prod deploy behind Railway TLS never emits the CONSOLE-token cookie without
    # Secure; set HUB_SESSION_HTTPS_ONLY=false only for local HTTP dev / tests.
    session_https_only: bool = True

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> HubConfig:
        e = env if env is not None else os.environ
        return cls(
            database_url=e.get("DATABASE_URL", cls.database_url),
            admin_token=e.get("HUB_ADMIN_TOKEN"),
            long_poll_wait_s=float(e.get("HUB_LONG_POLL_WAIT_S", cls.long_poll_wait_s)),
            lease_visibility_timeout_s=float(
                e.get("HUB_LEASE_TIMEOUT_S", cls.lease_visibility_timeout_s)
            ),
            job_ttl_s=int(e.get("HUB_JOB_TTL_S", cls.job_ttl_s)),
            sender_rate_per_min=int(e.get("HUB_SENDER_RATE_PER_MIN", cls.sender_rate_per_min)),
            max_raw_png_b64_bytes=int(
                e.get("HUB_MAX_RAW_PNG_B64_BYTES", cls.max_raw_png_b64_bytes)
            ),
            max_document_bytes=int(e.get("HUB_MAX_DOCUMENT_BYTES", cls.max_document_bytes)),
            max_recipients=int(e.get("HUB_MAX_RECIPIENTS", cls.max_recipients)),
            max_request_body_bytes=int(
                e.get("HUB_MAX_REQUEST_BODY_BYTES", cls.max_request_body_bytes)
            ),
            session_secret=e.get("HUB_SESSION_SECRET", cls.session_secret),
            login_link_ttl_s=int(e.get("HUB_LOGIN_LINK_TTL_S", cls.login_link_ttl_s)),
            public_url=e.get("HUB_PUBLIC_URL", cls.public_url),
            session_https_only=(
                e.get("HUB_SESSION_HTTPS_ONLY", "true").strip().lower()
                not in ("0", "false", "no", "off")
            ),
        )
