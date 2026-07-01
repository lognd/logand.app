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
