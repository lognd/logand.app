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

// ALWAYS resolves (never a 401/404-shaped rejection for "no such
// account") -- the backend deliberately returns the identical response
// regardless of whether the email matches a real account, so this
// function's callers only ever need to handle the generic-success and
// rate-limited (429) cases, never an "email not found" one that would
// otherwise tempt a caller into displaying it and reintroducing the
// account-enumeration leak the backend just closed.
export function requestPasswordReset(email: string): Promise<{ status: string }> {
  return apiPost<{ status: string }>("/api/auth/password-reset/request", { email });
}

export function confirmPasswordReset(
  token: string,
  newPassword: string,
): Promise<{ status: string }> {
  return apiPost<{ status: string }>("/api/auth/password-reset/confirm", {
    token,
    new_password: newPassword,
  });
}
