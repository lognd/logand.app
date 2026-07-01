import { apiGet, apiPost } from "./client";

// A raw line item request body, matching api/invoices.py's LineItemInput
// pydantic model field-for-field -- description/quantity/unit_price, not
// this file's usual mix of camelCase mistakes fixed elsewhere. Kept
// separate from the response-shaped MockInvoiceLineItem-adjacent types
// since this is what gets SENT, not what comes back.
export interface CreateInvoiceLineItem {
  description: string;
  quantity: string;
  unit_price: string;
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
  status: "draft" | "sent" | "paid" | "overdue" | "void";
  amount_total: string;
  currency: string;
  memo: string | null;
  due_date: string | null;
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
}

export function getPaymentMethods(): Promise<PaymentMethodsAvailability> {
  return apiGet<PaymentMethodsAvailability>("/api/invoices/payment-methods");
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
