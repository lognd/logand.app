import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { resendVerification, verifyEmail } from "../../../api/auth";
import { ApiError, RateLimitedError } from "../../../api/client";
import { useNoReferrer } from "../../layout/useNoReferrer";
import { formatRetryAt } from "../../../lib/time";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// Mirrors backend/src/logand_backend/api/auth.py's VerifyEmailInput password
// bounds (8-128 chars) -- same fast-fail-UX-nicety-not-source-of-truth
// reasoning as Register.tsx/Claim.tsx's identical constant.
const MIN_PASSWORD_LENGTH = 8;

// Reached from the real link mailer.py's email-verification-requested send
// (?token=<raw_token>). FINDINGS H1: verifying is now a "choose your
// password" step -- it POSTs {token, password} and sets the password AND
// marks the email verified in one transaction (mirroring Claim.tsx exactly,
// only the endpoint differs). There is no session at this point, by design
// -- verifying happens before any login is possible (docs/design/17). On an
// invalid/expired token, the resend affordance is kept.
export function VerifyEmail() {
  useNoReferrer();
  const [searchParams, setSearchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const navigate = useNavigate();

  const [password, setPassword] = useState("");
  const verifyMutation = useMutation({
    mutationFn: () => verifyEmail(token, password),
    onSuccess: () => {
      // The verify token is single-use and only ever needed once; drop it
      // from the visible URL now that it has been redeemed (docs/design/17
      // security notes), then send the visitor to log in with their new
      // password.
      setSearchParams({}, { replace: true });
      navigate("/login");
    },
  });

  // Login.tsx's "resend verification email" link (shown on the distinct
  // EmailNotVerified error) pre-fills this via ?email= so the visitor
  // doesn't have to retype an address -- purely a convenience default.
  const [resendEmail, setResendEmail] = useState(searchParams.get("email") ?? "");
  const resendMutation = useMutation({
    mutationFn: () => resendVerification(resendEmail),
  });

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;

  if (!token) {
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

      <p className="mb-4 text-base text-fg-primary">
        Set a password to finish verifying your account.
      </p>

      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (tooShort) return;
          verifyMutation.mutate();
        }}
      >
        <div>
          <label htmlFor="verify-password" className={LABEL_CLASS}>
            Password
          </label>
          <input
            id="verify-password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={MIN_PASSWORD_LENGTH}
            aria-describedby="verify-password-hint"
            className={INPUT_CLASS}
          />
          <p id="verify-password-hint" className="mt-1 text-base text-fg-muted">
            At least {MIN_PASSWORD_LENGTH} characters.
          </p>
        </div>

        <button
          type="submit"
          disabled={verifyMutation.isPending || tooShort}
          className={BUTTON_CLASS}
        >
          {verifyMutation.isPending ? "Verifying..." : "Verify and set password"}
        </button>
      </form>

      {verifyMutation.isError && (
        <>
          <p role="alert" className="mt-4 text-base text-accent-red">
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
