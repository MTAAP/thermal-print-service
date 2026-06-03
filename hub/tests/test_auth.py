import pytest

from hub.auth import TokenKind, authenticate, hash_token, mint_token
from hub.ids import new_id
from hub.models import Printer, Token
from tests.conftest import now


async def _printer(s, handle="alice"):
    p = Printer(id=new_id("prn"), handle=handle, display_name=handle,
                renderer_version=None, last_seen_at=None, created_at=now())
    s.add(p)
    await s.commit()
    return p


async def test_hash_is_not_plaintext_and_verifies():
    plaintext, h = mint_token()
    assert plaintext not in h
    assert hash_token(plaintext) == h


async def test_authenticate_matches_kind_and_scope(sm):
    async with sm() as s:
        p = await _printer(s)
        plaintext, h = mint_token()
        s.add(Token(id=new_id("tok"), printer_id=p.id, kind=TokenKind.DEVICE.value,
                    token_hash=h, revoked_at=None, created_at=now()))
        await s.commit()

        got = await authenticate(s, plaintext, required=TokenKind.DEVICE)
        assert got.id == p.id

        with pytest.raises(PermissionError):
            await authenticate(s, plaintext, required=TokenKind.API)  # wrong kind

        with pytest.raises(PermissionError):
            await authenticate(s, "wrong-token", required=TokenKind.DEVICE)


async def test_revoked_token_rejected(sm):
    async with sm() as s:
        p = await _printer(s)
        plaintext, h = mint_token()
        s.add(Token(id=new_id("tok"), printer_id=p.id, kind=TokenKind.API.value,
                    token_hash=h, revoked_at=now(), created_at=now()))
        await s.commit()
        with pytest.raises(PermissionError):
            await authenticate(s, plaintext, required=TokenKind.API)
