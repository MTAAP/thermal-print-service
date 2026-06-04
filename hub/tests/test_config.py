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


def test_web_session_config_defaults_and_override():
    from hub.config import HubConfig

    cfg = HubConfig.from_env({})
    # No default secret: a missing secret must be a loud misconfiguration in prod,
    # but tests/dev get a deterministic dev value so the cookie layer works.
    assert cfg.session_secret == "dev-insecure-session-secret"
    assert cfg.login_link_ttl_s == 600  # 10 minutes
    # Secure cookie defaults ON so prod behind TLS is safe by default.
    assert cfg.session_https_only is True

    cfg2 = HubConfig.from_env({
        "HUB_SESSION_SECRET": "s3cr3t",
        "HUB_LOGIN_LINK_TTL_S": "120",
        "HUB_SESSION_HTTPS_ONLY": "false",
    })
    assert cfg2.session_secret == "s3cr3t"
    assert cfg2.login_link_ttl_s == 120
    assert cfg2.session_https_only is False
