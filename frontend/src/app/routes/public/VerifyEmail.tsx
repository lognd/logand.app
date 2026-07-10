import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { resendVerification, verifyEmail } from "../../../api/auth";
import { ApiError, RateLimitedError } from "../../../api/client";
import { formatRetryAt } from "../../../lib/time";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// Reached from the real link mailer.py's email-verification-requested send
// (?token=<raw_token>), same shape as ResetPassword.tsx. There is no
// session at this point, by design -- verifying an email happens before
// any login is possible (see docs/design/16).
export function VerifyEmail() {
  const [searchParams, setSearchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const attempted = useRef(false);

  const verifyMutation = useMutation({
    mutationFn: () => verifyEmail(token),
  });

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true;
    verifyMutation.mutate(undefined, {
      // Once the token has been submitted, drop it from the visible URL
      // (docs/design/16 security notes) -- it is single-use and there is
      // no reason for it to keep sitting in the address bar / browser
      // history after this point.
      onSettled: () => {
        setSearchParams({}, { replace: true });
      },
    });
    // verifyMutation is a fresh object identity every render; only token
    // should re-trigger this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  // Login.tsx's "resend verification email" link (shown on the distinct
  // EmailNotVerified error) pre-fills this via ?email= so the visitor
  // doesn't have to retype an address they just typed into the login
  // form -- purely a convenience default, never trusted as anything else.
  const [resendEmail, setResendEmail] = useState(searchParams.get("email") ?? "");
  const resendMutation = useMutation({
    mutationFn: () => resendVerification(resendEmail),
  });

  // Gated on attempted.current, not just !token: the effect above clears
  // ?token= from the URL as soon as the verify attempt settles, so by the
  // time a result renders, token is already "" again -- checking token
  // alone would flip back to the missing-token branch right after a real
  // attempt and hide the success/failure state it just produced.
  if (!token && !attempted.current) {
    return (
      <main className="mx-auto w-full max-w-md px-4 py-8">
        <h1 className="mb-6 text-2xl text-fg-primary">Verify your email</h1>
        <p role="alert" className="text-base text-accent-red">
          This link is missing its verification token.
        </p>
        <ResendForm
          resendEmail={resendEmail}
          setResendEmail={setResendEmail}
          resendMutation={resendMutation}
        />
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-md px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Verify your email</h1>

      {verifyMutation.isPending && (
        <p className="text-base text-fg-muted">Verifying...</p>
      )}

      {verifyMutation.isSuccess && (
        <p className="text-base text-fg-primary">
          Your email has been verified. You can now{" "}
          <a href="/login" className="text-accent-aqua underline underline-offset-2">
            log in
          </a>
          .
        </p>
      )}

      {verifyMutation.isError && (
        <>
          <p role="alert" className="text-base text-accent-red">
            {verifyMutation.error instanceof RateLimitedError
              ? `Too many attempts. Try again at ${formatRetryAt(
                  verifyMutation.error.retryAfterSeconds,
                )}.`
              : verifyMutation.error instanceof ApiError
                ? verifyMutation.error.message
                : "This link is invalid, has expired, or was already used."}
          </p>
          <ResendForm
            resendEmail={resendEmail}
            setResendEmail={setResendEmail}
            resendMutation={resendMutation}
          />
        </>
      )}
    </main>
  );
}

interface ResendFormProps {
  resendEmail: string;
  setResendEmail: (value: string) => void;
  resendMutation: ReturnType<typeof useMutation<{ status: string }, Error, void>>;
}

// Shared by both the missing-token and invalid-token branches above. The
// backend's /resend-verification ALWAYS returns the same 202 body
// regardless of whether the address has a pending registration -- showing
// anything that varied on that would turn this form into an
// account-enumeration oracle (mirrors ForgotPassword.tsx's identical
// reasoning for password resets).
function ResendForm({ resendEmail, setResendEmail, resendMutation }: ResendFormProps) {
  return (
    <div className="mt-6">
      <h2 className="mb-2 text-lg text-fg-primary">Resend verification email</h2>
      {resendMutation.isSuccess ? (
        <p className="text-base text-fg-primary">
          If a pending registration exists for that email, a verification link
          has been sent. Check your inbox (and spam folder).
        </p>
      ) : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            resendMutation.mutate();
          }}
        >
          <div>
            <label htmlFor="resend-email" className={LABEL_CLASS}>
              Email
            </label>
            <input
              id="resend-email"
              type="email"
              autoComplete="username"
              value={resendEmail}
              onChange={(e) => setResendEmail(e.target.value)}
              required
              className={INPUT_CLASS}
            />
          </div>

          <button
            type="submit"
            disabled={resendMutation.isPending}
            className={BUTTON_CLASS}
          >
            {resendMutation.isPending ? "Sending..." : "Resend verification email"}
          </button>

          {resendMutation.isError && (
            <p role="alert" className="text-base text-accent-red">
              {resendMutation.error instanceof RateLimitedError
                ? `Too many attempts. Try again at ${formatRetryAt(
                    resendMutation.error.retryAfterSeconds,
                  )}.`
                : "Something went wrong. Please try again shortly."}
            </p>
          )}
        </form>
      )}
    </div>
  );
}
