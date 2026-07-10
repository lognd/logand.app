import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { register } from "../../../api/auth";
import { RateLimitedError } from "../../../api/client";
import { formatRetryAt } from "../../../lib/time";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// Mirrors backend/src/logand_backend/api/auth.py's RegisterRequest password
// bounds (8-128 chars) -- client-side check is just a fast-fail UX nicety,
// the backend is the actual source of truth and re-validates regardless.
const MIN_PASSWORD_LENGTH = 8;

// Every field is a real labeled input per docs/design/09's accessibility bar
// (no icon-only controls, 16px+ text, visible labels, 44px+ tap targets).
// Self-registration always creates a customer-role account -- there is no
// role field here, by design (see docs/design/02 and the backend's
// register() domain function: role is hardcoded server-side, never taken
// from the request).
//
// docs/design/17: registration no longer logs the visitor in -- POST
// /api/auth/register now returns 202 and mints a "verify" token emailed to
// the address, and the resulting account cannot log in until that link is
// clicked (email_verified_at IS NULL blocks login with a distinct error,
// see Login.tsx). There is no session to invalidate/redirect on here any
// more; success just means "check your email."
export function Register() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const mutation = useMutation({
    mutationFn: () => register(email, password),
  });

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;

  return (
    <main className="mx-auto w-full max-w-md px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Register</h1>
      {mutation.isSuccess ? (
        <p className="text-base text-fg-primary">
          Check your email for a link to verify your account before logging
          in.
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

          <div>
            <label htmlFor="password" className={LABEL_CLASS}>
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={MIN_PASSWORD_LENGTH}
              aria-describedby="password-hint"
              className={INPUT_CLASS}
            />
            <p id="password-hint" className="mt-1 text-base text-fg-muted">
              At least {MIN_PASSWORD_LENGTH} characters.
            </p>
          </div>

          <button
            type="submit"
            disabled={mutation.isPending || tooShort}
            className={BUTTON_CLASS}
          >
            {mutation.isPending ? "Creating account..." : "Create account"}
          </button>

          {mutation.isError && (
            <p role="alert" className="text-base text-accent-red">
              {mutation.error instanceof RateLimitedError
                ? `Too many attempts. Try again at ${formatRetryAt(
                    mutation.error.retryAfterSeconds,
                  )}.`
                : "Registration failed. That email may already be in use."}
            </p>
          )}
        </form>
      )}
      <p className="mt-4 text-base text-fg-primary">
        Already have an account?{" "}
        <a href="/login" className="text-accent-aqua underline underline-offset-2">
          Log in
        </a>
      </p>
    </main>
  );
}
