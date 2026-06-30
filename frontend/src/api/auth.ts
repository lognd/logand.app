import { apiGet } from "./client";

// TODO(logan): replace with generated type once backend/openapi.json exists
// (see Makefile `types` target).
export interface Me {
  id: string;
  email: string;
  role: "admin" | "customer";
}

export function fetchMe(): Promise<Me> {
  return apiGet<Me>("/api/me");
}
