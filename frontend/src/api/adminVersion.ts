import { apiGet } from "./client";

// "what versions of EVERYTHING" -- api/admin_version.py's read-only
// admin surface. Never cached long (no server-side change notifications
// for a dependency bump), a fresh fetch each visit is fine at this
// endpoint's real traffic volume.
export interface VersionInfo {
  app_version: string;
  git_commit: string;
  python_version: string;
  platform: string;
  dependencies: Record<string, string>;
}

export function getVersionInfo(): Promise<VersionInfo> {
  return apiGet<VersionInfo>("/api/admin/version");
}
