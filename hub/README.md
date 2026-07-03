# thermal-print-hub

Public relay hub for the thermal-print friend network. Dumb relay: stores and
routes JSON print documents between friends' Pis; never renders.

Run: `printer-hub run` (reads `DATABASE_URL`, `HUB_ADMIN_TOKEN`, see `hub/config.py`).

Schema changes run through Alembic migrations at startup. Existing pre-Alembic
databases are stamped at the baseline revision before applying later migrations.

## Self-hosting

The hub is replaceable infrastructure. It holds friend metadata, queued relay
jobs, tokens, and console sessions, but it never renders and never owns local
print authority; each Pi relay still enforces its own allow-list before
submitting to the local printer service. Devices can opt into offline ntfy
alerts with `PUT /printers/me/alerts`; the hub stores only the topic and sends
alerts when the relay has been silent longer than the configured threshold.

Required production environment:

- `DATABASE_URL`: SQLAlchemy async URL. Railway Postgres should use the provided
  asyncpg URL; local smoke tests can use `sqlite+aiosqlite:///./hub.db`.
- `HUB_ADMIN_TOKEN`: bearer token for `POST /admin/invites`, used to bootstrap
  the first invite.
- `HUB_SESSION_SECRET`: signing secret for web console sessions.
- `HUB_PUBLIC_URL`: public `https://...` base URL used in printed login links
  and shareable `/join` URLs.

Common tuning knobs:

- `HUB_SESSION_HTTPS_ONLY`: defaults to `true`; set `false` only for local HTTP
  development.
- `HUB_LONG_POLL_WAIT_S`, `HUB_LEASE_TIMEOUT_S`, `HUB_JOB_TTL_S`: receive-path
  timing.
- `HUB_OFFLINE_ALERT_AFTER_S`: relay silence threshold before an opted-in device
  receives an offline ntfy alert.
- `HUB_SENDER_RATE_PER_MIN`, `HUB_MAX_RAW_PNG_B64_BYTES`,
  `HUB_MAX_DOCUMENT_BYTES`, `HUB_MAX_RECIPIENTS`,
  `HUB_MAX_REQUEST_BODY_BYTES`: sender and request caps.

Railway deploy:

```bash
cd hub
railway up
```

Container-host deploy:

```bash
cd hub
docker build -t thermal-print-hub .
docker run --env-file ./hub.env -p 8000:8000 thermal-print-hub
```

The Docker image installs the package through `pip install -c constraints.txt .`
to match the Railway runtime path. Any container host is acceptable if it
provides the environment above, durable Postgres, HTTPS at `HUB_PUBLIC_URL`, and
health checks against `/healthz`.

Point a Pi relay at a replacement hub by setting `HUB_URL` before
`printer-svc hub join ...`; `RelayConfig.hub_url` stores that URL with the
device credentials. `printer-svc relay run` then reads the stored `hub_url` for
long-polling, acknowledgements, status reports, invites, friends, and login-link
requests.
