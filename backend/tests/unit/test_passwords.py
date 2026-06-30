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
