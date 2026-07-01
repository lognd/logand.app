import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type Invoice,
  type ManualPaymentMethod,
  listAdminInvoices,
  recordManualPayment,
  sendInvoice,
  voidInvoice,
} from "../../../api/invoices";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

const MANUAL_PAYMENT_METHODS: { value: ManualPaymentMethod; label: string }[] = [
  { value: "zelle", label: "Zelle" },
  { value: "paypal", label: "PayPal (sent directly)" },
  { value: "in_person", label: "In person" },
  { value: "other", label: "Other" },
];

// A visitor paying a customer's invoice via Stripe (the real /pay flow)
// never touches this -- this is exclusively for an admin recording a
// payment that already happened some other way (a Zelle transfer, cash
// handed over, a PayPal payment sent customer-to-admin directly), so the
// invoice's paid/unpaid state stays accurate even when the money moved
// outside Stripe entirely. See backend's domain/invoices/service.py
// record_manual_payment doc comment for why there's no provider API call
// here at all.
function ManualPaymentForm({
  invoice,
  onRecorded,
}: {
  invoice: Invoice;
  onRecorded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState<ManualPaymentMethod>("zelle");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");

  const mutation = useMutation({
    mutationFn: () => recordManualPayment(invoice.id, { method, amount, note: note || undefined }),
    onSuccess: () => {
      onRecorded();
      setOpen(false);
      setAmount("");
      setNote("");
    },
  });

  if (invoice.status !== "sent" && invoice.status !== "overdue") return null;

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Record a manual payment for invoice ${invoice.id}`}
        className={BUTTON_CLASS}
      >
        Record payment
      </button>
    );
  }

  return (
    <form
      className="flex w-full flex-col gap-2 rounded border border-border p-3 sm:w-auto sm:flex-row sm:items-end"
      onSubmit={(e) => {
        e.preventDefault();
        if (!amount) return;
        mutation.mutate();
      }}
    >
      <div>
        <label htmlFor={`method-${invoice.id}`} className={LABEL_CLASS}>
          Method
        </label>
        <select
          id={`method-${invoice.id}`}
          value={method}
          onChange={(e) => setMethod(e.target.value as ManualPaymentMethod)}
          className={INPUT_CLASS}
        >
          {MANUAL_PAYMENT_METHODS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor={`amount-${invoice.id}`} className={LABEL_CLASS}>
          Amount
        </label>
        <input
          id={`amount-${invoice.id}`}
          type="number"
          step="0.01"
          min="0"
          required
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className={INPUT_CLASS}
        />
      </div>
      <div>
        <label htmlFor={`note-${invoice.id}`} className={LABEL_CLASS}>
          Note (optional)
        </label>
        <input
          id={`note-${invoice.id}`}
          type="text"
          placeholder="e.g. Zelle confirmation #1234"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          className={INPUT_CLASS}
        />
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={mutation.isPending}
          className={BUTTON_CLASS}
        >
          {mutation.isPending ? "Recording..." : "Save"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className={BUTTON_CLASS}>
          Cancel
        </button>
      </div>
      {mutation.isError && (
        <p role="alert" className="text-base text-accent-red">
          Could not record payment. Check the amount and try again.
        </p>
      )}
    </form>
  );
}

// TODO(logan): create-invoice form (React Hook Form + zod) is still missing --
// this wires up list/send/void against real endpoints first since that's the
// higher-value data-flow path to prove out.
export function AdminInvoices() {
  const queryClient = useQueryClient();
  const {
    data: invoices,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["admin", "invoices"],
    queryFn: listAdminInvoices,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["admin", "invoices"] });
  const sendMutation = useMutation({ mutationFn: sendInvoice, onSuccess: invalidate });
  const voidMutation = useMutation({ mutationFn: voidInvoice, onSuccess: invalidate });

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Invoices (admin)</h1>
      {isLoading && <p className="text-base text-fg-muted">Loading...</p>}
      {isError && (
        <p role="alert" className="text-base text-accent-red">
          Failed to load invoices.
        </p>
      )}
      {invoices && (
        // Horizontal scroll wrapper, not a fixed-width table, so this stays
        // usable on a 375px-wide mobile viewport instead of overflowing or
        // forcing a tiny unreadable font.
        <div className="w-full overflow-x-auto">
          <table className="w-full min-w-[640px] text-base text-fg-primary">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="p-2">Status</th>
                <th className="p-2">Amount</th>
                <th className="p-2">Due</th>
                <th className="p-2">Memo</th>
                <th className="p-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {invoices.map((invoice) => (
                <tr key={invoice.id} className="border-b border-border">
                  <td className="p-2">{invoice.status}</td>
                  <td className="p-2">
                    {invoice.amountTotal} {invoice.currency}
                  </td>
                  <td className="p-2">{invoice.dueDate ?? "-"}</td>
                  <td className="p-2">{invoice.memo ?? "-"}</td>
                  <td className="flex flex-wrap gap-2 p-2">
                    <button
                      type="button"
                      disabled={invoice.status !== "draft"}
                      onClick={() => sendMutation.mutate(invoice.id)}
                      aria-label={`Send invoice ${invoice.id}`}
                      className={BUTTON_CLASS}
                    >
                      Send
                    </button>
                    <button
                      type="button"
                      disabled={invoice.status === "void"}
                      onClick={() => voidMutation.mutate(invoice.id)}
                      aria-label={`Void invoice ${invoice.id}`}
                      className={BUTTON_CLASS}
                    >
                      Void
                    </button>
                    {/* Same plain-<a>-not-fetch approach as
                        customer/Invoices.tsx -- see that file's identical
                        comment. Admins can preview a draft's PDF too (the
                        backend route has no status restriction), unlike
                        Pay/the customer view. */}
                    <a
                      href={`/api/admin/invoices/${invoice.id}/pdf`}
                      target="_blank"
                      rel="noreferrer"
                      aria-label={`Download PDF for invoice ${invoice.id}`}
                      className={BUTTON_CLASS}
                    >
                      PDF
                    </a>
                    <ManualPaymentForm invoice={invoice} onRecorded={invalidate} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
