from __future__ import annotations

import argparse
import asyncio
from uuid import UUID, uuid4

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.api._uploads import read_upload_capped, safe_filename
from logand_backend.api.errors import to_http_exception
from logand_backend.app.config import AppConfig
from logand_backend.auth.rate_limit import CUSTOMER_PAY, RateLimiter
from logand_backend.auth.sessions import SessionInfo, require_customer
from logand_backend.db.base import get_db
from logand_backend.db.models.invoices import Invoice, Payment
from logand_backend.domain.invoices.export import generate_invoice_pdf
from logand_backend.domain.invoices.pdf.renderer import PdfRenderError
from logand_backend.domain.invoices.service import (
    attach_payment_proof,
    flag_invoice_needs_review,
    get_amount_due,
    has_pending_payment,
    settle_invoice_if_paid,
)
from logand_backend.domain.notifications.notify import notify_payment_received
from logand_backend.domain.payments.currency import quantize_to_currency, to_minor_units
from logand_backend.domain.payments.providers import paypal, stripe_provider
from logand_backend.domain.storage.factory import get_storage_backend
from logand_backend.logging import get_logger

_log = get_logger(__name__)

router = APIRouter(prefix="/api/invoices", tags=["customer", "invoices"])
# redis_url wired from config -- see api/auth.py's identical NOTE for why
# this previously always used RateLimiter's in-process fallback regardless
# of REDIS_URL, and why AppConfig.redis_url defaulting to None (rather than
# a hardcoded-looking-real URL) matters here.
_pay_limiter = RateLimiter(
    *CUSTOMER_PAY, redis_url=AppConfig.from_external(argparse.Namespace()).redis_url
)


def _invoice_summary(invoice: Invoice) -> dict:
    return {
        "id": str(invoice.id),
        "status": invoice.status,
        "amount_total": str(
            quantize_to_currency(invoice.amount_total, invoice.currency)
        ),
        "currency": invoice.currency,
        "memo": invoice.memo,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
    }


@router.get("")
async def list_my_invoices(
    customer: SessionInfo = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    # NOTE: WHERE customer_id = customer.user_id always -- never accept a
    # customer_id from the request, see docs/design/04 ownership isolation.
    query = select(Invoice).where(
        Invoice.customer_id == customer.user_id, Invoice.deleted_at.is_(None)
    )
    rows = (await db.execute(query.order_by(Invoice.created_at.desc()))).scalars().all()
    return [_invoice_summary(row) for row in rows]


@router.get("/payment-methods")
async def get_payment_methods(
    _customer: SessionInfo = Depends(require_customer),
) -> dict:
    """Tells the frontend which payment methods are actually usable right
    now -- "paypal" only when real API credentials are configured (see
    domain/payments/providers/paypal.py's is_configured), so the customer-
    facing UI can hide/disable a PayPal button instead of offering one
    that would just 503. "manual" methods are always listed since an
    admin can record any of them regardless of what's configured -- this
    just tells the CUSTOMER-facing pay page what to show as a self-serve
    option, not what an admin can record after the fact.

    Registered BEFORE the "/{invoice_id}" route below -- FastAPI matches
    routes in registration order, and "/{invoice_id}" would otherwise
    swallow a literal "/payment-methods" path as if "payment-methods"
    were an invoice ID (and fail a UUID parse) if this came after it.
    """
    cfg = AppConfig.from_external(argparse.Namespace())
    return {
        # Gated on BOTH the publishable key AND the secret key being set
        # (stripe_provider.is_configured -- FINDINGS.md M1) -- the browser
        # can't mount Stripe's Payment Element without the pk_, and /pay
        # can't mint a PaymentIntent without a real secret, so gating on
        # only one half let an operator set a real pk_ while the secret was
        # still the unconfigured default, advertising a card button that
        # would dead-end on every /pay call. Same hide-what-can't-work
        # convention as "paypal" below.
        "stripe": stripe_provider.is_configured(cfg),
        # The frontend passes this straight to loadStripe(); pk_ keys are
        # designed to be public (they can only tokenize, never charge or
        # read), so returning it to an authenticated customer is fine.
        "stripe_publishable_key": cfg.stripe_publishable_key,
        "paypal": paypal.is_configured(cfg),
        "manual_methods_available_via_admin": ["zelle", "in_person", "other", "paypal"],
        # None when unconfigured (see AppConfig.zelle_handle's own doc
        # comment) -- the pay page only renders a Zelle option once this
        # is a real value, not a blank placeholder.
        "zelle_handle": cfg.zelle_handle,
    }


async def _get_owned_invoice(
    db: AsyncSession, invoice_id: UUID, customer_id: UUID, *, for_update: bool = False
) -> Invoice:
    # for_update=True (SELECT ... FOR UPDATE) on every path that reads the
    # invoice's status/amount and then acts on it (creating a payment
    # intent, capturing a PayPal order) -- serializes two concurrent
    # requests against the SAME invoice (a double-clicked pay button, two
    # browser tabs) so neither can act on a stale read of "still payable"
    # after the other has already started/finished paying it. Plain reads
    # (get_my_invoice, the PDF route) pass for_update=False (the default)
    # since taking a write lock there would serialize downloads against
    # payment operations for no reason.
    query = select(Invoice).where(Invoice.id == invoice_id)
    if for_update:
        query = query.with_for_update()
    invoice = (await db.execute(query)).scalar_one_or_none()
    # NOTE: 404 (not 403) whether the invoice doesn't exist OR exists but
    # isn't owned by this customer -- never let the response distinguish the
    # two (docs/design/04).
    if (
        invoice is None
        or invoice.deleted_at is not None
        or invoice.customer_id != customer_id
    ):
        raise HTTPException(status_code=404, detail="invoice not found")
    return invoice


@router.get("/{invoice_id}")
async def get_my_invoice(
    invoice_id: UUID,
    customer: SessionInfo = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    invoice = await _get_owned_invoice(db, invoice_id, customer.user_id)
    return _invoice_summary(invoice)


_PROOF_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "application/pdf"}


@router.post("/{invoice_id}/payment-proof")
async def upload_payment_proof(
    request: Request,
    invoice_id: UUID,
    file: UploadFile,
    customer: SessionInfo = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """ "An optional place to put a screenshot or something to show that
    they sent something" -- a customer attaching proof of an external
    Zelle/PayPal-direct send for an admin to review before marking the
    invoice paid. Ownership-checked the same way every other customer
    route is (_get_owned_invoice, 404 not 403 either way -- docs/design/04).
    """
    await _get_owned_invoice(db, invoice_id, customer.user_id)
    if file.content_type not in _PROOF_CONTENT_TYPES:
        raise HTTPException(
            status_code=415, detail="payment proof must be an image or PDF"
        )
    contents = await read_upload_capped(file, request)
    file_path = f"payment-proofs/{invoice_id}/{uuid4()}-{safe_filename(file.filename)}"
    result = await attach_payment_proof(
        db, invoice_id, customer.user_id, contents, file_path, file.content_type
    )
    if result.is_err:
        raise to_http_exception(result.danger_err)
    # Written AFTER the DB row succeeds (attach_payment_proof only flushes;
    # the real COMMIT happens in get_db's dependency teardown after this
    # route returns) -- same ordering as api/budget.py's upload_evidence and
    # api/documents.py's upload. This guards against a *failed* DB write (a
    # flush error rolls back before we ever reach this put). It does NOT
    # guard the reverse: if the final commit itself fails after this put
    # succeeds, the object is orphaned in storage with no owning row.
    # Accepted tradeoff (FINDINGS.md L1) -- a periodic storage GC is
    # expected to reconcile objects with no owning row rather than this
    # route attempting a compensating delete on a commit it can't observe.
    cfg = AppConfig.from_external(argparse.Namespace())
    storage = get_storage_backend(cfg)
    await storage.put(file_path, contents, file.content_type)
    return {"id": str(result.danger_ok)}


@router.get("/{invoice_id}/pdf")
async def get_my_invoice_pdf(
    invoice_id: UUID,
    customer: SessionInfo = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # _get_owned_invoice (not generate_invoice_pdf's own NotFound check)
    # is what actually enforces ownership here -- generate_invoice_pdf
    # takes a bare invoice_id and doesn't know who's asking, by design
    # (it's shared with the admin route below, which has no ownership
    # restriction at all). This 404s on someone else's invoice before
    # ever reaching the PDF-generation step.
    await _get_owned_invoice(db, invoice_id, customer.user_id)
    cfg = AppConfig.from_external(argparse.Namespace())
    try:
        result = await generate_invoice_pdf(db, invoice_id, cfg)
    except PdfRenderError as exc:
        # The LaTeX compiler's own log is exactly what a real failure
        # (e.g. a LaTeX toolchain package missing from the deployed
        # image) needs to actually diagnose -- logged server-side, never
        # returned to the client (it's compiler internals, not something
        # a customer/admin should have to read to understand "PDF
        # generation failed").
        _log.error("invoice PDF generation failed", extra={"log": exc.log})
        raise HTTPException(
            status_code=500, detail="failed to generate invoice PDF"
        ) from exc
    if result.is_err:
        raise to_http_exception(result.danger_err)
    return Response(
        content=result.danger_ok,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="invoice-{invoice_id}.pdf"'},
    )


class PayPalCaptureRequest(BaseModel):
    model_config = {}

    order_id: str


@router.post("/{invoice_id}/pay/paypal")
async def pay_invoice_via_paypal(
    invoice_id: UUID,
    customer: SessionInfo = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _pay_limiter.check("invoice_pay_paypal", str(customer.user_id))
    invoice = await _get_owned_invoice(
        db, invoice_id, customer.user_id, for_update=True
    )
    if invoice.status not in ("sent", "overdue"):
        raise HTTPException(
            status_code=409, detail="invoice is not payable in its current state"
        )
    # M1 in FINDINGS.md: a PENDING PayPal capture from an earlier attempt
    # leaves amount_due at the full total (pending contributes nothing to
    # get_paid_so_far), so without this guard a second order could be
    # created and captured on top of the still-outstanding one.
    if await has_pending_payment(db, invoice.id):
        raise HTTPException(
            status_code=409,
            detail="a payment is still being reviewed for this invoice; please wait",
        )
    amount_due = await get_amount_due(db, invoice)
    if amount_due <= 0:
        raise HTTPException(
            status_code=409,
            detail="invoice is already fully paid pending settlement; refresh the page",
        )

    cfg = AppConfig.from_external(argparse.Namespace())

    # M2 in FINDINGS.md (bounded fix, part (b)): a live Stripe intent
    # confirms entirely client-side/out-of-band -- if one already exists
    # for this invoice, refuse to also start a PayPal order, or a customer
    # who then confirms the card AND completes the PayPal payment could
    # double-collect once the PayPal side captures (fully closing this
    # would require actively cancelling the live Stripe intent here, which
    # would cancel a payment attempt the customer may currently be mid-way
    # through confirming -- out of scope for this bounded fix).
    if invoice.stripe_payment_intent_id:
        # A live intent ID on the invoice only ever gets set by pay_invoice
        # below, which refuses to run at all unless stripe_provider.
        # is_configured(cfg) was true -- so payment_processor_secret is
        # guaranteed set here too.
        assert cfg.payment_processor_secret is not None
        stripe.api_key = cfg.payment_processor_secret
        if cfg.stripe_api_base:
            stripe.api_base = cfg.stripe_api_base
        existing_intent = await asyncio.to_thread(
            stripe.PaymentIntent.retrieve, invoice.stripe_payment_intent_id
        )
        if existing_intent.status == "succeeded":
            # Mirrors pay_invoice's own check: the webhook hasn't caught up
            # yet, but the money has already moved on Stripe's side --
            # never let PayPal collect on top of that.
            raise HTTPException(
                status_code=409,
                detail="this invoice has already been paid; refresh the page",
            )
        if existing_intent.status != "canceled":
            raise HTTPException(
                status_code=409,
                detail=(
                    "a card payment is already in progress for this invoice; "
                    "finish or cancel it before trying PayPal"
                ),
            )

    result = await paypal.create_order(
        cfg, str(invoice.id), amount_due, invoice.currency
    )
    if result.is_err:
        # NotConfigured surfaces as a real 503 here (see api/errors.py) --
        # the frontend uses that specific status to show "PayPal isn't
        # available yet, try Zelle or contact us" rather than a generic
        # error banner indistinguishable from an actual outage.
        raise to_http_exception(result.danger_err)
    order = result.danger_ok
    return {"order_id": order.order_id, "approval_url": order.approval_url}


@router.post("/{invoice_id}/pay/paypal/capture")
async def capture_invoice_paypal_payment(
    invoice_id: UUID,
    body: PayPalCaptureRequest,
    customer: SessionInfo = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _pay_limiter.check("invoice_pay_paypal_capture", str(customer.user_id))
    invoice = await _get_owned_invoice(
        db, invoice_id, customer.user_id, for_update=True
    )
    # Idempotent retry: if this exact order was already captured and
    # recorded (the first capture succeeded server-side but the HTTP
    # response was lost, e.g. a dropped connection or a page reload --
    # capture_order's own docstring advertises retry safety), the invoice
    # has already flipped to "paid" by now, so the payability guard below
    # would 409 a customer who genuinely paid. Check for an existing
    # succeeded Payment for this order_id BEFORE that guard and short-
    # circuit to the same success response instead.
    # Look up any Payment already recorded for this order_id regardless of
    # status -- a retry (client re-firing capture after a lost response,
    # or after a previous call recorded a "pending" capture -- see M1 in
    # FINDINGS.md) must short-circuit to the SAME response instead of
    # re-inserting a second row, which would violate
    # uq_payments_paypal_order_id.
    existing_payment = (
        await db.execute(
            select(Payment).where(
                Payment.invoice_id == invoice.id,
                Payment.paypal_order_id == body.order_id,
            )
        )
    ).scalar_one_or_none()
    if existing_payment is not None and existing_payment.status == "succeeded":
        return {"status": "captured"}
    if existing_payment is not None and existing_payment.status == "pending":
        return {"status": "pending"}
    # L1 in FINDINGS.md: reconcile_pending_paypal_captures can mark a
    # previously-pending capture "failed" (PayPal reported DECLINED/
    # VOIDED after the fact). A re-fire of capture for that same order_id
    # must be refused outright here rather than falling through to a
    # second paypal.capture_order call + a second INSERT -- if PayPal now
    # returned COMPLETED, that INSERT would collide with this existing
    # "failed" row on uq_payments_paypal_order_id and raise an unhandled
    # IntegrityError (500).
    if existing_payment is not None and existing_payment.status == "failed":
        raise HTTPException(
            status_code=409,
            detail="this payment attempt already failed; please try again",
        )
    # M1 in FINDINGS.md: this route is the ONLY place a pending Payment
    # row for PayPal gets created, so it must guard against a second,
    # DIFFERENT order's capture proceeding while an earlier one from this
    # invoice is still pending review -- the exact-order short-circuit
    # above only dedups a retry of the SAME order_id. Checked after that
    # short-circuit so a legitimate retry of the still-pending order
    # itself still returns {"status": "pending"} instead of 409ing.
    if existing_payment is None and await has_pending_payment(db, invoice.id):
        raise HTTPException(
            status_code=409,
            detail="a payment is still being reviewed for this invoice; please wait",
        )
    if invoice.status not in ("sent", "overdue"):
        raise HTTPException(
            status_code=409, detail="invoice is not payable in its current state"
        )

    cfg = AppConfig.from_external(argparse.Namespace())
    # Stable per invoice+order pair: a client retry (Pay.tsx re-firing
    # capture after a lost response) sends the same order_id for the same
    # invoice, so this key is identical across retries and PayPal returns
    # the original capture response instead of attempting a second charge.
    idempotency_key = f"capture:{invoice.id}:{body.order_id}"
    result = await paypal.capture_order(cfg, body.order_id, idempotency_key)
    if result.is_err:
        raise to_http_exception(result.danger_err)
    capture = result.danger_ok

    # Never trust the client-supplied order_id to actually belong to this
    # invoice, or a PayPal capture in a non-final state, or one in a
    # different currency than the invoice: reference_id is PayPal's own
    # echo of the reference_id this app set on create_order (the invoice
    # id) -- a mismatch means the order_id in the request body wasn't the
    # one this invoice's own pay flow created. status must be COMPLETED or
    # PENDING -- anything else (DECLINED, VOIDED, ...) is not money
    # received and never will be, so it's rejected outright. PENDING (a
    # capture held for review) IS money PayPal has already acted on --
    # see M1 in FINDINGS.md: discarding it here with no record would
    # strand real captured funds with no way to reconcile once PayPal
    # later settles it. currency is compared because paid_so_far below
    # sums raw Decimal amounts across payments with no currency
    # conversion; a capture in the wrong currency would silently count as
    # if it were the invoice's own currency.
    if capture.reference_id != str(invoice.id):
        raise HTTPException(
            status_code=409, detail="PayPal order does not belong to this invoice"
        )
    if capture.status not in ("COMPLETED", "PENDING"):
        raise HTTPException(
            status_code=409,
            detail=f"PayPal capture not completed (status={capture.status})",
        )
    if capture.captured_currency.lower() != invoice.currency.lower():
        raise HTTPException(
            status_code=409, detail="PayPal capture currency does not match invoice"
        )

    if capture.status == "PENDING":
        # Record the money in the ledger now -- do NOT call
        # settle_invoice_if_paid (a "pending" Payment contributes nothing
        # to get_paid_so_far, see domain/invoices/service.py) and do NOT
        # notify the customer of a completed payment yet.
        # reconcile_pending_paypal_captures (domain/invoices/service.py,
        # run daily from scripts/scheduler.py, mirrors
        # reconcile_pending_paypal_refunds) polls PayPal until this
        # settles one way or the other.
        db.add(
            Payment(
                invoice_id=invoice.id,
                method="paypal",
                paypal_order_id=capture.order_id,
                paypal_capture_id=capture.capture_id,
                amount=capture.captured_amount,
                status="pending",
            )
        )
        await db.flush()
        _log.warning(
            "paypal capture pending (e.g. held for review); recorded as "
            "pending, not yet settled -- awaiting reconciliation",
            extra={
                "invoice_id": str(invoice.id),
                "order_id": capture.order_id,
                "capture_id": capture.capture_id,
                "captured_amount": str(capture.captured_amount),
            },
        )
        await db.commit()
        return {"status": "pending"}

    # create_order sets `value` to the outstanding remainder (amount_total
    # minus payments already recorded) at order-creation time. By the time
    # capture happens, that remainder can have changed (e.g. a manual
    # payment recorded concurrently), so expected_amount here is only used
    # to flag an overpayment for follow-up -- see H1 in FINDINGS.md: money
    # has ALREADY moved at PayPal once capture_order returns COMPLETED
    # (checked above), so a mismatch here must never cause the Payment to
    # be discarded. Discarding it would strand real captured funds with no
    # record and no way to reconcile (a retry just re-hits the same
    # idempotency key and gets the same COMPLETED capture again).
    expected_amount = await get_amount_due(db, invoice)
    overpaid = expected_amount <= 0 or capture.captured_amount != expected_amount

    db.add(
        Payment(
            invoice_id=invoice.id,
            method="paypal",
            paypal_order_id=capture.order_id,
            paypal_capture_id=capture.capture_id,
            amount=capture.captured_amount,
            status="succeeded",
        )
    )
    await db.flush()

    if overpaid:
        _log.warning(
            "paypal capture amount does not match amount due; recorded anyway",
            extra={
                "invoice_id": str(invoice.id),
                "order_id": capture.order_id,
                "capture_id": capture.capture_id,
                "captured_amount": str(capture.captured_amount),
                "expected_amount": str(expected_amount),
            },
        )
        await flag_invoice_needs_review(
            db,
            invoice,
            "paypal capture amount does not match amount due "
            f"(captured={capture.captured_amount}, expected={expected_amount})",
        )

    # Same "sum every succeeded payment, mark paid once it covers the
    # total" logic as domain/invoices/service.py's record_manual_payment
    # (and api/webhooks.py's Stripe path) -- a customer could in
    # principle combine a partial manual payment with a PayPal payment
    # for the remainder, so this always sums everything rather than
    # assuming this one capture is the only payment ever made against
    # the invoice.
    await settle_invoice_if_paid(db, invoice)

    # Release the invoice row's FOR UPDATE lock before the email round-
    # trip -- mirrors the Stripe webhook payment path (api/webhooks.py),
    # which commits before notify_payment_received for the same reason:
    # a slow mail send must never hold this lock and block a concurrent
    # capture retry / manual payment / void on the same invoice (M2).
    # expire_on_commit=False (db/base.py) means invoice.* is still safely
    # readable below without an illegal async lazy-load.
    await db.commit()

    await notify_payment_received(db, cfg, invoice, capture.captured_amount)

    return {"status": "captured"}


@router.post("/{invoice_id}/pay")
async def pay_invoice(
    invoice_id: UUID,
    customer: SessionInfo = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    await _pay_limiter.check("invoice_pay", str(customer.user_id))
    # for_update=True -- serializes this against any other concurrent
    # request touching the same invoice (another /pay call, a manual
    # payment, a PayPal capture), see _get_owned_invoice's own doc
    # comment. Combined with the idempotent-reuse check just below, this
    # is what actually prevents a double-clicked "Pay" button (or two
    # open tabs) from creating two separate live PaymentIntents that a
    # customer could then go on to confirm both of, charging their card
    # twice for one invoice.
    invoice = await _get_owned_invoice(
        db, invoice_id, customer.user_id, for_update=True
    )
    if invoice.status not in ("sent", "overdue"):
        raise HTTPException(
            status_code=409, detail="invoice is not payable in its current state"
        )
    # M1 in FINDINGS.md: block starting a Stripe payment while an earlier
    # PayPal capture is still pending review -- amount_due doesn't yet
    # reflect it, so without this a second payment could settle on top of
    # money PayPal already holds against this invoice.
    if await has_pending_payment(db, invoice.id):
        raise HTTPException(
            status_code=409,
            detail="a payment is still being reviewed for this invoice; please wait",
        )
    amount_due = await get_amount_due(db, invoice)
    if amount_due <= 0:
        raise HTTPException(
            status_code=409,
            detail="invoice is already fully paid pending settlement; refresh the page",
        )

    # NOTE: card data never touches this server -- Stripe Checkout/PaymentIntents
    # handles capture entirely on Stripe's side, see docs/design/04.
    cfg = AppConfig.from_external(argparse.Namespace())
    # FINDINGS.md M1: refuse outright (503, same convention as PayPal's
    # NotConfigured) rather than proceeding with an unset/placeholder
    # secret -- get_payment_methods above only advertises "stripe": True
    # once this same predicate is true, but a client could still hit this
    # route directly (stale page, crafted request), so it's re-checked here
    # rather than trusted from the earlier GET.
    if not stripe_provider.is_configured(cfg):
        raise HTTPException(
            status_code=503, detail="card payments are not configured"
        )
    assert cfg.payment_processor_secret is not None
    stripe.api_key = cfg.payment_processor_secret
    # None in production (stripe-python's own default: real api.stripe.com)
    # -- only set in test/CI, pointing at testing/fake_stripe.py's local
    # HTTP double, see AppConfig.stripe_api_base's doc comment.
    if cfg.stripe_api_base:
        stripe.api_base = cfg.stripe_api_base

    # Idempotent resume: if a PREVIOUS call already created a still-live
    # intent for this invoice (a reload of the pay page, a retried
    # request), reuse it instead of creating a second one -- Stripe would
    # happily create as many PaymentIntents as asked, and a customer
    # confirming two of them (two browser tabs, a slow first request
    # retried) would really charge their card twice.
    #
    # stripe-python's PaymentIntent.retrieve/create are synchronous
    # (blocking DNS + socket I/O) -- asyncio.to_thread, same reasoning as
    # render_invoice_pdf's own to_thread call for latexmk, so one slow
    # Stripe round trip doesn't stall every other concurrent request on
    # this process.
    if invoice.stripe_payment_intent_id:
        existing_intent = await asyncio.to_thread(
            stripe.PaymentIntent.retrieve, invoice.stripe_payment_intent_id
        )
        if existing_intent.status == "succeeded":
            # Already paid on Stripe's side -- either the webhook hasn't
            # landed yet or is about to. Creating a SECOND PaymentIntent
            # here would let the customer confirm both, charging their
            # card twice for one invoice; refuse instead and let the
            # webhook (or a retry once it has caught up) settle the
            # invoice's status.
            raise HTTPException(
                status_code=409,
                detail="this invoice has already been paid; refresh the page",
            )
        if existing_intent.status != "canceled":
            expected_minor_units = to_minor_units(amount_due, invoice.currency)
            if existing_intent.amount == expected_minor_units:
                assert existing_intent.client_secret is not None
                return {"client_secret": existing_intent.client_secret}
            # The amount due changed since this intent was created (e.g.
            # an admin edit, or another payment recorded against the
            # invoice, since the customer opened the pay page) -- reusing
            # it would let the customer confirm a payment for the OLD
            # amount while the invoice now expects a different remainder,
            # so settle_invoice_if_paid could over- or under-collect.
            # Cancel the stale intent and fall through to create a fresh
            # one for the current amount due.
            await asyncio.to_thread(stripe.PaymentIntent.cancel, existing_intent.id)

    intent = await asyncio.to_thread(
        stripe.PaymentIntent.create,
        amount=to_minor_units(amount_due, invoice.currency),
        currency=invoice.currency,
        metadata={"invoice_id": str(invoice.id)},
    )
    invoice.stripe_payment_intent_id = intent.id
    await db.flush()
    # client_secret is only None for an already-confirmed/cancelled intent,
    # which a freshly created intent never is.
    assert intent.client_secret is not None
    return {"client_secret": intent.client_secret}
