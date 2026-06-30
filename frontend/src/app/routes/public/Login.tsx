import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { login } from "../../../api/auth";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

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
            Login failed. Check your email and password.
          </p>
        )}
      </form>
    </main>
  );
}
