from hub.config import HubConfig


def test_defaults_and_env_override():
    cfg = HubConfig.from_env({})
    assert cfg.database_url.startswith("sqlite+aiosqlite")  # safe dev default
    assert cfg.long_poll_wait_s == 25.0
    assert cfg.lease_visibility_timeout_s == 60.0
    assert cfg.job_ttl_s == 24 * 3600
    assert cfg.sender_rate_per_min == 30

    cfg2 = HubConfig.from_env({
        "DATABASE_URL": "postgresql+asyncpg://u:p@h/db",
        "HUB_LONG_POLL_WAIT_S": "10",
        "HUB_JOB_TTL_S": "3600",
        "HUB_ADMIN_TOKEN": "secret",
    })
    assert cfg2.database_url == "postgresql+asyncpg://u:p@h/db"
    assert cfg2.long_poll_wait_s == 10.0
    assert cfg2.job_ttl_s == 3600
    assert cfg2.admin_token == "secret"
