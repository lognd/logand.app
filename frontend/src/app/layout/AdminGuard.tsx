import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { UnauthenticatedError } from "../../api/client";
import { useMe } from "../../hooks/useMe";

export function AdminGuard({ children }: { children: ReactNode }) {
  const { data, isLoading, isError, error } = useMe();

  if (isLoading) return <p className="p-4 text-base text-fg-muted">Loading...</p>;
  // NOTE: client.ts's own 401 handler deliberately does NOT redirect for
  // GET /api/me (see that module's own comment -- redirecting on it
  // caused a hard-reload loop, since every page's nav mounts useMe()).
  // That means the guard itself is the only thing that can send a
  // logged-out/expired-session visitor to /login when they land directly
  // on a protected route -- without this, isError left the guard
  // rendering `null`, a permanent blank page under the Shell with no way
  // out.
  //
  // Only redirect for a genuine UnauthenticatedError (the 401 case) --
  // any OTHER error (a network blip, a 500) is not "not logged in," and
  // treating it as one bounced an already-authenticated admin to /login
  // on a transient failure. Show a retry state instead.
  if (isError && error instanceof UnauthenticatedError) {
    return <Navigate to="/login" replace />;
  }
  if (isError || !data) {
    return <p className="p-4 text-base text-accent-red">Something went wrong loading your account. Please try again.</p>;
  }
  if (data.role !== "admin")
    return <p className="p-4 text-base text-accent-red">Forbidden.</p>;

  return <>{children}</>;
}
