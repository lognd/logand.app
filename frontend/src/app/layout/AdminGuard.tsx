import type { ReactNode } from "react";
import { useMe } from "../../hooks/useMe";

// TODO(logan): GET /api/me doesn't exist on the backend yet -- this will
// 401 against any real server until that endpoint lands. The 401 path in
// api/client.ts already redirects to /login, so this guard degrades safely.
export function AdminGuard({ children }: { children: ReactNode }) {
  const { data, isLoading, isError } = useMe();

  if (isLoading) return <p>Loading...</p>;
  if (isError || !data) return null; // client.ts already redirected on 401
  if (data.role !== "admin") return <p>Forbidden.</p>;

  return <>{children}</>;
}
