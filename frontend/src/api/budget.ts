import { apiGet, apiPost } from "./client";

// TODO(logan): replace with generated type once backend/openapi.json exists.
export interface BudgetEntry {
  id: string;
  amount: string;
  category: string;
  vendor: string | null;
  memo: string | null;
  occurredOn: string;
}

export function listBudgetEntries(): Promise<BudgetEntry[]> {
  return apiGet<BudgetEntry[]>("/api/admin/budget");
}

export function createBudgetEntry(
  entry: Omit<BudgetEntry, "id">,
): Promise<BudgetEntry> {
  return apiPost<BudgetEntry>("/api/admin/budget", entry);
}
