import pytest
from fastapi import HTTPException

from hub.presence import Presence
from hub.routes import AppDeps, bearer


def test_bearer_extracts_token():
    assert bearer("Bearer abc123") == "abc123"


def test_bearer_is_scheme_case_insensitive():
    # The code lowercases the scheme before comparing, so "bearer" is accepted.
    assert bearer("bearer abc123") == "abc123"


def test_bearer_missing_header_raises_401():
    with pytest.raises(HTTPException) as exc:
        bearer(None)
    assert exc.value.status_code == 401


def test_bearer_without_scheme_raises_401():
    with pytest.raises(HTTPException) as exc:
        bearer("abc123")
    assert exc.value.status_code == 401


def test_appdeps_holds_dependencies():
    # Smoke: AppDeps is a plain dataclass carrying the four request-scoped deps.
    deps = AppDeps(config=object(), sessionmaker=object(), wake=object(), online=Presence())
    assert deps.online is not None
