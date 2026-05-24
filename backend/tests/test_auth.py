"""Unit-тести підписаних токенів сесії (app.auth)."""
from __future__ import annotations

import time

import pytest

from app.auth import AuthError, create_token, verify_token


def test_roundtrip_valid_token():
    tok = create_token("u1", "dzhe", "room-x")
    data = verify_token(tok, expected_room="room-x")
    assert data.user_id == "u1"
    assert data.username == "dzhe"
    assert data.room == "room-x"
    assert data.exp > int(time.time())


def test_tampered_signature_rejected():
    tok = create_token("u1", "dzhe", "room-x")
    body, _sig = tok.split(".", 1)
    forged = f"{body}.AAAA"
    with pytest.raises(AuthError):
        verify_token(forged)


def test_tampered_payload_rejected():
    """Зміна payload без перепідпису ламає перевірку."""
    other = create_token("attacker", "evil", "room-x")
    good = create_token("u1", "dzhe", "room-x")
    forged = other.split(".", 1)[0] + "." + good.split(".", 1)[1]
    with pytest.raises(AuthError):
        verify_token(forged)


def test_room_mismatch_rejected():
    tok = create_token("u1", "dzhe", "room-a")
    with pytest.raises(AuthError):
        verify_token(tok, expected_room="room-b")


def test_expired_token_rejected():
    tok = create_token("u1", "dzhe", "room-x", ttl_minutes=-1)
    with pytest.raises(AuthError):
        verify_token(tok)


def test_malformed_token_rejected():
    with pytest.raises(AuthError):
        verify_token("not-a-token")


def test_wrong_secret_rejected():
    tok = create_token("u1", "dzhe", "room-x", secret="secret-a")
    with pytest.raises(AuthError):
        verify_token(tok, secret="secret-b")
