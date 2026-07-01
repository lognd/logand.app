import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listCustomers } from "../../../api/customers";
import {
  type CreateInvoiceLineItem,
  type Invoice,
  type ManualPaymentMethod,
  createInvoice,
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

const EMPTY_LINE_ITEM: CreateInvoiceLineItem = {
  description: "",
  quantity: "1",
  unit_price: "",
};

// Plain useState, not React Hook Form + zod -- the ManualPaymentForm
// above (and every other form in this app) already uses this same plain
// pattern; introducing a form library for just this one form would be
// inconsistent without buying much, given the field count here is small
// and fixed-shape (no dynamic validation schema worth the dependency).
function CreateInvoiceForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [customerId, setCustomerId] = useState("");
  const [memo, setMemo] = useState("");
  const [lineItems, setLineItems] = useState<CreateInvoiceLineItem[]>([
    { ...EMPTY_LINE_ITEM },
  ]);

  const customersQuery = useQuery({
    queryKey: ["admin", "customers"],
    queryFn: listCustomers,
    // Only fetch once the form is actually open -- an admin might never
    // open this on a given visit, and the customer list isn't needed
    // for anything else on this page.
    enabled: open,
  });

  const mutation = useMutation({
    mutationFn: () =>
      createInvoice(
        customerId,
        lineItems.filter((li) => li.description && li.unit_price),
        memo || undefined,
      ),
    onSuccess: () => {
      onCreated();
      setOpen(false);
      setCustomerId("");
      setMemo("");
      setLineItems([{ ...EMPTY_LINE_ITEM }]);
    },
  });

  function updateLineItem(index: number, patch: Partial<CreateInvoiceLineItem>) {
    setLineItems((items) =>
      items.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
  }

  function addLineItem() {
    setLineItems((items) => [...items, { ...EMPTY_LINE_ITEM }]);
  }

  function removeLineItem(index: number) {
    setLineItems((items) => items.filter((_, i) => i !== index));
  }

  const hasAtLeastOneRealLineItem = lineItems.some(
    (li) => li.description && li.unit_price,
  );

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className={BUTTON_CLASS}>
        New invoice
      </button>
    );
  }

  return (
    <form
      className="mb-6 flex flex-col gap-4 rounded border border-border p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!customerId || !hasAtLeastOneRealLineItem) return;
        mutation.mutate();
      }}
    >
      <h2 className="text-xl text-fg-primary">New invoice</h2>

      <div>
        <label htmlFor="new-invoice-customer" className={LABEL_CLASS}>
          Bill to
        </label>
        <select
          id="new-invoice-customer"
          required
          value={customerId}
          onChange={(e) => setCustomerId(e.target.value)}
          className={INPUT_CLASS}
        >
          <option value="">
            {customersQuery.isLoading ? "Loading customers..." : "Select a customer"}
          </option>
          {customersQuery.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.email}
            </option>
          ))}
        </select>
        {customersQuery.isError && (
          <p role="alert" className="mt-1 text-base text-accent-red">
            Could not load customer list.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-3">
        <span className={LABEL_CLASS}>Line items</span>
        {lineItems.map((item, index) => (
          <div key={index} className="flex flex-wrap items-end gap-2">
            <div className="min-w-[10rem] flex-1">
              <label htmlFor={`li-description-${index}`} className={LABEL_CLASS}>
                Description
              </label>
              <input
                id={`li-description-${index}`}
                type="text"
                value={item.description}
                onChange={(e) => updateLineItem(index, { description: e.target.value })}
                className={INPUT_CLASS}
              />
            </div>
            <div className="w-20">
              <label htmlFor={`li-quantity-${index}`} className={LABEL_CLASS}>
                Qty
              </label>
              <input
                id={`li-quantity-${index}`}
                type="number"
                step="0.01"
                min="0"
                value={item.quantity}
                onChange={(e) => updateLineItem(index, { quantity: e.target.value })}
                className={INPUT_CLASS}
              />
            </div>
            <div className="w-28">
              <label htmlFor={`li-unit-price-${index}`} className={LABEL_CLASS}>
                Unit price
              </label>
              <input
                id={`li-unit-price-${index}`}
                type="number"
                step="0.01"
                min="0"
                value={item.unit_price}
                onChange={(e) => updateLineItem(index, { unit_price: e.target.value })}
                className={INPUT_CLASS}
              />
            </div>
            <button
              type="button"
              onClick={() => removeLineItem(index)}
              disabled={lineItems.length === 1}
              aria-label={`Remove line item ${index + 1}`}
              className={BUTTON_CLASS}
            >
              Remove
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={addLineItem}
          className={`${BUTTON_CLASS} self-start`}
        >
          Add line item
        </button>
      </div>

      <div>
        <label htmlFor="new-invoice-memo" className={LABEL_CLASS}>
          Memo (optional)
        </label>
        <input
          id="new-invoice-memo"
          type="text"
          value={memo}
          onChange={(e) => setMemo(e.target.value)}
          className={INPUT_CLASS}
        />
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={mutation.isPending || !customerId || !hasAtLeastOneRealLineItem}
          className={BUTTON_CLASS}
        >
          {mutation.isPending ? "Creating..." : "Create invoice"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className={BUTTON_CLASS}>
          Cancel
        </button>
      </div>

      {mutation.isError && (
        <p role="alert" className="text-base text-accent-red">
          Could not create the invoice. Check every field and try again.
        </p>
      )}
    </form>
  );
}

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
      <CreateInvoiceForm onCreated={invalidate} />
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
                    {invoice.amount_total} {invoice.currency}
                  </td>
                  <td className="p-2">{invoice.due_date ?? "-"}</td>
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
