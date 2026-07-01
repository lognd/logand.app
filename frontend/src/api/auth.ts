import { apiGet, apiPost } from "./client";

// TODO(logan): replace with generated type once backend/openapi.json exists
// (see Makefile `types` target).
// Deliberately matches api/health.py's real MeResponse fields exactly
// (user_id/role only, no email) -- an earlier version of this interface
// declared id/email fields the real backend never actually returns
// (found while auditing for real-vs-mocked-backend field mismatches; see
// PaypalOrderResponse's identical concern in api/invoices.ts). Nothing in
// this app's real code reads either field, but a wrong type here would
// have silently type-checked fine while returning undefined at runtime
// against the real backend.
export interface Me {
  user_id: string;
  role: "admin" | "customer";
}

export function fetchMe(): Promise<Me> {
  return apiGet<Me>("/api/me");
}

export function login(email: string, password: string): Promise<{ status: string }> {
  return apiPost<{ status: string }>("/api/auth/login", { email, password });
}

export function logout(): Promise<{ status: string }> {
  return apiPost<{ status: string }>("/api/auth/logout");
}

export function register(
  email: string,
  password: string,
): Promise<{ status: string }> {
  return apiPost<{ status: string }>("/api/auth/register", { email, password });
}
