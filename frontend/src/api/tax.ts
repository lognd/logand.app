import { apiGet, apiPost } from "./client";

// One do-as-we-go item tax classification row, matching the backend's
// admin tax classifications endpoint (api/tax_classifications.py --
// see docs/design/16-sales-tax.md). `status` starts "pending" whenever
// the classifier engine has never seen this normalized item key before;
// an admin either confirms the model's guess as-is or overrides it with
// a corrected category/taxable/hts_code, both of which move it out of
// the pending review queue.
export interface TaxClassification {
  id: string;
  normalized_key: string;
  description: string;
  category: string;
  taxable: boolean;
  hts_code: string | null;
  status: "pending" | "confirmed" | "overridden";
  source: string;
  model: string | null;
  rationale: string | null;
  confirmed_at: string | null;
  updated_at: string;
}

// Omit `status` to fetch every classification regardless of review state.
export function listTaxClassifications(
  status?: "pending" | "confirmed" | "overridden",
): Promise<TaxClassification[]> {
  const params = status ? `?${new URLSearchParams({ status }).toString()}` : "";
  return apiGet<TaxClassification[]>(`/api/admin/tax/classifications${params}`);
}

// normalized_key may contain spaces/punctuation -- always URL-encoded here
// so callers never have to remember to do it themselves.
export function confirmTaxClassification(
  normalizedKey: string,
): Promise<TaxClassification> {
  return apiPost<TaxClassification>(
    `/api/admin/tax/classifications/${encodeURIComponent(normalizedKey)}/confirm`,
  );
}

export interface TaxClassificationOverrideInput {
  category: string;
  taxable: boolean;
  hts_code?: string | null;
}

export function overrideTaxClassification(
  normalizedKey: string,
  body: TaxClassificationOverrideInput,
): Promise<TaxClassification> {
  return apiPost<TaxClassification>(
    `/api/admin/tax/classifications/${encodeURIComponent(normalizedKey)}/override`,
    body,
  );
}

// Stripe's own recorded tax figures for the same range as the deterministic
// tax report -- a cross-check, not a source of truth; only covers
// Stripe-processed payments (see api/invoices.py's stripe-reconcile route).
export interface StripeTaxReconcile {
  total_tax_collected: string;
  by_jurisdiction: Record<string, string>;
  transaction_count: number;
}

export function getStripeReconcile(
  fromDate: string,
  toDate: string,
): Promise<StripeTaxReconcile> {
  const params = new URLSearchParams({ from_date: fromDate, to_date: toDate });
  return apiGet<StripeTaxReconcile>(
    `/api/admin/tax/stripe-reconcile?${params.toString()}`,
  );
}

// One rate row in the tax_rules knowledge base (docs/design/16-sales-tax.md)
// -- admin-entered and government-cited. Claude only ever classifies items
// into a category; it never sets or approves the rate itself, so every row
// here traces back to a real citation_url an admin typed in.
export interface TaxRule {
  id: string;
  jurisdiction: string;
  tax_type: string;
  category: string;
  rate: string;
  source: string;
  citation_url: string | null;
  effective_from: string;
}

export function listTaxRules(): Promise<TaxRule[]> {
  return apiGet<TaxRule[]>("/api/admin/tax/rules");
}

export interface TaxRuleInput {
  jurisdiction: string;
  tax_type: string;
  category?: string;
  rate: string;
  source: string;
  citation_url: string;
}

export function addTaxRule(input: TaxRuleInput): Promise<TaxRule> {
  return apiPost<TaxRule>("/api/admin/tax/rules", input);
}
