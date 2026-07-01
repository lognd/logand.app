"""guard against double-recording the same provider payment

Revision ID: 0003_payment_idempotency
Revises: 0002_payment_methods
Create Date: 2026-07-01

Neither stripe_payment_intent_id nor paypal_order_id on payments had a
uniqueness constraint at the database level -- two concurrent requests
(a retried webhook delivery, a double-clicked capture, two browser tabs)
racing the read-then-insert in api/webhooks.py or
invoices_public.py::capture_invoice_paypal_payment could both pass an
"does a payment for this provider reference already exist?" check before
either one's INSERT commits, double-recording the same real-world payment
in our ledger. Application-level row locking (see the same-commit changes
to api/invoices_public.py, domain/invoices/service.py, api/webhooks.py)
closes the race in the common case; this is the belt-and-suspenders
DB-level backstop that holds even if a code path somehow doesn't take the
lock. Partial (WHERE ... IS NOT NULL) since most rows (manual payments)
never set these at all and NULL vs NULL should never be treated as a
value collision.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0003_payment_idempotency"
down_revision: Union[str, None] = "0002_payment_methods"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_payments_stripe_payment_intent_id",
        "payments",
        ["stripe_payment_intent_id"],
        unique=True,
        postgresql_where="stripe_payment_intent_id IS NOT NULL",
    )
    op.create_index(
        "uq_payments_paypal_order_id",
        "payments",
        ["paypal_order_id"],
        unique=True,
        postgresql_where="paypal_order_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_payments_paypal_order_id", table_name="payments")
    op.drop_index("uq_payments_stripe_payment_intent_id", table_name="payments")
