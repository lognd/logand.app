import { apiDelete, apiGet, apiPatch, apiPost } from "./client";

// Generic reflection-based admin table browser/editor
// (api/admin_data.py, domain/admin_data/service.py) -- "absolute power"
// over real business tables per the user's own explicit scope decision,
// with every write going through the same before/after-audited path as
// every other risky admin action on this site.

export interface ColumnInfo {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: boolean;
  editable: boolean;
}

export interface AuditLogEntry {
  id: string;
  admin_id: string | null;
  action: string;
  target_table: string | null;
  target_id: string | null;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  created_at: string;
}

export function listTables(): Promise<string[]> {
  return apiGet<string[]>("/api/admin/data/tables");
}

export function getTableSchema(tableName: string): Promise<ColumnInfo[]> {
  return apiGet<ColumnInfo[]>(`/api/admin/data/tables/${tableName}/schema`);
}

export function listRows(
  tableName: string,
  limit = 50,
  offset = 0,
): Promise<Record<string, unknown>[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return apiGet<Record<string, unknown>[]>(
    `/api/admin/data/tables/${tableName}/rows?${params.toString()}`,
  );
}

export function getRow(
  tableName: string,
  rowId: string,
): Promise<Record<string, unknown>> {
  return apiGet<Record<string, unknown>>(
    `/api/admin/data/tables/${tableName}/rows/${rowId}`,
  );
}

export function insertRow(
  tableName: string,
  values: Record<string, unknown>,
): Promise<{ change_id: string }> {
  return apiPost<{ change_id: string }>(`/api/admin/data/tables/${tableName}/rows`, {
    values,
  });
}

export function updateRow(
  tableName: string,
  rowId: string,
  changes: Record<string, unknown>,
): Promise<{ change_id: string }> {
  return apiPatch<{ change_id: string }>(
    `/api/admin/data/tables/${tableName}/rows/${rowId}`,
    { changes },
  );
}

export function deleteRow(
  tableName: string,
  rowId: string,
): Promise<{ change_id: string }> {
  return apiDelete<{ change_id: string }>(
    `/api/admin/data/tables/${tableName}/rows/${rowId}`,
  );
}

export function listChanges(limit = 50, offset = 0): Promise<AuditLogEntry[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  return apiGet<AuditLogEntry[]>(`/api/admin/data/changes?${params.toString()}`);
}

export function revertChange(changeId: string): Promise<{ change_id: string }> {
  return apiPost<{ change_id: string }>(`/api/admin/data/changes/${changeId}/revert`);
}
