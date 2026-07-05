from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_payment_methods_zelle_handle_is_none_when_unconfigured(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/invoices/payment-methods")

    assert resp.status_code == 200
    assert resp.json()["zelle_handle"] is None


async def test_payment_methods_returns_real_zelle_handle_once_configured(
    db_client: AsyncClient, make_user, login_as, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A phone number or email, whatever the admin's real Zelle account is
    # registered under -- see AppConfig.zelle_handle's own doc comment on
    # why this is free-form/unvalidated.
    monkeypatch.setenv("ZELLE_HANDLE", "+1 (423) 555-0100")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/invoices/payment-methods")

    assert resp.status_code == 200
    assert resp.json()["zelle_handle"] == "+1 (423) 555-0100"


async def test_payment_methods_paypal_receive_email_is_none_when_unconfigured(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/invoices/payment-methods")

    assert resp.status_code == 200
    assert resp.json()["paypal_receive_email"] is None


async def test_payment_methods_returns_paypal_receive_email_once_configured(
    db_client: AsyncClient, make_user, login_as, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The confirmed email on the PayPal account a customer sends a manual
    # payment to -- see AppConfig.paypal_receive_email's own doc comment.
    monkeypatch.setenv("PAYPAL_RECEIVE_EMAIL", "paypal@logand.app")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/invoices/payment-methods")

    assert resp.status_code == 200
    assert resp.json()["paypal_receive_email"] == "paypal@logand.app"
