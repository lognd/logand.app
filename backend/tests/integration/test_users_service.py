from __future__ import annotations

from uuid import uuid4

from logand_backend.auth.passwords import verify_password
from logand_backend.db.models.audit import AdminAuditLog
from logand_backend.db.models.users import User
from logand_backend.domain.users.service import (
    admin_reset_password,
    deactivate_customer,
    get_customer,
    reactivate_customer,
)
from logand_backend.errors import UserError


async def test_deactivate_customer_sets_disabled_at_and_writes_audit_log(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")

    result = await deactivate_customer(db_session, customer.id, admin.id)

    assert result.is_ok
    user = await db_session.get(User, customer.id)
    assert user.disabled_at is not None

    log = await db_session.get(AdminAuditLog, result.danger_ok)
    assert log.action == "user.deactivate"
    assert log.admin_id == admin.id
    assert log.target_id == str(customer.id)
    assert log.before_state["disabled_at"] is None
    assert log.after_state["disabled_at"] is not None
    # The rollback record must never contain a password hash.
    assert "password_hash" not in log.before_state
    assert "password_hash" not in log.after_state


async def test_reactivate_customer_clears_disabled_at(db_session, make_user) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")
    await deactivate_customer(db_session, customer.id, admin.id)

    result = await reactivate_customer(db_session, customer.id, admin.id)

    assert result.is_ok
    user = await db_session.get(User, customer.id)
    assert user.disabled_at is None


async def test_deactivate_customer_not_found(db_session, make_user) -> None:
    admin = await make_user(role="admin")
    result = await deactivate_customer(db_session, uuid4(), admin.id)
    assert result.is_err
    assert result.danger_err == UserError.NotFound


async def test_deactivate_rejects_admin_account(db_session, make_user) -> None:
    admin = await make_user(role="admin")
    other_admin = await make_user(role="admin")
    result = await deactivate_customer(db_session, other_admin.id, admin.id)
    assert result.is_err
    assert result.danger_err == UserError.CannotModifyAdmin


async def test_admin_reset_password_changes_hash_and_never_logs_it(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer", password="original-password")

    result = await admin_reset_password(
        db_session, customer.id, "a-brand-new-password", admin.id
    )

    assert result.is_ok
    user = await db_session.get(User, customer.id)
    assert verify_password("a-brand-new-password", user.password_hash)
    assert not verify_password("original-password", user.password_hash)

    log = await db_session.get(AdminAuditLog, result.danger_ok)
    assert log.action == "user.reset_password"
    # No before/after snapshot at all for a password reset -- never
    # persist a hash (old or new) in the audit trail.
    assert log.before_state is None
    assert log.after_state is None


async def test_admin_reset_password_rejects_short_password(
    db_session, make_user
) -> None:
    admin = await make_user(role="admin")
    customer = await make_user(role="customer")

    result = await admin_reset_password(db_session, customer.id, "short", admin.id)

    assert result.is_err
    assert result.danger_err == UserError.PasswordTooShort


async def test_admin_reset_password_refuses_contact_row(db_session, make_user) -> None:
    """FINDINGS L1: setting a password on a contact row (password_hash NULL,
    never verified) would silently produce an unverified row that can never
    log in. It must be refused with a distinct, actionable error instead of
    reporting success.
    """
    from logand_backend.domain.auth.service import get_or_create_contact_user

    admin = await make_user(role="admin")
    contact = (
        await get_or_create_contact_user(db_session, "contact@example.com")
    ).danger_ok

    result = await admin_reset_password(
        db_session, contact.id, "a-brand-new-password", admin.id
    )

    assert result.is_err
    assert result.danger_err == UserError.CannotResetContactAccount
    # Still a contact -- no half-created unusable account was left behind.
    refreshed = await db_session.get(User, contact.id)
    assert refreshed.password_hash is None
    assert refreshed.email_verified_at is None


async def test_get_customer_rejects_admin_account(db_session, make_user) -> None:
    admin = await make_user(role="admin")
    result = await get_customer(db_session, admin.id)
    assert result.is_err
    assert result.danger_err == UserError.CannotModifyAdmin
