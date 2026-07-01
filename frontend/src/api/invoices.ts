import { apiGet, apiPost } from "./client";

// TODO(logan): replace with generated type once backend/openapi.json exists.
export interface Invoice {
  id: string;
  status: "draft" | "sent" | "paid" | "overdue" | "void";
  amountTotal: string;
  currency: string;
  memo: string | null;
  dueDate: string | null;
}

// Customer-scoped (/api/invoices, see api/invoices_public.py).
export function listInvoices(): Promise<Invoice[]> {
  return apiGet<Invoice[]>("/api/invoices");
}

export function getInvoice(id: string): Promise<Invoice> {
  return apiGet<Invoice>(`/api/invoices/${id}`);
}

export function payInvoice(id: string): Promise<{ clientSecret: string }> {
  return apiPost<{ clientSecret: string }>(`/api/invoices/${id}/pay`);
}

// Admin-scoped (/api/admin/invoices, see api/invoices.py).
export function listAdminInvoices(): Promise<Invoice[]> {
  return apiGet<Invoice[]>("/api/admin/invoices");
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
