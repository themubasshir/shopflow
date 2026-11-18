from __future__ import annotations

import pytest

from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_password_round_trip():
    h = hash_password("CorrectHorse#1")
    assert verify_password("CorrectHorse#1", h) is True
    assert verify_password("wrong", h) is False


def test_verify_handles_missing_hash():
    assert verify_password("anything", None) is False


def test_short_password_rejected():
    with pytest.raises(ValueError):
        hash_password("short")


def test_token_round_trip():
    token = create_access_token(
        "user-1", shop_id="shop-1", role="manager", permissions=["sales:read"]
    )
    payload = decode_access_token(token)
    assert payload["sub"] == "user-1"
    assert payload["role"] == "manager"
    assert "sales:read" in payload["permissions"]


def test_tampered_token_rejected():
    token = create_access_token("u", shop_id="s", role="r", permissions=[])
    with pytest.raises(TokenError):
        decode_access_token(token[:-4] + "AAAA")


def test_needs_rehash_detects_bad_hash():
    assert needs_rehash("not-a-hash") is True
