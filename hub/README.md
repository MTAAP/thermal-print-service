# thermal-print-hub

Public relay hub for the thermal-print friend network. Dumb relay: stores and
routes JSON print documents between friends' Pis; never renders.

Run: `printer-hub run` (reads `DATABASE_URL`, `HUB_ADMIN_TOKEN`, see `hub/config.py`).

v1 creates tables with `create_all` at startup. The first post-launch schema
change should introduce Alembic.
