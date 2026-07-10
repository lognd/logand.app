import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { register } from "../../../api/auth";
import { RateLimitedError } from "../../../api/client";
import { formatRetryAt } from "../../../lib/time";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// Every field is a real labeled input per docs/design/09's accessibility bar
// (no icon-only controls, 16px+ text, visible labels, 44px+ tap targets).
// Self-registration always creates a customer-role account -- there is no
// role field here, by design (see docs/design/02 and the backend's
// register() domain function: role is hardcoded server-side, never taken
// from the request).
//
// FINDINGS H1: registration is now EMAIL-ONLY. It sets no password and does
// not log the visitor in -- POST /api/auth/register returns 202 and mints a
// "verify" token emailed to the address. The password is chosen only when
// that link is clicked (see VerifyEmail.tsx), so an attacker registering
// someone else's address can never plant a credential a victim's click would
// activate. Success here just means "check your email."
export function Register() {
  const [email, setEmail] = useState("");
  const mutation = useMutation({
    mutationFn: () => register(email),
  });

  return (
    <main className="mx-auto w-full max-w-md px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Register</h1>
      {mutation.isSuccess ? (
        <p className="text-base text-fg-primary">
          Check your email for a link to verify your account and set your
          password before logging in.
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

          <button
            type="submit"
            disabled={mutation.isPending}
            className={BUTTON_CLASS}
          >
            {mutation.isPending ? "Sending..." : "Create account"}
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
