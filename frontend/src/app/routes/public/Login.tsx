import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { login } from "../../../api/auth";

// Real form skeleton -- styling deferred to docs/design/09's pass, but
// every field is a real labeled input per that doc's accessibility bar
// (no icon-only controls, 16px+ text, visible labels).
export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const mutation = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: () => {
      window.location.assign("/");
    },
  });

  return (
    <main>
      <h1>Log in</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        <button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Logging in..." : "Log in"}
        </button>

        {mutation.isError && (
          <p role="alert">Login failed. Check your email and password.</p>
        )}
      </form>
    </main>
  );
}
