from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Params per docs/design/02-auth-and-security.md -- revisit only if VPS RAM
# (see docs/design/11-deployment.md sizing) proves this too heavy in practice.
_HASHER = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)

# Fixed dummy hash for the "user does not exist" login branch (see
# domain/auth/service.py::login and FINDINGS.md L1) -- verifying against
# this constant hash makes that branch pay the same argon2 latency as the
# "user exists, wrong password" branch, closing a timing side-channel that
# would otherwise let an attacker enumerate valid emails by response time.
# Generated once from an arbitrary raw string; the raw value itself is
# irrelevant since no real password is ever checked against it correctly.
DUMMY_PASSWORD_HASH = _HASHER.hash("dummy-password-for-timing-parity")


def hash_password(raw: str) -> str:
    return _HASHER.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _HASHER.verify(hashed, raw)
    except VerifyMismatchError:
        return False
