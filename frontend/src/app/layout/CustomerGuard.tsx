import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { UnauthenticatedError } from "../../api/client";
import { useMe } from "../../hooks/useMe";

export function CustomerGuard({ children }: { children: ReactNode }) {
  const { data, isLoading, isError, error } = useMe();

  if (isLoading) return <p className="p-4 text-base text-fg-muted">Loading...</p>;
  // See AdminGuard's identical NOTE -- client.ts never redirects on a
  // GET /api/me 401, so the guard itself must send a logged-out/expired-
  // session visitor to /login rather than rendering a permanent blank
  // page. Only a genuine UnauthenticatedError counts as "logged out";
  // any other error (network blip, 500) gets a retry state instead of
  // bouncing an already-authenticated customer to /login.
  if (isError && error instanceof UnauthenticatedError) {
    return <Navigate to="/login" replace />;
  }
  if (isError || !data) {
    return <p className="p-4 text-base text-accent-red">Something went wrong loading your account. Please try again.</p>;
  }
  if (data.role !== "customer")
    return <p className="p-4 text-base text-accent-red">Forbidden.</p>;

  return <>{children}</>;
}
