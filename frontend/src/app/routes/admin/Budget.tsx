import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createBudgetEntry,
  listBudgetEntries,
  uploadBudgetEvidence,
} from "../../../api/budget";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// Correction flow (editing an entry once evidence is attached) is
// server-side only for now, see docs/design/05-budget.md -- this wires
// up list + create + evidence upload.
export function AdminBudget() {
  const queryClient = useQueryClient();
  const {
    data: entries,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["admin", "budget"],
    queryFn: () => listBudgetEntries(),
  });

  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("");
  const [occurredOn, setOccurredOn] = useState("");

  const createMutation = useMutation({
    mutationFn: createBudgetEntry,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "budget"] });
      setAmount("");
      setCategory("");
      setOccurredOn("");
    },
  });

  // Tracks which entry's file input is currently uploading, so only
  // that one row shows a pending state (not the whole page).
  const [uploadingEntryId, setUploadingEntryId] = useState<string | null>(null);
  const evidenceMutation = useMutation({
    mutationFn: ({ entryId, file }: { entryId: string; file: File }) =>
      uploadBudgetEvidence(entryId, file),
    onMutate: ({ entryId }) => setUploadingEntryId(entryId),
    onSettled: () => setUploadingEntryId(null),
  });

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Budget (admin)</h1>

      <form
        className="mb-8 flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          createMutation.mutate({ amount, category, occurredOn });
        }}
      >
        <div>
          <label htmlFor="amount" className={LABEL_CLASS}>
            Amount
          </label>
          <input
            id="amount"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            required
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label htmlFor="category" className={LABEL_CLASS}>
            Category
          </label>
          <input
            id="category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            required
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label htmlFor="occurredOn" className={LABEL_CLASS}>
            Date
          </label>
          <input
            id="occurredOn"
            type="date"
            value={occurredOn}
            onChange={(e) => setOccurredOn(e.target.value)}
            required
            className={INPUT_CLASS}
          />
        </div>
        <button
          type="submit"
          disabled={createMutation.isPending}
          className={BUTTON_CLASS}
        >
          Add entry
        </button>
      </form>
      {createMutation.isError && (
        <p role="alert" className="mb-4 text-base text-accent-red">
          Failed to add entry.
        </p>
      )}

      {isLoading && <p className="text-base text-fg-muted">Loading...</p>}
      {isError && (
        <p role="alert" className="text-base text-accent-red">
          Failed to load budget entries.
        </p>
      )}
      {entries && (
        <div className="w-full overflow-x-auto">
          <table className="w-full min-w-[560px] text-base text-fg-primary">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="p-2">Date</th>
                <th className="p-2">Category</th>
                <th className="p-2">Vendor</th>
                <th className="p-2">Amount</th>
                <th className="p-2">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id} className="border-b border-border">
                  <td className="p-2">{entry.occurred_on}</td>
                  <td className="p-2">{entry.category}</td>
                  <td className="p-2">{entry.vendor ?? "-"}</td>
                  <td className="p-2">{entry.amount}</td>
                  <td className="p-2">
                    <label
                      className={LABEL_CLASS}
                      htmlFor={`evidence-${entry.id}`}
                      aria-label={`Upload evidence for entry on ${entry.occurred_on}`}
                    >
                      <input
                        id={`evidence-${entry.id}`}
                        type="file"
                        accept="application/pdf,image/png,image/jpeg"
                        disabled={uploadingEntryId === entry.id}
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (!file) return;
                          evidenceMutation.mutate({ entryId: entry.id, file });
                          e.target.value = "";
                        }}
                        className="text-base text-fg-primary"
                      />
                      {uploadingEntryId === entry.id && (
                        <span className="ml-2 text-fg-muted">Uploading...</span>
                      )}
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {evidenceMutation.isError && (
        <p role="alert" className="mt-4 text-base text-accent-red">
          Failed to upload evidence.
        </p>
      )}
    </main>
  );
}
