from __future__ import annotations

import time
import uuid

from scripts.prodtest.admin_data_helper import hard_delete_row, row_exists
from scripts.prodtest.admin_session import get_shared_admin_client
from scripts.prodtest.env import ProdEnv
from scripts.prodtest.http_client import ProdHttpClient
from scripts.prodtest.revert import Cleanup, Probe


def _fetch_log_lines(admin_client: ProdHttpClient) -> list[str]:
    log_lines = admin_client.get("/api/admin/logs/tail", params={"lines": 500})
    assert log_lines.status_code == 200, log_lines.text
    result: list[str] = log_lines.json()
    return result


def _assert_notification_not_failed(
    lines: list[str], failure_marker: str, invoice_id: str, recipient: str
) -> None:
    failures = [line for line in lines if failure_marker in line and invoice_id in line]
    assert not failures, (
        f"{failure_marker!r} was logged for {recipient}:\n" + "\n".join(failures)
    )


class InvoiceNotificationEmailProbe(Probe):
    name = "notifications.invoice_and_payment_email_send"
    description = (
        "Real end-to-end mail send test (SMTP or Gmail OAuth2, whichever "
        "domain/notifications/mailer.py is actually configured for -- see "
        "that module's own doc comment) -- registers a throwaway customer "
        "at env.notification_email (PRODTEST_NOTIFICATION_EMAIL, default "
        "prodtest@logand.app), creates+sends them an invoice (triggers "
        "notify_invoice_sent) and records a manual payment against it "
        "(triggers notify_payment_received), then tails the backend's own "
        "logs to confirm neither send was logged as failed. This is the "
        "one probe that actually authenticates against the real mail "
        "transport's credentials and sends real mail -- health_check.py's "
        "own check (see payment_provider_health.py's SmtpReachabilityProbe) "
        "only proves the transport is reachable/the OAuth2 token exchange "
        "works, not that a real send actually succeeds end to end. "
        "mailer.send_email() swallows send failures (see notify.py's own "
        "doc comment -- email is best-effort, never blocks the invoice/"
        "payment flow itself), so 'no error logged' is the strongest "
        "automatable proof of success available without giving this "
        "harness IMAP access to the inbox; the destination address is "
        "printed below for a quick manual glance at the real inbox to "
        "finish confirming."
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        # A unique local-part under the configured recipient's domain, not
        # the bare configured address itself -- Stripe/mail-provider
        # catch-all routing (see env.py's own doc comment) still delivers
        # it to the same real inbox, while keeping this probe's throwaway
        # customer account distinguishable from a real one at that exact
        # address if one ever exists.
        local, _, domain = env.notification_email.partition("@")
        test_email = f"{local}-{uuid.uuid4().hex[:8]}@{domain}"
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
            f"hard-delete prodtest notification customer {test_email}",
            _delete_customer,
        )

        create = admin_client.post(
            "/api/admin/invoices",
            params={
                "customer_id": customer_id,
                "memo": "prodtest harness invoice -- deleted automatically after run",
            },
            json=[
                {
                    "description": "prodtest harness line item",
                    "quantity": "1",
                    "unit_price": "1.00",
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

        # Deferred before the customer's own defer above (LIFO -> runs
        # BEFORE _delete_customer, same FK-order reasoning as
        # invoice_flow.py's InvoiceLifecycleProbe).
        cleanup.defer(
            f"hard-delete prodtest notification invoice {invoice_id}", _delete_invoice
        )

        # Real send #1: notify_invoice_sent (api/invoices.py's send route).
        send = admin_client.post(f"/api/admin/invoices/{invoice_id}/send")
        assert send.status_code == 200, send.text

        # Real send #2: notify_payment_received (record_manual_payment).
        payment = admin_client.post(
            f"/api/admin/invoices/{invoice_id}/payments/manual",
            json={"method": "zelle", "amount": "1.00", "note": "prodtest harness"},
        )
        assert payment.status_code == 200, payment.text
        payment_id = payment.json()["id"]

        def _delete_payment() -> None:
            # Payment.invoice_id is ondelete="RESTRICT" -- must go before
            # the invoice's own delete (see invoice_flow.py's identical
            # comment for why this was confirmed the hard way).
            hard_delete_row(admin_client, "payments", payment_id)
            if row_exists(admin_client, "payments", payment_id):
                raise RuntimeError(f"payment {payment_id} still exists")

        cleanup.defer(
            f"hard-delete prodtest notification payment {payment_id}", _delete_payment
        )

        # notify_* is fired synchronously within the request (see
        # notify.py), but the actual SMTP conversation happens via
        # asyncio.to_thread inside that same request/response cycle --
        # by the time send/payment above returned 200, the send attempt
        # (success or logged failure) has already happened. A short sleep
        # is still cheap insurance against any log-flush delay before the
        # tail below reads it.
        time.sleep(1.0)

        lines = _fetch_log_lines(admin_client)
        _assert_notification_not_failed(
            lines, "failed to send invoice-sent notification", invoice_id, test_email
        )
        _assert_notification_not_failed(
            lines,
            "failed to send payment-received notification",
            invoice_id,
            test_email,
        )

        print(
            f"    (sent 2 real notification emails to {test_email} -- "
            "glance at that inbox to finish confirming delivery/content)"
        )


class RefundSettlementNotificationProbe(Probe):
    name = "notifications.refund_settled_email_send"
    description = (
        "Real end-to-end mail send test for notify_refund_settled -- the "
        "one notify_* path InvoiceNotificationEmailProbe doesn't exercise. "
        "Registers a throwaway customer, creates+sends an invoice, records "
        "a manual payment, then refunds it via the manual refund path "
        "(method='manual' settles synchronously inside refund_payment "
        "itself -- see domain/invoices/refunds.py -- so the notification "
        "send attempt has already happened by the time the refund request "
        "returns, same as the invoice/payment sends above), then tails the "
        "backend's own logs to confirm the send wasn't logged as failed."
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        local, _, domain = env.notification_email.partition("@")
        test_email = f"{local}-{uuid.uuid4().hex[:8]}@{domain}"
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
            f"hard-delete prodtest refund-notification customer {test_email}",
            _delete_customer,
        )

        create = admin_client.post(
            "/api/admin/invoices",
            params={
                "customer_id": customer_id,
                "memo": "prodtest harness invoice -- deleted automatically after run",
            },
            json=[
                {
                    "description": "prodtest harness line item",
                    "quantity": "1",
                    "unit_price": "1.00",
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

        cleanup.defer(
            f"hard-delete prodtest refund-notification invoice {invoice_id}",
            _delete_invoice,
        )

        send = admin_client.post(f"/api/admin/invoices/{invoice_id}/send")
        assert send.status_code == 200, send.text

        payment = admin_client.post(
            f"/api/admin/invoices/{invoice_id}/payments/manual",
            json={"method": "zelle", "amount": "1.00", "note": "prodtest harness"},
        )
        assert payment.status_code == 200, payment.text
        payment_id = payment.json()["id"]

        def _delete_payment() -> None:
            hard_delete_row(admin_client, "payments", payment_id)
            if row_exists(admin_client, "payments", payment_id):
                raise RuntimeError(f"payment {payment_id} still exists")

        cleanup.defer(
            f"hard-delete prodtest refund-notification payment {payment_id}",
            _delete_payment,
        )

        refund = admin_client.post(
            f"/api/admin/invoices/{invoice_id}/payments/{payment_id}/refund",
            json={
                "payment_id": payment_id,
                "amount": "1.00",
                "reason": "prodtest harness",
                "client_request_id": str(uuid.uuid4()),
            },
        )
        assert refund.status_code == 200, refund.text
        refund_id = refund.json()["id"]

        def _delete_refund() -> None:
            # Refund.payment_id has the same RESTRICT-before-parent-delete
            # constraint reasoning as Payment.invoice_id above -- must go
            # before the payment's own delete.
            hard_delete_row(admin_client, "refunds", refund_id)
            if row_exists(admin_client, "refunds", refund_id):
                raise RuntimeError(f"refund {refund_id} still exists")

        cleanup.defer(
            f"hard-delete prodtest refund-notification refund {refund_id}",
            _delete_refund,
        )

        # A manual refund settles synchronously inside refund_payment
        # itself (no provider webhook round-trip to wait for), so the
        # send attempt has already happened by the time the request above
        # returned 200 -- same cheap insurance sleep as the sibling probe.
        time.sleep(1.0)

        lines = _fetch_log_lines(admin_client)
        _assert_notification_not_failed(
            lines, "failed to send refund-settled notification", invoice_id, test_email
        )

        print(
            f"    (sent 1 real refund-settled notification email to {test_email} -- "
            "glance at that inbox to finish confirming delivery/content)"
        )
