from __future__ import annotations

import uuid

from scripts.prodtest.admin_data_helper import (
    hard_delete_row,
    opt_out_of_emails,
    row_exists,
)
from scripts.prodtest.admin_session import get_shared_admin_client
from scripts.prodtest.env import ProdEnv
from scripts.prodtest.http_client import ProdHttpClient
from scripts.prodtest.revert import Cleanup, Probe


class InvoiceLifecycleProbe(Probe):
    name = "invoices.create_send_manual_payment"
    description = (
        "Admin creates an invoice with a real line item for a throwaway "
        "customer, sends it, records a manual payment, confirms totals and "
        "status -- then hard-deletes the payment, the invoice (cascades "
        "line items, but NOT payments -- that FK is RESTRICT, not "
        "CASCADE), and the throwaway customer, in that order"
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        test_email = f"prodtest-invoice-{uuid.uuid4()}@example.invalid"
        test_password = "prodtest-harness-password-1"

        with ProdHttpClient(env.base_url) as customer_client:
            register = customer_client.post(
                "/api/auth/register",
                json={"email": test_email, "password": test_password},
            )
            assert register.status_code == 200, register.text
            customer_id = customer_client.get("/api/me").json()["user_id"]
            customer_client.logout()

        admin_client = get_shared_admin_client(env)

        def _delete_customer() -> None:
            hard_delete_row(admin_client, "users", customer_id)
            if row_exists(admin_client, "users", customer_id):
                raise RuntimeError(f"customer {customer_id} still exists")

        cleanup.defer(
            f"hard-delete prodtest invoice customer {test_email}", _delete_customer
        )
        # test_email's domain (@example.invalid, RFC 2606) is deliberately
        # non-routable -- /send and /payments/manual below both trigger a
        # real notification send. Opt this throwaway customer out first,
        # or Gmail OAuth2 (unlike the SMTP transport this replaced) really
        # delivers to Google and gets a real mailer-daemon bounce back to
        # the sending mailbox. See opt_out_of_emails' own doc comment.
        opt_out_of_emails(admin_client, customer_id)

        create = admin_client.post(
            "/api/admin/invoices",
            params={
                "customer_id": customer_id,
                "memo": (
                    "prodtest harness invoice -- deleted automatically after this run"
                ),
            },
            json=[
                {
                    "description": "prodtest harness line item",
                    "quantity": "2",
                    "unit_price": "10.00",
                    "unit": "each",
                }
            ],
        )
        assert create.status_code == 200, create.text
        invoice_id = create.json()["id"]

        def _delete_invoice() -> None:
            hard_delete_row(admin_client, "invoices", invoice_id)
            if row_exists(admin_client, "invoices", invoice_id):
                raise RuntimeError(f"invoice {invoice_id} still exists")

        # Deferred before the invoice is customer-deleted (LIFO means
        # this revert runs BEFORE _delete_customer above, satisfying
        # the RESTRICT FK from invoices.customer_id -> users.id).
        cleanup.defer(f"hard-delete prodtest invoice {invoice_id}", _delete_invoice)

        got = admin_client.get(f"/api/admin/invoices/{invoice_id}")
        assert got.status_code == 200, got.text
        body = got.json()
        assert body["amount_total"] == "20.00", body
        assert body["status"] == "draft", body

        send = admin_client.post(f"/api/admin/invoices/{invoice_id}/send")
        assert send.status_code == 200, send.text

        payment = admin_client.post(
            f"/api/admin/invoices/{invoice_id}/payments/manual",
            json={"method": "zelle", "amount": "20.00", "note": "prodtest harness"},
        )
        assert payment.status_code == 200, payment.text
        payment_id = payment.json()["id"]

        def _delete_payment() -> None:
            # Payment.invoice_id is ondelete="RESTRICT" (NOT CASCADE --
            # confirmed the hard way: an earlier version of this probe
            # deferred only the invoice's own delete and left a real
            # invoice + payment + customer on production after a 409
            # "constraint violation" broke cleanup). Must be deleted
            # before the invoice.
            hard_delete_row(admin_client, "payments", payment_id)
            if row_exists(admin_client, "payments", payment_id):
                raise RuntimeError(f"payment {payment_id} still exists")

        # Deferred after invoice creation's own defer (LIFO -> this
        # revert runs BEFORE _delete_invoice above).
        cleanup.defer(f"hard-delete prodtest payment {payment_id}", _delete_payment)

        final = admin_client.get(f"/api/admin/invoices/{invoice_id}")
        assert final.status_code == 200, final.text
        assert final.json()["status"] == "paid", final.json()
