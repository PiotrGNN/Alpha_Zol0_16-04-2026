import time

import pytest

from paid_beta.security import create_token, decode_token, hash_password, verify_password


def test_password_hash_roundtrip():
    encoded = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", encoded)
    assert not verify_password("wrong-password", encoded)


def test_signed_token_roundtrip_and_tamper_rejection():
    secret = "s" * 32
    token = create_token(user_id=7, role="admin", secret=secret, ttl_seconds=60)
    claims = decode_token(token, secret=secret)
    assert claims.user_id == 7
    assert claims.role == "admin"
    with pytest.raises(ValueError):
        decode_token(token + "tampered", secret=secret)


def test_expired_token_rejected(monkeypatch):
    secret = "s" * 32
    monkeypatch.setattr(time, "time", lambda: 100)
    token = create_token(user_id=1, role="user", secret=secret, ttl_seconds=1)
    monkeypatch.setattr(time, "time", lambda: 102)
    with pytest.raises(ValueError):
        decode_token(token, secret=secret)
