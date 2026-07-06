import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  confirmTaxClassification,
  listTaxClassifications,
  overrideTaxClassification,
  type TaxClassification,
} from "../../../api/tax";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// Inline "edit this row" form for overriding a classification -- kept as a
// small local component (not a modal) so the admin can see the row they're
// correcting right above the form, same "no modals for routine edits"
// pattern as Customers.tsx's inline reset-password panel.
function OverrideForm({
  classification,
  onDone,
}: {
  classification: TaxClassification;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [category, setCategory] = useState(classification.category);
  const [taxable, setTaxable] = useState(classification.taxable);
  const [htsCode, setHtsCode] = useState(classification.hts_code ?? "");

  const overrideMutation = useMutation({
    mutationFn: () =>
      overrideTaxClassification(classification.normalized_key, {
        category,
        taxable,
        hts_code: htsCode || null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "tax", "classifications"] });
      onDone();
    },
  });

  return (
    <div className="w-full rounded border border-border p-3">
      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col text-sm text-fg-muted">
          Category
          <input
            type="text"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className={INPUT_CLASS}
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-fg-muted">
          <input
            type="checkbox"
            checked={taxable}
            onChange={(e) => setTaxable(e.target.checked)}
            className="h-5 w-5"
          />
          Taxable
        </label>
        <label className="flex flex-col text-sm text-fg-muted">
          HTS code
          <input
            type="text"
            value={htsCode}
            onChange={(e) => setHtsCode(e.target.value)}
            className={INPUT_CLASS}
          />
        </label>
      </div>
      {overrideMutation.isError && (
        <p role="alert" className="mt-2 text-base text-accent-red">
          Could not save the override.
        </p>
      )}
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          disabled={!category || overrideMutation.isPending}
          onClick={() => overrideMutation.mutate()}
          className={BUTTON_CLASS}
        >
          Save override
        </button>
        <button type="button" onClick={onDone} className={BUTTON_CLASS}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function ClassificationRow({ classification }: { classification: TaxClassification }) {
  const queryClient = useQueryClient();
  const [overriding, setOverriding] = useState(false);

  const confirmMutation = useMutation({
    mutationFn: () => confirmTaxClassification(classification.normalized_key),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "tax", "classifications"] });
    },
  });

  return (
    <>
      <tr className="border-b border-border">
        <td className="p-2">{classification.description}</td>
        <td className="p-2 font-mono">{classification.category}</td>
        <td className="p-2">{classification.taxable ? "Yes" : "No"}</td>
        <td className="p-2 font-mono">{classification.hts_code ?? "--"}</td>
        <td className="p-2">{classification.status}</td>
        <td className="p-2">{classification.source}</td>
        <td className="p-2 text-fg-muted">{classification.rationale ?? "--"}</td>
        <td className="p-2">
          {classification.status === "pending" && (
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={confirmMutation.isPending}
                onClick={() => confirmMutation.mutate()}
                className={BUTTON_CLASS}
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => setOverriding((v) => !v)}
                className={BUTTON_CLASS}
              >
                Override
              </button>
            </div>
          )}
          {confirmMutation.isError && (
            <p role="alert" className="mt-1 text-sm text-accent-red">
              Could not confirm.
            </p>
          )}
        </td>
      </tr>
      {overriding && (
        <tr>
          <td colSpan={8} className="p-2">
            <OverrideForm
              classification={classification}
              onDone={() => setOverriding(false)}
            />
          </td>
        </tr>
      )}
    </>
  );
}

// Admin review queue for the do-as-we-go item tax classifier: every new
// normalized item key the tax engine has never seen gets an automatic
// guess (category/taxable/hts_code) that sits "pending" until an admin
// confirms it as-is or overrides it -- see docs/design/16-sales-tax.md.
export function AdminTaxClassifications() {
  const [statusFilter, setStatusFilter] = useState<"pending" | "all">("pending");

  const classificationsQuery = useQuery({
    queryKey: ["admin", "tax", "classifications", statusFilter],
    queryFn: () =>
      listTaxClassifications(statusFilter === "pending" ? "pending" : undefined),
  });

  const classifications = classificationsQuery.data ?? [];

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8">
      <h1 className="mb-2 text-2xl text-fg-primary">Tax classifications (admin)</h1>
      <p className="mb-6 text-base text-fg-muted">
        Review how the tax engine has classified line items it has not seen
        before. Confirm a guess as-is, or override the category, taxability,
        or HTS code.
      </p>

      <div className="mb-6">
        <label htmlFor="status-filter" className={LABEL_CLASS}>
          Show
        </label>
        <select
          id="status-filter"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as "pending" | "all")}
          className={INPUT_CLASS}
        >
          <option value="pending">Pending review</option>
          <option value="all">All</option>
        </select>
      </div>

      {classificationsQuery.isLoading && (
        <p className="text-base text-fg-muted">Loading...</p>
      )}
      {classificationsQuery.isError && (
        <p role="alert" className="text-base text-accent-red">
          Failed to load tax classifications.
        </p>
      )}

      {!classificationsQuery.isLoading &&
        !classificationsQuery.isError &&
        classifications.length === 0 && (
          <p className="text-base text-fg-muted">No classifications need review.</p>
        )}

      {classifications.length > 0 && (
        <div className="w-full overflow-x-auto">
          <table className="w-full min-w-[900px] text-base text-fg-primary">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="p-2">Description</th>
                <th className="p-2">Category</th>
                <th className="p-2">Taxable</th>
                <th className="p-2">HTS code</th>
                <th className="p-2">Status</th>
                <th className="p-2">Source</th>
                <th className="p-2">Rationale</th>
                <th className="p-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {classifications.map((c) => (
                <ClassificationRow key={c.id} classification={c} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
