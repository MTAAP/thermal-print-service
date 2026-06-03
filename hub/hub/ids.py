from __future__ import annotations

import secrets


def new_id(prefix: str) -> str:
    """Opaque, URL-safe id with a human-readable prefix (e.g. 'job_x9...')."""
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def new_token() -> str:
    """High-entropy bearer token (the plaintext is shown to the holder once)."""
    return secrets.token_urlsafe(32)


def new_invite_code() -> str:
    return secrets.token_urlsafe(9)
