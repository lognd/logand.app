import { apiGet, apiPost, apiPut } from "./client";

// Admin-only lookup list (api/admin_users.py) -- id+email only, used to
// populate the "bill who?" picker on the admin create-invoice form. Not a
// general user-management endpoint; there is no create/edit/delete-user
// surface at all.
export interface Customer {
  id: string;
  email: string;
}

// `q`, when given, filters to emails containing it (case-insensitive
// substring) -- see api/admin_users.py's list_customers doc comment.
// Always capped at 50 rows server-side.
export function listCustomers(q?: string): Promise<Customer[]> {
  const params = q ? `?${new URLSearchParams({ q }).toString()}` : "";
  return apiGet<Customer[]>(`/api/admin/customers${params}`);
}

export interface CustomerDetail {
  id: string;
  email: string;
  role: string;
  emails_opted_out: boolean;
  disabled_at: string | null;
  created_at: string;
  // Destination address for tax sourcing (docs/design/16-sales-tax.md
  // Phase 6) -- matches api/admin_users.py's _customer_detail field names
  // exactly. Any/all may be null if never set.
  address_line1: string | null;
  address_city: string | null;
  address_state: string | null;
  address_postal_code: string | null;
  address_country: string | null;
}

export function getCustomerDetail(userId: string): Promise<CustomerDetail> {
  return apiGet<CustomerDetail>(`/api/admin/customers/${userId}`);
}

export interface CustomerAddressInput {
  address_line1?: string | null;
  address_city?: string | null;
  address_state?: string | null;
  address_postal_code?: string | null;
  address_country?: string | null;
}

// Replaces the whole address (backend api/admin_users.py's AddressInput --
// omitted/null fields are cleared, not left as-is), used by the tax engine's
// destination-jurisdiction lookup.
export function updateCustomerAddress(
  userId: string,
  body: CustomerAddressInput,
): Promise<CustomerDetail> {
  return apiPut<CustomerDetail>(`/api/admin/customers/${userId}/address`, body);
}

export function deactivateCustomer(userId: string): Promise<{ status: string }> {
  return apiPost<{ status: string }>(`/api/admin/customers/${userId}/deactivate`);
}

export function reactivateCustomer(userId: string): Promise<{ status: string }> {
  return apiPost<{ status: string }>(`/api/admin/customers/${userId}/reactivate`);
}

export function resetCustomerPassword(
  userId: string,
  newPassword: string,
): Promise<{ status: string }> {
  return apiPost<{ status: string }>(`/api/admin/customers/${userId}/reset-password`, {
    new_password: newPassword,
  });
}
