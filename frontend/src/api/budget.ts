import { apiGet, apiPost } from "./client";

// snake_case fields (occurred_on/corrects_entry_id), matching
// api/budget.py's list_entries response exactly -- found during a real
// end-to-end verification pass that this file had never actually been
// checked against the real backend: create() sent a JSON body when the
// real route (api/budget.py's create, all scalar params) only accepts
// query params, and the MSW mock had independently drifted to accept a
// body too, so nothing ever caught the mismatch. Same class of bug as
// invoices.ts's own camelCase/query-vs-body history -- see that file's
// doc comment.
export interface BudgetEntry {
  id: string;
  amount: string;
  category: string;
  vendor: string | null;
  memo: string | null;
  occurred_on: string;
  corrects_entry_id: string | null;
}

export function listBudgetEntries(params?: {
  category?: string;
  dateFrom?: string;
  dateTo?: string;
}): Promise<BudgetEntry[]> {
  const query = new URLSearchParams();
  if (params?.category) query.set("category", params.category);
  if (params?.dateFrom) query.set("date_from", params.dateFrom);
  if (params?.dateTo) query.set("date_to", params.dateTo);
  const qs = query.toString();
  return apiGet<BudgetEntry[]>(`/api/admin/budget${qs ? `?${qs}` : ""}`);
}

export interface CreateBudgetEntryInput {
  amount: string;
  category: string;
  occurredOn: string;
  vendor?: string;
  memo?: string;
}

// amount/category/occurred_on/vendor/memo travel as QUERY PARAMS, no
// body at all -- matches api/budget.py's create() route exactly (every
// param is a plain scalar, so FastAPI treats all of them as query
// params; there's no body-eligible pydantic model in the signature).
export function createBudgetEntry(
  entry: CreateBudgetEntryInput,
): Promise<{ id: string }> {
  const params = new URLSearchParams({
    amount: entry.amount,
    category: entry.category,
    occurred_on: entry.occurredOn,
  });
  if (entry.vendor) params.set("vendor", entry.vendor);
  if (entry.memo) params.set("memo", entry.memo);
  return apiPost<{ id: string }>(`/api/admin/budget?${params.toString()}`);
}

// Real multipart/form-data upload -- matches api/budget.py's
// upload_evidence route (a `file: UploadFile` param, allowlisted to
// application/pdf|image/png|image/jpeg).
export function uploadBudgetEvidence(
  entryId: string,
  file: File,
): Promise<{ id: string }> {
  const formData = new FormData();
  formData.append("file", file);
  return apiPost<{ id: string }>(`/api/admin/budget/${entryId}/evidence`, formData);
}
