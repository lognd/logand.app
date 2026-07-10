import { apiGet, apiPost, apiPut } from "./client";

// docs/design/17-contact-users-and-email-verification.md's three account
// states, derived server-side (never trust a client-computed version of
// this since it comes from password_hash, which the client never sees):
// - "contact": admin invoiced this email, no account exists, cannot log in.
// - "unverified": registered, has not proven inbox control.
// - "active": fully usable account.
export type AccountState = "contact" | "unverified" | "active";

// Admin-only lookup list (api/admin_users.py) -- id+email+account_state,
// used to populate the "bill who?" picker on the admin create-invoice form
// and to let an admin chasing an unpaid invoice see at a glance whether the
// person has ever claimed it. Not a general user-management endpoint;
// there is no create/edit/delete-user surface at all.
export interface Customer {
  id: string;
  email: string;
  account_state: AccountState;
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
  account_state: AccountState;
  // Timestamp the customer proved inbox control (docs/design/17); null
  // for "contact" and "unverified" states. Not sensitive -- unlike
  // password_hash, which the backend never serializes at all.
  email_verified_at: string | null;
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
