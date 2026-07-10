from __future__ import annotations

import stripe
from httpx import AsyncClient

# Regression tests for L1 in FINDINGS-2026-07-09.md: a transient Stripe
# outage on a customer-facing pay route used to escape as an unhandled 500,
# while every other Stripe call site in this codebase (refunds.py,
# webhooks.py) already degraded gracefully. api/invoices_public.py's
# _stripe_call now converts stripe.error.StripeError into the same 503 the
# "card payments are not configured" path already returns.


async def _send_invoice_to(
    db_client: AsyncClient, admin_email: str, customer_id: str, login_as
):
    await login_as(db_client, admin_email, "pw")
    headers = {"X-CSRF-Token": db_client.cookies["csrf_token"]}
    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": customer_id},
        json=[{"description": "widget", "quantity": "1", "unit_price": "25.00"}],
        headers=headers,
    )
    assert create_resp.status_code == 200
    invoice_id = create_resp.json()["id"]
    send_resp = await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=headers
    )
    assert send_resp.status_code == 200
    await db_client.post("/api/auth/logout", headers=headers)
    return invoice_id


async def test_pay_invoice_returns_503_when_stripe_is_unreachable(
    db_client: AsyncClient, make_user, login_as, monkeypatch
) -> None:
    """A Stripe blip during PaymentIntent.create must surface as a clean 503,
    not a bare 500. No money moves either way -- this is purely about the
    customer seeing "try again shortly" instead of a crash.
    """
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    invoice_id = await _send_invoice_to(
        db_client, admin.email, str(customer.id), login_as
    )

    def _boom(*args, **kwargs):
        raise stripe.error.APIConnectionError("stripe is down")

    monkeypatch.setattr(stripe.PaymentIntent, "create", _boom)

    await login_as(db_client, customer.email, "pw")
    headers = {"X-CSRF-Token": db_client.cookies["csrf_token"]}
    resp = await db_client.post(f"/api/invoices/{invoice_id}/pay", headers=headers)

    assert resp.status_code == 503
    assert "temporarily unavailable" in resp.json()["detail"]


async def test_pay_invoice_still_409s_when_intent_already_succeeded(
    db_client: AsyncClient, make_user, login_as, monkeypatch
) -> None:
    """The 409 "already paid" guard is raised BETWEEN the wrapped Stripe
    calls. _stripe_call must not swallow it into a 503 -- a customer whose
    payment already succeeded must be told to refresh, never invited to
    retry a second charge.
    """
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    invoice_id = await _send_invoice_to(
        db_client, admin.email, str(customer.id), login_as
    )

    created = {}

    def _create(*args, **kwargs):
        intent = stripe.PaymentIntent.construct_from(
            {
                "id": "pi_test_already_succeeded",
                "status": "requires_payment_method",
                "client_secret": "pi_test_secret",
                "amount": kwargs["amount"],
            },
            "sk_test_fake",
        )
        created["id"] = intent.id
        return intent

    monkeypatch.setattr(stripe.PaymentIntent, "create", _create)

    await login_as(db_client, customer.email, "pw")
    headers = {"X-CSRF-Token": db_client.cookies["csrf_token"]}
    first = await db_client.post(f"/api/invoices/{invoice_id}/pay", headers=headers)
    assert first.status_code == 200

    # Second attempt: Stripe now reports the stored intent as succeeded.
    def _retrieve(intent_id, *args, **kwargs):
        return stripe.PaymentIntent.construct_from(
            {
                "id": intent_id,
                "status": "succeeded",
                "client_secret": "pi_test_secret",
                "amount": 25000,
            },
            "sk_test_fake",
        )

    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", _retrieve)

    second = await db_client.post(f"/api/invoices/{invoice_id}/pay", headers=headers)
    assert second.status_code == 409
