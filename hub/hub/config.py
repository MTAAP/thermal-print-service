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
    # Web console session signing key. A real value MUST be set in prod via
    # HUB_SESSION_SECRET; the dev default is intentionally obvious so an
    # unconfigured deploy is visibly insecure rather than silently weak.
    session_secret: str = "dev-insecure-session-secret"
    # One-time console login link lifetime (short — it is a bearer-equivalent).
    login_link_ttl_s: int = 600
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
            session_secret=e.get("HUB_SESSION_SECRET", cls.session_secret),
            login_link_ttl_s=int(e.get("HUB_LOGIN_LINK_TTL_S", cls.login_link_ttl_s)),
            session_https_only=(
                e.get("HUB_SESSION_HTTPS_ONLY", "true").strip().lower()
                not in ("0", "false", "no", "off")
            ),
        )
