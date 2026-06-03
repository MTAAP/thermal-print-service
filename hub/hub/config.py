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
        )
