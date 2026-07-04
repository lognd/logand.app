from __future__ import annotations

import hashlib


def hash_token(raw_token: str) -> str:
    """sha256 hex digest of a raw, cryptographically random token
    (secrets.token_urlsafe) -- the ONLY form of a bearer token this
    codebase ever persists (sessions.py's session cookie, and
    password_reset.py's reset token). The raw value only ever exists in
    the cookie/URL and in-memory during the request that issues or
    consumes it, so a DB leak alone can never be replayed as a live
    token. Shared here (not duplicated per call site) so both token
    types are provably hashed the same way.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
