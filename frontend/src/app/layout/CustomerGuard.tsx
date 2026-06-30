import type { ReactNode } from "react";
import { useMe } from "../../hooks/useMe";

export function CustomerGuard({ children }: { children: ReactNode }) {
  const { data, isLoading, isError } = useMe();

  if (isLoading) return <p>Loading...</p>;
  if (isError || !data) return null; // client.ts already redirected on 401
  if (data.role !== "customer") return <p>Forbidden.</p>;

  return <>{children}</>;
}
