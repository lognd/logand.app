from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typani.result import Err, Ok, Result

from logand_backend.auth.passwords import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    verify_password,
)
from logand_backend.auth.sessions import SessionInfo, create_session
from logand_backend.db.models.users import User
from logand_backend.domain.auth.email_verification import mint_email_verification_token
from logand_backend.errors import AuthError
from logand_backend.logging import get_logger

_log = get_logger(__name__)


async def login(
    db: AsyncSession, email: str, password: str
) -> Result[tuple[str, SessionInfo], AuthError]:
    """Looks up the user by email, verifies the password, and on success
    creates a session. Deliberately returns the same AuthError.InvalidCredentials
    for both "no such user" and "wrong password" -- never let the error
    distinguish account existence (standard login-enumeration defense).

    Also rejects a disabled account (User.disabled_at set -- see
    api/admin_users.py's deactivate route) with that SAME
    InvalidCredentials error, for the same reason: "wrong password" and
    "this account exists but was deactivated" must be indistinguishable
    from the outside, or the error itself becomes a way to enumerate
    which accounts an admin has disabled.

    Looks up case-insensitively (`func.lower(User.email) ==
    email.strip().lower()`) -- register()/ensure_admin_seeded() both
    store emails lowercased and stripped, so a lookup that didn't
    normalize the same way here would let "User@X.com" register
    successfully and then fail to log back in with that exact same
    string.
    """
    normalized_email = email.strip().lower()
    # .limit(1) (not scalar_one_or_none()) -- users.email has a
    # case-SENSITIVE unique constraint, so legacy pre-normalization data
    # can still contain two rows differing only by case (e.g. "Bob@x.com"
    # and "bob@x.com"); scalar_one_or_none() would raise
    # MultipleResultsFound on that lookup and turn a login into an
    # uncaught 500 instead of a clean auth outcome. order_by(User.id)
    # makes which of the two rows wins deterministic rather than
    # depending on table scan order.
    user = (
        await db.execute(
            select(User)
            .where(func.lower(User.email) == normalized_email)
            .order_by(User.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if user is None:
        # Run a verify against a fixed dummy hash so this branch costs the
        # same argon2 latency as the "wrong password" branch below --
        # otherwise the immediate return here is a timing side-channel for
        # account enumeration (see FINDINGS.md L1). The result is always
        # discarded: there is no real password to accept.
        verify_password(password, DUMMY_PASSWORD_HASH)
        _log.warning("login failed: no such account", extra={"email": email})
        return Err(AuthError.InvalidCredentials)
    # docs/design/17: a contact row (password_hash IS NULL) has nothing to
    # authenticate as -- but still run verify_password against the SAME
    # fixed dummy hash used above, so this branch costs the same argon2
    # latency as a real wrong-password check and doesn't fork timing
    # between "no such account", "this is a contact row", and "wrong
    # password" (all three must be indistinguishable from outside).
    if user.password_hash is None:
        verify_password(password, DUMMY_PASSWORD_HASH)
        _log.warning(
            "login failed: account has no password set (contact row)",
            extra={"email": email, "user_id": str(user.id)},
        )
        return Err(AuthError.InvalidCredentials)
    if not verify_password(password, user.password_hash):
        _log.warning(
            "login failed: wrong password",
            extra={"email": email, "user_id": str(user.id)},
        )
        return Err(AuthError.InvalidCredentials)
    if user.disabled_at is not None:
        _log.warning(
            "login failed: account disabled",
            extra={"email": email, "user_id": str(user.id)},
        )
        return Err(AuthError.InvalidCredentials)
    if user.email_verified_at is None:
        # Distinct, disclosable error (docs/design/16) -- reaching this
        # branch already required knowing the correct password, so it is
        # safe to tell the truth here (unlike InvalidCredentials, this
        # does not participate in the login account-existence oracle).
        _log.warning(
            "login failed: email not verified",
            extra={"email": email, "user_id": str(user.id)},
        )
        return Err(AuthError.EmailNotVerified)
    _log.info("login succeeded", extra={"email": email, "user_id": str(user.id)})
    return await create_session(db, user.id, user.role)


async def register(
    db: AsyncSession, email: str, password: str
) -> Result[tuple[User, str], AuthError]:
    """Get-or-create semantics (docs/design/16), NOT plain self-registration
    any more: since an admin invoicing a bare email now leaves a real
    users row behind (a "contact" row, password_hash/email_verified_at
    both NULL), register() may be landing on a row that already exists
    for a completely legitimate reason -- there being an invoice already
    waiting for this address is the whole point of the feature.

    - No existing row: create a fresh "unverified" one.
    - Existing row is a contact (password_hash NULL) or unverified
      (email_verified_at NULL): allowed. Overwrites password_hash and
      re-mints a 'verify' token -- this is what stops an attacker from
      squatting/denial-of-servicing a real owner out of their own
      address (whoever proves inbox control wins, see the design doc's
      "Squatting" section), and what lets the real owner re-request a
      verification email if the first one was lost.
    - Existing row is "active" (email_verified_at set): refused --
      the email is already in use by someone who has proven ownership.

    Returns (user, raw_verify_token) rather than a session -- unlike the
    old self-registration flow, a freshly registered account is NOT
    logged in immediately any more (see api/auth.py's register route):
    it can't log in until it verifies, so there is no session to hand
    back.

    Email comparison/storage is lowercased so "User@x.com" and "user@x.com"
    can't both register -- the case-insensitive lookup here is a
    best-effort pre-check; the real guard against a duplicate insert
    racing this SELECT is the `users.email` unique constraint plus the
    IntegrityError catch below.
    """
    normalized_email = email.strip().lower()

    existing = (
        await db.execute(select(User).where(func.lower(User.email) == normalized_email))
    ).scalar_one_or_none()

    if existing is not None:
        if existing.email_verified_at is not None:
            return Err(AuthError.EmailAlreadyRegistered)
        # Contact or unverified row -- overwrite the password and re-mint.
        existing.password_hash = hash_password(password)
        await db.flush()
        raw_token = await mint_email_verification_token(db, existing.id, "verify")
        _log.info(
            "registration overwrote contact/unverified row",
            extra={"email": normalized_email, "user_id": str(existing.id)},
        )
        return Ok((existing, raw_token))

    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        role="customer",
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        return Err(AuthError.EmailAlreadyRegistered)

    raw_token = await mint_email_verification_token(db, user.id, "verify")
    _log.info(
        "registration created new unverified user",
        extra={"email": normalized_email, "user_id": str(user.id)},
    )
    return Ok((user, raw_token))


async def logout(db: AsyncSession, session_id: UUID) -> Result[None, AuthError]:
    from logand_backend.auth.sessions import revoke_session

    return await revoke_session(db, session_id)


async def ensure_admin_seeded(db: AsyncSession, email: str, password: str) -> User:
    """Idempotently ensures an admin account exists at `email` with
    `password` -- the one out-of-band path for creating an admin (see
    register()'s docstring: there is deliberately no request path that can
    set role="admin"). Safe to call on every app startup/every test-suite
    run: if the account already exists, this only re-hashes and rewrites
    the password (so a changed SEED_ADMIN_PASSWORD env var actually takes
    effect on the next restart) rather than erroring or duplicating it.

    Only ever wired up behind an explicit opt-in (SEED_ADMIN_EMAIL/
    SEED_ADMIN_PASSWORD env vars, see app/app.py's lifespan) -- never
    called unconditionally, since a real production deployment shouldn't
    have a well-known admin password sitting in an env var at all past
    its very first bootstrap.
    """
    normalized_email = email.strip().lower()
    existing = (
        await db.execute(select(User).where(func.lower(User.email) == normalized_email))
    ).scalar_one_or_none()

    if existing is not None:
        existing.password_hash = hash_password(password)
        existing.role = "admin"
        # docs/design/17: without this, the seeded admin is left
        # "unverified" (email_verified_at NULL) and cannot log in at all
        # -- there is no inbox to click a verify link from for an
        # out-of-band seeded account, so this IS the verification.
        existing.email_verified_at = datetime.now(timezone.utc)
        await db.flush()
        return existing

    user = User(
        email=normalized_email,
        password_hash=hash_password(password),
        role="admin",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()
    return user


async def get_or_create_contact_user(db: AsyncSession, email: str) -> User:
    """Get-or-create a "contact" row for `email` (docs/design/16) -- used
    by api/invoices.py's POST /api/invoices when an admin invoices a bare
    email address with no existing account. Returns the existing row
    unchanged if one already exists (contact, unverified, or active --
    whatever state it's in, an admin billing that address just attaches
    the invoice to it; this never demotes an active account back to
    contact). Only ever creates a brand-new row with password_hash AND
    email_verified_at both NULL (a fresh contact) when no row exists yet.
    """
    normalized_email = email.strip().lower()
    existing = (
        await db.execute(select(User).where(func.lower(User.email) == normalized_email))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    user = User(email=normalized_email, password_hash=None, role="customer")
    try:
        # SAVEPOINT (not the outer transaction) -- this may run nested
        # inside a larger create-invoice transaction; a plain db.rollback()
        # on IntegrityError would discard everything else that caller has
        # already flushed, not just this insert. `user` is added inside
        # the same nested block so a rollback also un-pends it from the
        # session's identity map, not just the SQL.
        async with db.begin_nested():
            db.add(user)
            await db.flush()
    except IntegrityError:
        # Lost a race with a concurrent insert for the same email -- fetch
        # the row the other request just created instead of erroring.
        existing = (
            await db.execute(
                select(User).where(func.lower(User.email) == normalized_email)
            )
        ).scalar_one()
        return existing
    _log.info("created contact user for invoicing", extra={"email": normalized_email})
    return user
