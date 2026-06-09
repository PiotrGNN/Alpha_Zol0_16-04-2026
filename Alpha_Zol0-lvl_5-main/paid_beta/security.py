from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

PBKDF2_ROUNDS = 310_000


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("password must contain at least 10 characters")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), _b64decode(salt), int(rounds)
        )
        return hmac.compare_digest(actual, _b64decode(expected))
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    role: str
    expires_at: int
    token_version: int


def create_token(
    *,
    user_id: int,
    role: str,
    secret: str,
    ttl_seconds: int,
    token_version: int = 0,
) -> str:
    now = int(time.time())
    payload = {
        "sub": int(user_id),
        "role": role,
        "iat": now,
        "exp": now + ttl_seconds,
        "ver": int(token_version),
    }
    body = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64encode(signature)}"


def decode_token(token: str, *, secret: str) -> TokenClaims:
    try:
        body, encoded_signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(encoded_signature)):
            raise ValueError("invalid token signature")
        payload = json.loads(_b64decode(body))
        expires_at = int(payload["exp"])
        if expires_at <= int(time.time()):
            raise ValueError("token expired")
        return TokenClaims(
            user_id=int(payload["sub"]),
            role=str(payload.get("role", "user")),
            expires_at=expires_at,
            token_version=int(payload.get("ver", 0)),
        )
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid token") from exc


def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
