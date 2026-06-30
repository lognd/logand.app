from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Params per docs/design/02-auth-and-security.md -- revisit only if VPS RAM
# (see docs/design/11-deployment.md sizing) proves this too heavy in practice.
_HASHER = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)


def hash_password(raw: str) -> str:
    return _HASHER.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _HASHER.verify(hashed, raw)
    except VerifyMismatchError:
        return False
