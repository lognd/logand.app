import { apiGet } from "./client";

// Read-only admin surface over api/admin_logs.py -- "I can retrieve logs
// from backend." No mutation endpoints here by design (log files
// themselves are never edited or deleted through the UI, only pruned
// server-side by logging/retention.py on its own schedule).
export interface LogFileInfo {
  name: string;
  size_bytes: number;
  modified_at: number;
}

export function listLogFiles(): Promise<LogFileInfo[]> {
  return apiGet<LogFileInfo[]>("/api/admin/logs/files");
}

export function tailLiveLog(lines = 200): Promise<string[]> {
  return apiGet<string[]>(`/api/admin/logs/tail?lines=${lines}`);
}

export function logFileDownloadUrl(name: string): string {
  return `/api/admin/logs/files/${encodeURIComponent(name)}`;
}
