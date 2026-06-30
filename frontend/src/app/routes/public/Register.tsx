import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { register } from "../../../api/auth";
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
export function Register() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => register(email, password),
    onSuccess: async () => {
      // Registration logs the user in immediately, same as login -- see
      // Login.tsx's identical post-success handling.
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      navigate("/");
    },
  });

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;

  return (
    <main className="mx-auto w-full max-w-md px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Register</h1>
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
            Registration failed. That email may already be in use, or try again
            shortly if you've made several attempts (rate limited).
          </p>
        )}
      </form>
      <p className="mt-4 text-base text-fg-primary">
        Already have an account?{" "}
        <a href="/login" className="text-accent-aqua underline underline-offset-2">
          Log in
        </a>
      </p>
    </main>
  );
}
