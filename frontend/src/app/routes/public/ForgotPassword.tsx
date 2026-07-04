import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { requestPasswordReset } from "../../../api/auth";
import { RateLimitedError } from "../../../api/client";
import { formatRetryAt } from "../../../lib/time";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// Every field is a real labeled input per docs/design/09's accessibility bar.
export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const mutation = useMutation({
    mutationFn: () => requestPasswordReset(email),
  });

  return (
    <main className="mx-auto w-full max-w-md px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Reset your password</h1>
      {mutation.isSuccess ? (
        // The backend always returns this same message regardless of
        // whether the email matched a real account -- showing anything
        // that varied on that (e.g. "no account found") would turn this
        // form into an account-enumeration oracle. See
        // domain/auth/password_reset.py's own doc comment.
        <p className="text-base text-fg-primary">
          If an account exists for that email, a password reset link has been
          sent. Check your inbox (and spam folder) for a message from us.
        </p>
      ) : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
        >
          <div>
            <label htmlFor="email" className={LABEL_CLASS}>
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className={INPUT_CLASS}
            />
          </div>

          <button type="submit" disabled={mutation.isPending} className={BUTTON_CLASS}>
            {mutation.isPending ? "Sending..." : "Send reset link"}
          </button>

          {mutation.isError && (
            <p role="alert" className="text-base text-accent-red">
              {mutation.error instanceof RateLimitedError
                ? `Too many attempts. Try again at ${formatRetryAt(
                    mutation.error.retryAfterSeconds,
                  )}.`
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
