from __future__ import annotations

from logand_backend.auth.passwords import hash_password, verify_password


def test_hash_and_verify_round_trip() -> None:
    raw = "correct horse battery staple"
    hashed = hash_password(raw)
    assert hashed != raw
    assert verify_password(raw, hashed) is True


def test_verify_rejects_wrong_password() -> None:
    hashed = hash_password("the-real-password")
    assert verify_password("not-the-real-password", hashed) is False


def test_verify_rejects_empty_password_against_real_hash() -> None:
    hashed = hash_password("the-real-password")
    assert verify_password("", hashed) is False


def test_hash_and_verify_round_trip_with_unicode() -> None:
    # \uXXXX escapes (not literal bytes) per repo convention: ASCII-only
    # source files. This is still a real unicode password at runtime.
    raw = "correct horse battery staple \u00e9\u00e8\u4e2d\u6587"
    hashed = hash_password(raw)
    assert verify_password(raw, hashed) is True


def test_hash_and_verify_round_trip_with_very_long_password() -> None:
    raw = "a" * 1024
    hashed = hash_password(raw)
    assert verify_password(raw, hashed) is True
    assert verify_password("a" * 1023, hashed) is False
