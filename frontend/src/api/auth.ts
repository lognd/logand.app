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

// Redeems a 'verify' token minted by register() (docs/design/16). 204 on
// success; a 400 with code "AuthError.EmailVerificationTokenInvalid" means
// the token is invalid, expired, or already used.
export function verifyEmail(token: string): Promise<void> {
  return apiPost<void>("/api/auth/verify-email", { token });
}

// ALWAYS resolves 202 regardless of whether the email has a pending
// registration -- same no-oracle contract as requestPasswordReset above
// (see domain/auth/email_verification.py::request_verification_resend's
// own doc comment). Callers must show the identical confirmation message
// on every resolution, never branch UI on this having "found" anything.
export function resendVerification(email: string): Promise<{ status: string }> {
  return apiPost<{ status: string }>("/api/auth/resend-verification", { email });
}

// Just enough to preview an invoice-claim link before a password is set
// (docs/design/16's ClaimPreviewInvoice) -- amount_total is a decimal
// string (already quantized to the invoice's currency server-side), never
// a number, so it round-trips through JSON without float rounding.
export interface ClaimPreviewInvoice {
  id: string;
  status: string;
  amount_total: string;
  currency: string;
  due_date: string | null;
}

export interface ClaimPreview {
  email: string;
  invoices: ClaimPreviewInvoice[];
}

// Read-only -- never redeems the token (see get_claim_preview's own doc
// comment). Safe to call repeatedly (e.g. on remount) without burning the
// one-time claim token.
export function getClaimPreview(token: string): Promise<ClaimPreview> {
  return apiGet<ClaimPreview>(`/api/auth/claim?token=${encodeURIComponent(token)}`);
}

// Redeems a 'claim' token: sets password AND marks the row's email
// verified in one step (docs/design/16) -- clicking the link is itself
// proof of inbox control, so there is no second verify round-trip after
// this succeeds.
export function confirmClaim(token: string, password: string): Promise<void> {
  return apiPost<void>("/api/auth/claim", { token, password });
}
