import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { confirmClaim, getClaimPreview } from "../../../api/auth";
import { ApiError, RateLimitedError } from "../../../api/client";
import { formatRetryAt } from "../../../lib/time";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// Mirrors backend/src/logand_backend/api/auth.py's ClaimConfirmInput
// password bounds (8-128 chars) -- same fast-fail-UX-nicety-not-
// source-of-truth reasoning as Register.tsx's identical constant.
const MIN_PASSWORD_LENGTH = 8;

// Reached from the real invoice-sent email's claim link
// (?token=<raw_token>) when the recipient is a "contact" row that has
// never had a password (docs/design/16). No auth is possible yet -- the
// token itself is the credential -- so this preview-then-set-password
// flow has no session at any point.
export function Claim() {
  const [searchParams, setSearchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const navigate = useNavigate();

  const previewQuery = useQuery({
    queryKey: ["claim-preview", token],
    queryFn: () => getClaimPreview(token),
    enabled: !!token,
    retry: false,
  });

  const [password, setPassword] = useState("");
  const confirmMutation = useMutation({
    mutationFn: () => confirmClaim(token, password),
    onSuccess: () => {
      // The claim token is single-use and only ever needed once; drop it
      // from the visible URL now that it has been redeemed (docs/design/16
      // security notes), then send the visitor to log in with their new
      // password.
      setSearchParams({}, { replace: true });
      navigate("/login");
    },
  });

  // Deliberately does NOT scrub the token from the URL on a failed
  // preview (unlike the success path above) -- doing so would change
  // this query's queryKey out from under it (["claim-preview", token]),
  // flipping `enabled` to false and erasing the very error message this
  // render is trying to show. A dead/expired token sitting in history
  // after a failed preview is a much smaller concern than that.

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;

  if (!token) {
    return (
      <main className="mx-auto w-full max-w-md px-4 py-8">
        <h1 className="mb-6 text-2xl text-fg-primary">Claim your invoices</h1>
        <p role="alert" className="text-base text-accent-red">
          This link is missing its claim token.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-md px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Claim your invoices</h1>

      {previewQuery.isLoading && (
        <p className="text-base text-fg-muted">Loading...</p>
      )}

      {previewQuery.isError && (
        <p role="alert" className="text-base text-accent-red">
          {previewQuery.error instanceof ApiError
            ? previewQuery.error.message
            : "This link is invalid, has expired, or was already used."}
        </p>
      )}

      {previewQuery.data && !confirmMutation.isSuccess && (
        <>
          <p className="mb-4 text-base text-fg-primary">
            Set a password for <strong>{previewQuery.data.email}</strong> to
            access the invoice(s) below.
          </p>

          <ul className="mb-6 flex flex-col gap-2">
            {previewQuery.data.invoices.map((invoice) => (
              <li
                key={invoice.id}
                className="rounded border border-border p-3 text-base text-fg-primary"
              >
                <div>
                  {invoice.amount_total} {invoice.currency.toUpperCase()}
                </div>
                <div className="text-fg-muted">Status: {invoice.status}</div>
                <div className="text-fg-muted">
                  Due: {invoice.due_date ?? "-"}
                </div>
              </li>
            ))}
          </ul>

          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (tooShort) return;
              confirmMutation.mutate();
            }}
          >
            <div>
              <label htmlFor="claim-password" className={LABEL_CLASS}>
                Password
              </label>
              <input
                id="claim-password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={MIN_PASSWORD_LENGTH}
                aria-describedby="claim-password-hint"
                className={INPUT_CLASS}
              />
              <p id="claim-password-hint" className="mt-1 text-base text-fg-muted">
                At least {MIN_PASSWORD_LENGTH} characters.
              </p>
            </div>

            <button
              type="submit"
              disabled={confirmMutation.isPending || tooShort}
              className={BUTTON_CLASS}
            >
              {confirmMutation.isPending ? "Setting password..." : "Set password"}
            </button>

            {confirmMutation.isError && (
              <p role="alert" className="text-base text-accent-red">
                {confirmMutation.error instanceof RateLimitedError
                  ? `Too many attempts. Try again at ${formatRetryAt(
                      confirmMutation.error.retryAfterSeconds,
                    )}.`
                  : confirmMutation.error instanceof ApiError
                    ? confirmMutation.error.message
                    : "Something went wrong. Please try again shortly."}
              </p>
            )}
          </form>
        </>
      )}
    </main>
  );
}
