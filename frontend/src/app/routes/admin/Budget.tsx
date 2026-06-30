import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createBudgetEntry, listBudgetEntries } from "../../../api/budget";

// TODO(logan): evidence upload form is still missing -- correction flow
// (editing an entry once evidence is attached) is server-side only for now,
// see docs/design/05-budget.md. This wires up list + create.
export function AdminBudget() {
  const queryClient = useQueryClient();
  const {
    data: entries,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["admin", "budget"],
    queryFn: listBudgetEntries,
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

  return (
    <main>
      <h1>Budget (admin)</h1>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          createMutation.mutate({
            amount,
            category,
            occurredOn,
            vendor: null,
            memo: null,
          });
        }}
      >
        <label htmlFor="amount">Amount</label>
        <input
          id="amount"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          required
        />
        <label htmlFor="category">Category</label>
        <input
          id="category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          required
        />
        <label htmlFor="occurredOn">Date</label>
        <input
          id="occurredOn"
          type="date"
          value={occurredOn}
          onChange={(e) => setOccurredOn(e.target.value)}
          required
        />
        <button type="submit" disabled={createMutation.isPending}>
          Add entry
        </button>
      </form>

      {isLoading && <p>Loading...</p>}
      {isError && <p role="alert">Failed to load budget entries.</p>}
      {entries && (
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Category</th>
              <th>Vendor</th>
              <th>Amount</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr key={entry.id}>
                <td>{entry.occurredOn}</td>
                <td>{entry.category}</td>
                <td>{entry.vendor ?? "-"}</td>
                <td>{entry.amount}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
