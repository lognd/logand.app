# Audit findings

Fresh pass (iteration 2 of the audit-fix convergence loop). Focused on the
recent refund/dispute/stats/auth work (b61d27d..a462237) plus money/auth/
data-integrity paths across backend, frontend, android, re-checked after
iteration 1's fixes (H1 client_request_id wiring, M1 Android StateFlow
dedup, L1 dispute-webhook renotify).

AUDIT COMPLETE: 0 HIGH, 3 MEDIUM, 3 LOW

## MEDIUM

### M1. [FIXED] Frontend counts failed AND pending refunds as "refunded", hiding a still-valid refund

**Fix applied**: `frontend/src/app/routes/admin/Invoices.tsx`'s `refundedSoFar` now filters to only `status === "succeeded" || status === "pending"` before summing, matching the backend's own remaining-balance semantics (see M2's fix, which now also reserves `pending` refunds). `frontend/src/api/invoices.ts`'s `Refund.status` type was widened to include `"pending"` (it was missing that value entirely, which would have been a type error against real API responses). Verified with `npx vitest run` (77 passed) and `tsc --noEmit` (clean).

### M1 (original). Frontend counts failed AND pending refunds as "refunded", hiding a still-valid refund

- **Where**: `frontend/src/app/routes/admin/Invoices.tsx`, `RefundForm`, lines 126-146.
- **What's wrong**: `refundedSoFar` sums every refund row regardless of status: `payment.refunds.reduce((sum, r) => sum + Number(r.amount), 0)`. The backend authority (`domain/invoices/refunds.py::_refunded_so_far`) counts ONLY `status == "succeeded"`. They disagree for any `pending`/`failed` refund.
- **Failure scenario**: Admin issues a $100 refund on a $100 payment; Stripe returns `failed` (no money moved). The row exists with `status="failed"`, so `refundedSoFar` = $100, `remaining` = $0, and `if (... || remaining <= 0) return null;` hides the Refund button. Admin can no longer retry from the UI despite the customer never being refunded. A `pending` PayPal refund similarly blocks a legitimate second partial refund.
- **Fix direction**: Only count `succeeded` (optionally `pending`, never `failed`) refunds in `refundedSoFar`, e.g. `payment.refunds.filter(r => r.status === "succeeded")` before summing.

### M2. [FIXED] Backend remaining-balance ignores pending refunds; only the provider stops a double refund

**Fix applied**: Added `_reserved_so_far` in `backend/src/logand_backend/domain/invoices/refunds.py`, which counts both `succeeded` and `pending` refunds. `refund_payment`'s `remaining` computation and `_record_refund`'s manual-path balance re-check now both use `_reserved_so_far` instead of `_refunded_so_far`. `_refunded_so_far` itself is left succeeded-only, since it also drives payment/invoice status transitions that should only fire on settlement. Verified with `uv run pytest tests/unit tests/integration` (224 passed) and `ruff`/`ty` clean.

### M2 (original). Backend remaining-balance ignores pending refunds; only the provider stops a double refund

- **Where**: `backend/src/logand_backend/domain/invoices/refunds.py`, `_refunded_so_far` (76-84), `refund_payment` (173-179), and `_record_refund`'s intentional skip of balance re-check for provider-backed refunds (278-301).
- **What's wrong**: `remaining = payment.amount - refunded_so_far` counts only `succeeded` refunds. A still-`pending` refund doesn't reduce remaining, and `payment.status` stays `succeeded` until settlement. For provider-backed refunds the follow-up transaction deliberately skips balance re-validation, so only the provider prevents a second full refund.
- **Failure scenario**: Admin A issues a full refund -> Stripe `pending`. Before settlement, Admin B (or a direct API call bypassing the M1 UI guard) issues another full refund. `remaining` still computes to the full amount, validation passes, a second `stripe.Refund.create` is attempted. Stripe/PayPal reject it today (they count pending refunds), so the outcome is a confusing provider error rather than lost money -- but the app relies entirely on the provider for an invariant it claims to enforce.
- **Fix direction**: Include `pending` refunds (as reserved amount) in the `remaining` computation in `refund_payment` so the over-refund is rejected before any second provider call.

### M3. [FIXED] Retry of a client_request_id whose original refund FAILED reports success

**Fix applied**: Added `RefundError.PriorAttemptFailed` (mapped to HTTP 409 in `api/errors.py`). `refund_payment`'s idempotency short-circuit now checks `existing.status == "failed"` and returns `Err(RefundError.PriorAttemptFailed)` instead of `Ok(existing.id)`, so a retry under the same `client_request_id` never reports success for a refund that moved no money. Verified with the backend test suite (224 passed) and `ruff`/`ty` clean.

### M3 (original). Retry of a client_request_id whose original refund FAILED reports success

- **Where**: `backend/src/logand_backend/domain/invoices/refunds.py`, `refund_payment`, lines 121-147.
- **What's wrong**: The idempotency short-circuit returns `Ok(existing.id)` for any pre-existing Refund with the same `client_request_id`, ignoring `existing.status`. A row can be `failed`.
- **Failure scenario**: First attempt records a Refund that ends `failed`. Client retries the same action (lost-response resubmit, same id). The retry finds the failed row and returns `Ok(existing.id)` -- API reports the refund succeeded when no money was refunded.
- **Fix direction**: If `existing.status == "failed"`, don't treat it as a satisfied retry -- return a distinct error variant the UI can surface, or attempt a fresh refund under a new id.

## LOW

### L1. [FIXED] Concurrent manual-refund retry returns AmountExceedsBalance instead of idempotent Ok

**Fix applied**: In `_record_refund`'s manual path (no provider id), before the balance re-check, now re-queries `Refund.id == refund_id`; if found (a concurrent retry that already committed under the same id while this call was serialized behind the invoice re-lock), returns `Ok(existing.id)` instead of proceeding to a balance check that would otherwise reject it. Verified with the backend test suite.

### L1 (original). Concurrent manual-refund retry returns AmountExceedsBalance instead of idempotent Ok

- **Where**: `backend/src/logand_backend/domain/invoices/refunds.py`, `_record_refund`, lines 293-301 (manual path).
- **What's wrong**: Two requests sharing a `client_request_id` that both pass the top lookup (retry in-flight) serialize on the invoice re-lock; the second sees the first's `succeeded` refund and returns `Err(AmountExceedsBalance)` instead of an idempotent `Ok`. Money stays correct; only the reported error is wrong.
- **Fix direction**: Before the manual-path balance re-check, re-query for `id == refund_id` and return `Ok(existing.id)` if found (mirroring the provider-id IntegrityError branch).

### L2. [FIXED] Migration 0015 downgrade fails if any partially_refunded payment exists

**Fix applied**: `downgrade()` now runs `UPDATE payments SET status = 'refunded' WHERE status = 'partially_refunded'` before recreating `ck_payments_status` without that value, so the CHECK's revalidation against existing rows can't abort the downgrade. Verified by reading the migration logic (no live downgrade test harness in this repo); `ruff`/`ty` clean.

### L2 (original). Migration 0015 downgrade fails if any partially_refunded payment exists

- **Where**: `backend/src/logand_backend/db/migrations/versions/0015_refunds_and_disputes.py`, `downgrade`, lines 137-141.
- **What's wrong**: Downgrade recreates `ck_payments_status` without `partially_refunded`, which live rows can hold; Postgres validates the new CHECK against existing rows and aborts. Downgrade-only.
- **Fix direction**: Normalize `partially_refunded` rows before recreating the constraint, or document 0015 as not safely reversible with refund data present.

### L3. [FIXED] Android logout() can double-fire onUnauthorized teardown

**Fix applied**: `logout()` in `android/core/src/main/kotlin/app/logand/core/ApiClient.kt` now calls `.decodeUnit(notifyOn401 = false)`, same as `login()`. Added a regression test (`onUnauthorized does not fire on logout's own 401`) to `ApiClientTest.kt`. Verified with the real Android test suite via `make test` in `android/` (BUILD SUCCESSFUL, all unit tests including the new one passed) -- the aapt2/Gradle sandbox issue that blocked this in the prior pass is resolved.

### L3 (original). Android logout() can double-fire onUnauthorized teardown

- **Where**: `android/core/src/main/kotlin/app/logand/core/ApiClient.kt`, `logout` (77-84), `decodeUnit` (251-256).
- **What's wrong**: `logout()` uses default `notifyOn401 = true`; an already-expired session makes `POST /api/auth/logout` return 401, firing `onUnauthorized` in addition to logout's own unconditional cookie-jar clear.
- **Fix direction**: Call logout's request with `notifyOn401 = false`, same rationale as `login()`.

## Notes

**Checked and found correct (fixer need not re-verify):** CSRF cookie==header==session.csrf_secret chain (auth.py `_set_session_cookies` <-> csrf.py <-> app.py middleware); single session lookup/slide per request; `validate_session` rejects expired+disabled users and the new session-revocation on deactivate/reset (users/service.py); Stripe payment-intent webhook idempotency (partial unique index + begin_nested + IntegrityError); dispute handler row-lock serialization and notify-on-transition (this pass's L1 fix from iteration 1 confirmed working); PayPal capture route verifies reference_id/currency/amount before recording; `currency.py` zero/two/three-decimal ROUND_HALF_UP; `stats.py` net_collected double-subtraction avoidance and `by_status` full pre-population; Pay.tsx PayPal token snapshot race fix; guards redirect only on UnauthenticatedError; `admin_data` `_validate_row_id` non-UUID 500 fix.

**Skimmed/skipped:** non-payment domains (bom, inventory, budget, mileage, receipts, documents) unchanged in range; mailer/template HTML-injection not audited; rate-limit Redis internals; alembic chain prior to 0015.
</content>
