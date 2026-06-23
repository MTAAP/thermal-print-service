from __future__ import annotations

# Lifecycle (spec §8.1). Non-terminal then terminal.
IN_FLIGHT = {"queued", "leased", "delivered"}
TERMINAL = {
    "relay_expired", "rejected_not_allowlisted", "rejected_rate_limited",
    "rejected_incompatible", "printed", "printer_expired",
    "printer_retry_timeout", "printer_unknown_partial", "printer_lost", "failed",
}
STATES = IN_FLIGHT | TERMINAL

# Pi local terminal event -> hub status (spec §8.1 mapping table).
LOCAL_TO_HUB = {
    "printed": "printed",
    "expired": "printer_expired",
    "retry_timeout": "printer_retry_timeout",
    "unknown_partial": "printer_unknown_partial",
}

# Statuses the relay may post via the status callback (post-delivery).
# printer_lost is relay-only -- it has no local terminal event (the local job
# RECORD vanished before its outcome could be confirmed), so it is reportable but
# deliberately absent from LOCAL_TO_HUB.
RELAY_REPORTABLE = set(LOCAL_TO_HUB.values()) | {
    "rejected_not_allowlisted", "rejected_rate_limited", "rejected_incompatible",
    "printer_lost", "failed",
}


def map_local_status(local_event: str) -> str:
    return LOCAL_TO_HUB.get(local_event, "failed")
