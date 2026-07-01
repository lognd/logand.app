import { apiGet } from "./client";

// Admin-only lookup list (api/admin_users.py) -- id+email only, used to
// populate the "bill who?" picker on the admin create-invoice form. Not a
// general user-management endpoint; there is no create/edit/delete-user
// surface at all.
export interface Customer {
  id: string;
  email: string;
}

export function listCustomers(): Promise<Customer[]> {
  return apiGet<Customer[]>("/api/admin/customers");
}
