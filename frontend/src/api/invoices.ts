import { apiGet, apiGetBlob, apiPost } from "./client";

// A raw line item request body, matching api/invoices.py's LineItemInput
// pydantic model field-for-field -- description/quantity/unit_price, not
// this file's usual mix of camelCase mistakes fixed elsewhere. Kept
// separate from the response-shaped MockInvoiceLineItem-adjacent types
// since this is what gets SENT, not what comes back.
export interface CreateInvoiceLineItem {
  description: string;
  quantity: string;
  unit_price: string;
  // Free-form unit label ("hr", "ea", "ft", "kg"...) shown next to the
  // unit price on the admin form, the customer view, and the PDF -- e.g.
  // "$45.00 / hr" instead of a bare "$45.00" that leaves what's actually
  // being priced ambiguous. Optional/blank is fine (a flat one-off charge
  // has no natural unit).
  unit: string;
}

// TODO(logan): replace with generated type once backend/openapi.json exists.
// snake_case fields (amount_total/due_date), not amountTotal/dueDate --
// found during a security/correctness audit that this interface (and
// mocks/data.ts's matching shape) had been declaring camelCase fields the
// real backend (api/invoices_public.py's _invoice_summary,
// api/invoices.py's identical admin one) never actually returns. Every
// page reading these fields had only ever been exercised against MSW
// mocks that happened to use the same (wrong) camelCase convention, so
// this silently rendered "undefined" for both fields against a real
// backend without anyone having noticed yet.
export interface Invoice {
  id: string;
  // "refunded" added alongside admin refund support (see
  // domain/invoices/refunds.py::refund_payment) -- set only once total
  // refunds across every payment on the invoice cover the full
  // amount_total; a partial or single-payment refund on a multi-payment
  // invoice leaves the invoice "paid".
  status: "draft" | "sent" | "paid" | "overdue" | "void" | "refunded";
  amount_total: string;
  currency: string;
  memo: string | null;
  due_date: string | null;
  // ISO 8601 timestamp, set once when status first flips to "paid" (see
  // db/models/invoices.py::Invoice.paid_at's own doc comment) -- null
  // for anything not yet paid.
  paid_at: string | null;
}

// One (partial or full) refund issued against a payment -- matches
// api/invoices.py's get_invoice route's "refunds" field on each payment,
// itself a serialized db/models/invoices.py::Refund row.
export interface Refund {
  id: string;
  amount: string;
  reason: string | null;
  status: "succeeded" | "pending" | "failed";
  stripe_refund_id: string | null;
  paypal_refund_id: string | null;
  recorded_by: string;
  created_at: string;
}

// One payment row on an invoice, as returned by the admin invoice-detail
// route (GET /api/admin/invoices/{id}) -- includes dispute_status/refunds,
// which the plain list view (listAdminInvoices) never returns.
export interface InvoicePayment {
  id: string;
  method: "stripe" | "paypal" | "zelle" | "in_person" | "other";
  amount: string;
  status: "pending" | "succeeded" | "failed" | "refunded" | "partially_refunded";
  transaction_id: string | null;
  note: string | null;
  recorded_by: string | null;
  // Null until a real Stripe charge.dispute.* webhook event lands on
  // this payment -- see api/webhooks.py's _handle_dispute_event.
  dispute_status: "needs_response" | "under_review" | "won" | "lost" | null;
  refunds: Refund[];
}

export interface InvoiceLineItemDetail {
  id: string;
  description: string;
  quantity: string;
  unit_price: string;
  unit: string | null;
}

export interface InvoiceDetail extends Invoice {
  line_items: InvoiceLineItemDetail[];
  payments: InvoicePayment[];
}

export function getAdminInvoice(id: string): Promise<InvoiceDetail> {
  return apiGet<InvoiceDetail>(`/api/admin/invoices/${id}`);
}

// Customer-scoped (/api/invoices, see api/invoices_public.py).
export function listInvoices(): Promise<Invoice[]> {
  return apiGet<Invoice[]>("/api/invoices");
}

export function getInvoice(id: string): Promise<Invoice> {
  return apiGet<Invoice>(`/api/invoices/${id}`);
}

// client_secret (not clientSecret) -- same real-field-name audit as
// Invoice above; api/invoices_public.py's /pay route returns
// {"client_secret": ...} literally.
export function payInvoice(id: string): Promise<{ client_secret: string }> {
  return apiPost<{ client_secret: string }>(`/api/invoices/${id}/pay`);
}

// Admin-scoped (/api/admin/invoices, see api/invoices.py).
export function listAdminInvoices(): Promise<Invoice[]> {
  return apiGet<Invoice[]>("/api/admin/invoices");
}

// customer_id and memo travel as QUERY PARAMS, line_items as a bare JSON
// array body -- matches api/invoices.py's create() route signature
// exactly (customer_id: UUID and memo: str | None are plain scalar
// params, which FastAPI treats as query params by default; line_items:
// list[LineItemInput] is the one body-eligible param, so it's the WHOLE
// body, not wrapped in an envelope object). Getting this shape wrong
// doesn't 422 with an obviously-wrong-looking error -- it 422s with
// "field required: customer_id" even though the caller DID send a
// customer_id, just in the wrong place, which is exactly what happened
// before this was ever wired up to a real form (see AdminInvoices.tsx's
// former TODO).
export function createInvoice(
  customerId: string,
  lineItems: CreateInvoiceLineItem[],
  memo?: string,
): Promise<{ id: string }> {
  const params = new URLSearchParams({ customer_id: customerId });
  if (memo) params.set("memo", memo);
  return apiPost<{ id: string }>(`/api/admin/invoices?${params.toString()}`, lineItems);
}

// Fetches the PDF as a real Blob first (via apiGetBlob, see that
// function's own doc comment for why a plain <a href> can't surface a
// server-side failure) and only THEN opens it in a new tab -- preserves
// the original design's actual goal (the browser's own PDF viewer
// handles print/save/zoom, not a forced Save-As) while fixing the real
// bug: a plain <a href="/api/.../pdf" target="_blank"> against a failing
// endpoint just opened a blank/raw-JSON tab with no usable feedback
// ("the PDF option doesn't work"). Throws with the server's real error
// detail on failure (e.g. "failed to generate invoice PDF" when latexmk
// isn't installed in the serving environment -- see docs/deployment.md's
// health-check section), which callers should catch and show inline
// instead of ever letting a broken tab open at all.
export async function openInvoicePdf(path: string): Promise<void> {
  const blob = await apiGetBlob(path);
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener,noreferrer");
  // Revoked after a delay, not immediately -- the opened tab needs the
  // URL to stay valid long enough to actually load/render the PDF
  // (revoking synchronously right after window.open can race the new
  // tab's own fetch of the blob: URL and break the download). 60s is
  // comfortably past any real PDF load time on this connection while
  // still bounding the leak per download instead of leaving it for the
  // lifetime of the tab (a customer/admin downloading many invoice PDFs
  // in one session previously accumulated one live blob URL each,
  // unbounded, for as long as this tab stayed open).
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export function sendInvoice(id: string): Promise<Invoice> {
  return apiPost<Invoice>(`/api/admin/invoices/${id}/send`);
}

export function voidInvoice(id: string): Promise<Invoice> {
  return apiPost<Invoice>(`/api/admin/invoices/${id}/void`);
}

// Zelle/in-person/PayPal-sent-directly/other -- an admin recording a
// payment that happened outside this system, not a real payment-provider
// call. See backend's domain/invoices/service.py record_manual_payment.
export type ManualPaymentMethod = "paypal" | "zelle" | "in_person" | "other";

export interface ManualPaymentInput {
  method: ManualPaymentMethod;
  amount: string;
  note?: string;
}

export function recordManualPayment(
  invoiceId: string,
  payment: ManualPaymentInput,
): Promise<{ id: string }> {
  return apiPost<{ id: string }>(
    `/api/admin/invoices/${invoiceId}/payments/manual`,
    payment,
  );
}

export interface PaymentMethodsAvailability {
  stripe: boolean;
  paypal: boolean;
  // null when unconfigured (see backend AppConfig.zelle_handle's own doc
  // comment) -- Pay.tsx only shows a Zelle option once this is a real
  // value.
  zelle_handle: string | null;
}

export function getPaymentMethods(): Promise<PaymentMethodsAvailability> {
  return apiGet<PaymentMethodsAvailability>("/api/invoices/payment-methods");
}

// Real multipart/form-data upload -- matches api/invoices_public.py's
// upload_payment_proof route, same pattern as api/budget.ts's
// uploadBudgetEvidence. "An optional place to put a screenshot or
// something to show that they sent something."
export function uploadPaymentProof(
  invoiceId: string,
  file: File,
): Promise<{ id: string }> {
  const formData = new FormData();
  formData.append("file", file);
  return apiPost<{ id: string }>(`/api/invoices/${invoiceId}/payment-proof`, formData);
}

export interface PaymentProof {
  id: string;
  content_type: string;
  created_at: string;
}

export function listPaymentProof(invoiceId: string): Promise<PaymentProof[]> {
  return apiGet<PaymentProof[]>(`/api/admin/invoices/${invoiceId}/payment-proof`);
}

export function paymentProofFileUrl(invoiceId: string, proofId: string): string {
  return `/api/admin/invoices/${invoiceId}/payment-proof/${proofId}/file`;
}

// Deliberately snake_case fields here (order_id/approval_url), not this
// file's usual camelCase -- these are the LITERAL JSON keys
// api/invoices_public.py's /pay/paypal route actually returns; getting
// this wrong wouldn't just be a display mismatch (like some of this
// file's older camelCase interfaces vs the mocked data they were written
// against), it would silently read undefined for a real field.
export interface PaypalOrderResponse {
  order_id: string;
  approval_url: string | null;
}

export function payInvoiceViaPaypal(id: string): Promise<PaypalOrderResponse> {
  return apiPost<PaypalOrderResponse>(`/api/invoices/${id}/pay/paypal`);
}

export function capturePaypalPayment(
  id: string,
  orderId: string,
): Promise<{ status: string }> {
  // order_id (not orderId) in the body -- must match
  // api/invoices_public.py's PayPalCaptureRequest field name exactly.
  return apiPost<{ status: string }>(`/api/invoices/${id}/pay/paypal/capture`, {
    order_id: orderId,
  });
}

export interface RefundInput {
  payment_id: string;
  // Omit for "refund the payment's full remaining balance" -- matches
  // domain/invoices/refunds.py::RefundInput's own amount=None meaning.
  amount?: string;
  reason?: string;
  // Stable per refund *action* (generated once when the admin initiates
  // the refund, not regenerated on retry) -- lets the backend dedupe a
  // resubmitted request instead of minting a fresh provider idempotency
  // key each time. See domain/invoices/refunds.py::RefundInput.
  client_request_id: string;
}

// Method-aware server-side (Stripe/PayPal API call, or pure bookkeeping
// for a manual payment) -- see domain/invoices/refunds.py::refund_payment.
// payment_id travels both in the URL and the body; the backend 422s if
// they don't match (api/invoices.py's refund_invoice_payment).
export function refundPayment(
  invoiceId: string,
  paymentId: string,
  input: RefundInput,
): Promise<{ id: string }> {
  return apiPost<{ id: string }>(
    `/api/admin/invoices/${invoiceId}/payments/${paymentId}/refund`,
    { ...input, payment_id: paymentId },
  );
}

// Matches domain/invoices/stats.py::InvoiceStatusBreakdown.
export interface InvoiceStatusBreakdown {
  count: number;
  amount_total: string;
}

// Matches domain/invoices/stats.py::PaymentMethodBreakdown.
export interface PaymentMethodStatsBreakdown {
  count: number;
  amount: string;
}

// Matches domain/invoices/stats.py::DisputeBreakdown.
export interface DisputeBreakdown {
  needs_response: number;
  under_review: number;
  won: number;
  lost: number;
}

// Matches domain/invoices/stats.py::InvoiceStats -- every field is
// computed fresh from invoices/payments/refunds on each call, no cached
// counters to drift out of sync (see that module's own doc comment).
export interface InvoiceStats {
  by_status: Record<Invoice["status"], InvoiceStatusBreakdown>;
  total_collected: string;
  total_refunded: string;
  net_collected: string;
  outstanding: string;
  by_payment_method: Record<string, PaymentMethodStatsBreakdown>;
  open_disputes: number;
  disputes: DisputeBreakdown;
}

export function getInvoiceStats(): Promise<InvoiceStats> {
  // Registered before GET /{invoice_id} on the backend -- see
  // api/invoices.py's get_stats doc comment.
  return apiGet<InvoiceStats>("/api/admin/invoices/stats");
}
