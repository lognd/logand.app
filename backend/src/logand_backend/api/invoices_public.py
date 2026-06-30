from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from logand_backend.auth.rate_limit import CUSTOMER_PAY, RateLimiter
from logand_backend.auth.sessions import SessionInfo, require_customer

router = APIRouter(prefix="/api/invoices", tags=["customer", "invoices"])
_pay_limiter = RateLimiter(*CUSTOMER_PAY)


@router.get("")
async def list_my_invoices(customer: SessionInfo = Depends(require_customer)) -> list[dict]:
    # NOTE: WHERE customer_id = customer.user_id always -- never accept a
    # customer_id from the request, see docs/design/04 ownership isolation.
    raise NotImplementedError("filtered list query; needs db.models.invoices")


@router.get("/{invoice_id}")
async def get_my_invoice(invoice_id: UUID, customer: SessionInfo = Depends(require_customer)) -> dict:
    # NOTE: 404 (not 403) if invoice_id exists but isn't owned by this
    # customer -- never let the response distinguish "doesn't exist" from
    # "exists but isn't yours" (docs/design/04).
    raise NotImplementedError("ownership-checked lookup; needs db.models.invoices")


@router.post("/{invoice_id}/pay")
async def pay_invoice(invoice_id: UUID, customer: SessionInfo = Depends(require_customer)) -> dict[str, str]:
    await _pay_limiter.check("invoice_pay", str(customer.user_id))
    raise NotImplementedError(
        "create Stripe PaymentIntent for invoice_id (after ownership check), "
        "return client_secret for Stripe.js; needs PAYMENT_PROCESSOR_SECRET + db.models.invoices"
    )
