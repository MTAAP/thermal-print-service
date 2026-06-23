from __future__ import annotations

import secrets


def new_id(prefix: str) -> str:
    """Opaque, URL-safe id with a human-readable prefix (e.g. 'job_x9...')."""
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def new_token() -> str:
    """High-entropy bearer token (the plaintext is shown to the holder once)."""
    return secrets.token_urlsafe(32)


def new_invite_code() -> str:
    # token_urlsafe draws from [A-Za-z0-9_-]. A leading '-' or '_' is hostile to
    # CLI positionals (`printer-svc hub join <code>` -> argparse reads it as a
    # flag, not the code) and awkward in URLs, so reject those first characters.
    # Re-rolling keeps full entropy for the codes we keep (no biased first byte).
    while True:
        code = secrets.token_urlsafe(9)
        if code[0] not in "-_":
            return code
