import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { confirmPasswordReset } from "../../../api/auth";
import { ApiError, RateLimitedError } from "../../../api/client";
import { formatRetryAt } from "../../../lib/time";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// Mirrors backend/src/logand_backend/api/auth.py's PasswordResetConfirmInput
// bounds (8-128 chars) -- same fast-fail-UX-nicety-not-source-of-truth
// reasoning as Register.tsx's identical constant.
const MIN_PASSWORD_LENGTH = 8;

// Every field is a real labeled input per docs/design/09's accessibility bar.
// Reached from the real link mailer.py's password_reset_requested email
// sends (?token=<raw_token>) -- there is no session at this point, by
// design (see api/app.py's CSRF-exempt-paths comment on this route).
export function ResetPassword() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [newPassword, setNewPassword] = useState("");
  const mutation = useMutation({
    mutationFn: () => confirmPasswordReset(token, newPassword),
  });

  const tooShort = newPassword.length > 0 && newPassword.length < MIN_PASSWORD_LENGTH;

  if (!token) {
    return (
      <main className="mx-auto w-full max-w-md px-4 py-8">
        <h1 className="mb-6 text-2xl text-fg-primary">Reset your password</h1>
        <p role="alert" className="text-base text-accent-red">
          This link is missing its reset token. Request a new one below.
        </p>
        <p className="mt-4 text-base text-fg-primary">
          <a
            href="/forgot-password"
            className="text-accent-aqua underline underline-offset-2"
          >
            Request a new reset link
          </a>
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-md px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Reset your password</h1>
      {mutation.isSuccess ? (
        <p className="text-base text-fg-primary">
          Your password has been reset. You can now{" "}
          <a href="/login" className="text-accent-aqua underline underline-offset-2">
            log in
          </a>{" "}
          with your new password.
        </p>
      ) : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (tooShort) return;
            mutation.mutate();
          }}
        >
          <div>
            <label htmlFor="new-password" className={LABEL_CLASS}>
              New password
            </label>
            <input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={MIN_PASSWORD_LENGTH}
              aria-describedby="new-password-hint"
              className={INPUT_CLASS}
            />
            <p id="new-password-hint" className="mt-1 text-base text-fg-muted">
              At least {MIN_PASSWORD_LENGTH} characters.
            </p>
          </div>

          <button
            type="submit"
            disabled={mutation.isPending || tooShort}
            className={BUTTON_CLASS}
          >
            {mutation.isPending ? "Resetting..." : "Reset password"}
          </button>

          {mutation.isError && (
            <p role="alert" className="text-base text-accent-red">
              {mutation.error instanceof RateLimitedError
                ? `Too many attempts. Try again at ${formatRetryAt(
                    mutation.error.retryAfterSeconds,
                  )}.`
                : mutation.error instanceof ApiError
                  ? mutation.error.message
                  : "Something went wrong. Please try again shortly."}
            </p>
          )}
        </form>
      )}
      <p className="mt-4 text-base text-fg-primary">
        <a href="/login" className="text-accent-aqua underline underline-offset-2">
          Back to log in
        </a>
      </p>
    </main>
  );
}
