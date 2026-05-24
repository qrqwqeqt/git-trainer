"""Підписані токени сесії (HMAC-SHA256) для WebSocket-автентифікації.

Особистість студента (user_id, username, room) видається сервером і
підписується секретом (`settings.secret_key`), тож клієнт не може її
підмінити на кожному кадрі. Токен прив'язаний до конкретної кімнати та має
строк дії (`access_token_ttl_minutes`). Без зовнішніх залежностей — лише stdlib.

Формат: base64url(json(payload)) + "." + base64url(hmac_sha256(secret, body)).
Це частина підрозділу ПЗ «захист даних» (авторизація). Модель довіри —
«довірена аудиторія»: токен забезпечує цілісність та строк дії сесії; для
закритих груп зверху додається пароль кімнати (майбутнє посилення).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from app.config import get_settings


class AuthError(Exception):
    """Токен невалідний: підпис, формат або строк дії."""


@dataclass(frozen=True)
class TokenData:
    user_id: str
    username: str
    room: str
    exp: int


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(body: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return _b64e(digest)


def create_token(
    user_id: str,
    username: str,
    room: str,
    *,
    ttl_minutes: int | None = None,
    secret: str | None = None,
) -> str:
    """Видати підписаний токен сесії для (user_id, username, room)."""
    settings = get_settings()
    secret = secret or settings.secret_key
    ttl = ttl_minutes if ttl_minutes is not None else settings.access_token_ttl_minutes
    exp = int(time.time()) + ttl * 60
    payload = {"uid": user_id, "un": username, "room": room, "exp": exp}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body, secret)}"


def verify_token(
    token: str,
    *,
    secret: str | None = None,
    expected_room: str | None = None,
) -> TokenData:
    """Перевірити підпис, строк дії та (опційно) кімнату. Кидає AuthError."""
    settings = get_settings()
    secret = secret or settings.secret_key
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise AuthError("malformed token") from exc
    if not hmac.compare_digest(sig, _sign(body, secret)):
        raise AuthError("bad signature")
    try:
        payload = json.loads(_b64d(body))
    except Exception as exc:  # noqa: BLE001 — будь-який збій декодування = невалід
        raise AuthError("malformed payload") from exc
    if int(payload.get("exp", 0)) < int(time.time()):
        raise AuthError("token expired")
    room = payload.get("room")
    if expected_room is not None and room != expected_room:
        raise AuthError("room mismatch")
    try:
        return TokenData(
            user_id=payload["uid"],
            username=payload["un"],
            room=room,
            exp=int(payload["exp"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("incomplete payload") from exc
