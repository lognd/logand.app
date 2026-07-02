import { apiGet, apiPost } from "./client";

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
}

export function getCustomerDetail(userId: string): Promise<CustomerDetail> {
  return apiGet<CustomerDetail>(`/api/admin/customers/${userId}`);
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
