import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { login } from "../../../api/auth";
import { ApiError, RateLimitedError } from "../../../api/client";
import { formatRetryAt } from "../../../lib/time";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// The backend already returns a deliberately generic message here
// ("email or password is incorrect") that never distinguishes "no such
// account" from "wrong password" -- safe to show verbatim, not a
// security regression, since that's the whole design of
// AuthError.InvalidCredentials (see domain/auth/service.py::login's own
// doc comment). This is only a fallback for the rare case the backend
// didn't send a detail body at all (a raw network failure, a non-JSON
// 401 from something in front of the app).
const GENERIC_LOGIN_ERROR = "Login failed. Check your email and password.";

// docs/design/16: unlike InvalidCredentials, EmailNotVerified is safe to
// disclose distinctly -- reaching it already requires knowing the correct
// password, so it does not participate in login's account-existence
// oracle (see backend/src/logand_backend/errors.py's own comment on
// AuthError.EmailNotVerified). Matched on the stable `code`, never on
// message prose.
const EMAIL_NOT_VERIFIED_CODE = "AuthError.EmailNotVerified";

function isEmailNotVerified(error: unknown): boolean {
  return error instanceof ApiError && error.code === EMAIL_NOT_VERIFIED_CODE;
}

function loginErrorMessage(error: unknown): string {
  if (error instanceof RateLimitedError) {
    return `Too many attempts. Try again at ${formatRetryAt(error.retryAfterSeconds)}.`;
  }
  if (error instanceof ApiError && error.message) {
    return error.message;
  }
  return GENERIC_LOGIN_ERROR;
}

// Every field is a real labeled input per docs/design/09's accessibility bar
// (no icon-only controls, 16px+ text, visible labels, 44px+ tap targets).
export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: async () => {
      // SPA navigation, not window.location.assign -- a full reload here
      // was needlessly jarring (flash of unstyled content, the whole bundle
      // re-fetching). The ["me"] query result is now stale from the
      // pre-login (401) state, so explicitly invalidate it rather than
      // relying on a reload to implicitly refetch.
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      navigate("/");
    },
  });

  return (
    <main className="mx-auto w-full max-w-md px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Log in</h1>
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

        <div>
          <label htmlFor="password" className={LABEL_CLASS}>
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className={INPUT_CLASS}
          />
        </div>

        <button type="submit" disabled={mutation.isPending} className={BUTTON_CLASS}>
          {mutation.isPending ? "Logging in..." : "Log in"}
        </button>

        {mutation.isError && (
          <p role="alert" className="text-base text-accent-red">
            {loginErrorMessage(mutation.error)}
            {isEmailNotVerified(mutation.error) && (
              <>
                {" "}
                <a
                  href={`/verify-email?email=${encodeURIComponent(email)}`}
                  className="text-accent-aqua underline underline-offset-2"
                >
                  Resend verification email
                </a>
              </>
            )}
          </p>
        )}
      </form>
      <p className="mt-4 text-base text-fg-primary">
        <a
          href="/forgot-password"
          className="text-accent-aqua underline underline-offset-2"
        >
          Forgot your password?
        </a>
      </p>
      <p className="mt-2 text-base text-fg-primary">
        Don&apos;t have an account?{" "}
        <a href="/register" className="text-accent-aqua underline underline-offset-2">
          Register
        </a>
      </p>
    </main>
  );
}
