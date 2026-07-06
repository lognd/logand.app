import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { addTaxRule, listTaxRules, type TaxRule } from "../../../api/tax";
import { ApiError } from "../../../api/client";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

const TAX_TYPES = ["sales", "use", "import_duty"] as const;

function formatPercent(rate: string): string {
  const value = Number(rate);
  if (Number.isNaN(value)) return rate;
  // Trims trailing zeros (0.070 -> 7%) without losing precision for odd
  // rates (0.0725 -> 7.25%).
  return `${(value * 100).toFixed(4).replace(/\.?0+$/, "")}%`;
}

function RulesTable({ rules }: { rules: TaxRule[] }) {
  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full min-w-[800px] text-base text-fg-primary">
        <thead>
          <tr className="border-b border-border text-left">
            <th className="p-2">Jurisdiction</th>
            <th className="p-2">Type</th>
            <th className="p-2">Category</th>
            <th className="p-2">Rate</th>
            <th className="p-2">Source</th>
            <th className="p-2">Citation</th>
          </tr>
        </thead>
        <tbody>
          {rules.map((r) => (
            <tr key={r.id} className="border-b border-border">
              <td className="p-2 font-mono">{r.jurisdiction}</td>
              <td className="p-2">{r.tax_type}</td>
              <td className="p-2 font-mono">{r.category}</td>
              <td className="p-2">{formatPercent(r.rate)}</td>
              <td className="p-2">{r.source}</td>
              <td className="p-2">
                {r.citation_url ? (
                  <a
                    href={r.citation_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-accent-aqua underline underline-offset-2 hover:text-accent-orange"
                  >
                    source
                  </a>
                ) : (
                  "--"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Rate is entered as a whole-number percent here ("7" -> 0.07 sent to the
// backend) -- easier for an admin to type/check against a state's published
// rate sheet than a bare fraction like "0.07".
function AddRuleForm() {
  const queryClient = useQueryClient();
  const [jurisdiction, setJurisdiction] = useState("");
  const [taxType, setTaxType] = useState<(typeof TAX_TYPES)[number]>("sales");
  const [category, setCategory] = useState("*");
  const [percent, setPercent] = useState("");
  const [source, setSource] = useState("");
  const [citationUrl, setCitationUrl] = useState("");

  const addMutation = useMutation({
    mutationFn: () =>
      addTaxRule({
        jurisdiction,
        tax_type: taxType,
        category: category || "*",
        rate: String(Number(percent) / 100),
        source,
        citation_url: citationUrl,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "tax", "rules"] });
      setJurisdiction("");
      setPercent("");
      setSource("");
      setCitationUrl("");
      setCategory("*");
    },
  });

  const errorMessage =
    addMutation.error instanceof ApiError
      ? addMutation.error.message
      : addMutation.isError
        ? "Could not save the rate."
        : null;

  return (
    <form
      className="mt-6 flex flex-col gap-4 rounded border border-border p-4"
      onSubmit={(e) => {
        e.preventDefault();
        addMutation.mutate();
      }}
    >
      <h2 className="text-xl text-fg-primary">Add rate</h2>

      <div className="flex flex-wrap gap-4">
        <label className="flex flex-col">
          <span className={LABEL_CLASS}>Jurisdiction (e.g. US-TN)</span>
          <input
            type="text"
            required
            value={jurisdiction}
            onChange={(e) => setJurisdiction(e.target.value)}
            className={INPUT_CLASS}
          />
        </label>

        <label className="flex flex-col">
          <span className={LABEL_CLASS}>Tax type</span>
          <select
            value={taxType}
            onChange={(e) => setTaxType(e.target.value as (typeof TAX_TYPES)[number])}
            className={INPUT_CLASS}
          >
            {TAX_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col">
          <span className={LABEL_CLASS}>Category</span>
          <input
            type="text"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className={INPUT_CLASS}
          />
        </label>

        <label className="flex flex-col">
          <span className={LABEL_CLASS}>Rate (percent, e.g. 7 for 7%)</span>
          <input
            type="number"
            step="any"
            min="0"
            required
            value={percent}
            onChange={(e) => setPercent(e.target.value)}
            className={INPUT_CLASS}
          />
        </label>
      </div>

      <label className="flex flex-col">
        <span className={LABEL_CLASS}>Source</span>
        <input
          type="text"
          required
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className={INPUT_CLASS}
          placeholder="e.g. TN DOR 2026"
        />
      </label>

      <label className="flex flex-col">
        <span className={LABEL_CLASS}>
          Government source URL (.gov/.mil/.us or an allowlisted state site)
        </span>
        <input
          type="url"
          required
          value={citationUrl}
          onChange={(e) => setCitationUrl(e.target.value)}
          className={INPUT_CLASS}
          placeholder="https://www.tn.gov/revenue.html"
        />
      </label>

      {errorMessage && (
        <p role="alert" className="text-base text-accent-red">
          {errorMessage}
        </p>
      )}

      <div>
        <button type="submit" disabled={addMutation.isPending} className={BUTTON_CLASS}>
          Add rate
        </button>
      </div>
    </form>
  );
}

// Admin surface for the tax_rules knowledge base (docs/design/16-sales-tax
// .md): rates are always entered and cited by a human, with a government
// source URL required on every row -- Claude only classifies items into a
// category, it never sets or approves the rate.
export function AdminTaxRates() {
  const rulesQuery = useQuery({
    queryKey: ["admin", "tax", "rules"],
    queryFn: listTaxRules,
  });

  const rules = rulesQuery.data ?? [];

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8">
      <h1 className="mb-2 text-2xl text-fg-primary">Tax rates (admin)</h1>
      <p className="mb-6 text-base text-fg-muted">
        Enter and cite the sales/use tax rates you collect. Every rate needs a
        government-source citation -- Claude only classifies items, it never
        sets the rate.
      </p>

      {rulesQuery.isLoading && <p className="text-base text-fg-muted">Loading...</p>}
      {rulesQuery.isError && (
        <p role="alert" className="text-base text-accent-red">
          Failed to load tax rates.
        </p>
      )}

      {!rulesQuery.isLoading && !rulesQuery.isError && rules.length === 0 && (
        <p className="text-base text-fg-muted">No rates entered yet.</p>
      )}

      {rules.length > 0 && <RulesTable rules={rules} />}

      <AddRuleForm />
    </main>
  );
}
