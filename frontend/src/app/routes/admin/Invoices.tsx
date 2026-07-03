import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../../api/client";
import { getBomCostBreakdown, listBoms } from "../../../api/bom";
import { listCustomers } from "../../../api/customers";
import {
  type CreateInvoiceLineItem,
  type Invoice,
  type InvoicePayment,
  type ManualPaymentMethod,
  createInvoice,
  getAdminInvoice,
  listAdminInvoices,
  listPaymentProof,
  openInvoicePdf,
  paymentProofFileUrl,
  recordManualPayment,
  refundPayment,
  sendInvoice,
  voidInvoice,
} from "../../../api/invoices";
import {
  BUTTON_CLASS,
  CHIP_LINK_CLASS,
  INPUT_CLASS,
  LABEL_CLASS,
} from "../../../styles/a11y";

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
// Lets an admin actually see what a customer uploaded (Pay.tsx's
// optional screenshot-as-proof upload) before deciding whether to
// record a manual payment -- "something to show that they sent
// something." A plain <a href> (not a fetch+blob dance like the PDF
// download fix) is fine here: this always opens successfully once a
// proof exists (no server-side rendering step that can fail the way PDF
// compilation can), and the browser's own image/PDF viewer handles
// display.
function PaymentProofViewer({ invoiceId }: { invoiceId: string }) {
  const [open, setOpen] = useState(false);
  const proofQuery = useQuery({
    queryKey: ["admin", "invoices", invoiceId, "payment-proof"],
    queryFn: () => listPaymentProof(invoiceId),
    enabled: open,
  });

  return (
    <div>
      <button type="button" onClick={() => setOpen((v) => !v)} className={BUTTON_CLASS}>
        {open ? "Hide" : "View"} payment proof
      </button>
      {open && (
        <div className="mt-2 flex flex-wrap gap-2">
          {proofQuery.isLoading && <p className="text-sm text-fg-muted">Loading...</p>}
          {proofQuery.data?.length === 0 && (
            <p className="text-sm text-fg-muted">
              No proof uploaded by the customer yet.
            </p>
          )}
          {proofQuery.data?.map((proof) => (
            <a
              key={proof.id}
              href={paymentProofFileUrl(invoiceId, proof.id)}
              target="_blank"
              rel="noreferrer"
              className={CHIP_LINK_CLASS}
            >
              {proof.content_type === "application/pdf" ? "PDF" : "Image"} (
              {new Date(proof.created_at).toLocaleString()})
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

const DISPUTE_STATUS_LABEL: Record<string, string> = {
  needs_response: "Dispute: needs response",
  under_review: "Dispute: under review",
  won: "Dispute: won",
  lost: "Dispute: lost",
};

// Every payment status a refund can still target -- a fully "refunded"
// payment or one that never succeeded (pending/failed) has nothing left
// to refund. Matches domain/invoices/refunds.py::refund_payment's own
// PaymentNotRefundable check.
const REFUNDABLE_PAYMENT_STATUSES = new Set(["succeeded", "partially_refunded"]);

function RefundForm({
  invoiceId,
  payment,
  onRefunded,
}: {
  invoiceId: string;
  payment: InvoicePayment;
  onRefunded: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  // Generated once per refund action (when the form opens) and reused
  // across any retry of that same action, so a lost-response resubmit
  // dedupes server-side instead of minting a fresh provider refund.
  const [clientRequestId, setClientRequestId] = useState(() => crypto.randomUUID());

  // Mirrors the backend authority's own remaining-balance computation
  // (domain/invoices/refunds.py::_reserved_so_far / refund_payment):
  // count succeeded refunds (money actually moved) AND pending refunds
  // (money already claimed against the balance, not yet settled) --
  // but never failed refunds, which moved nothing and must not hide a
  // still-valid Refund button (M1).
  const refundedSoFar = payment.refunds
    .filter((r) => r.status === "succeeded" || r.status === "pending")
    .reduce((sum, r) => sum + Number(r.amount), 0);
  const remaining = Number(payment.amount) - refundedSoFar;

  const mutation = useMutation({
    mutationFn: () =>
      refundPayment(invoiceId, payment.id, {
        payment_id: payment.id,
        amount: amount || undefined,
        reason: reason || undefined,
        client_request_id: clientRequestId,
      }),
    onSuccess: () => {
      onRefunded();
      setOpen(false);
      setAmount("");
      setReason("");
      setClientRequestId(crypto.randomUUID());
    },
    onError: (err) => {
      // Backend returns RefundError.PriorAttemptFailed (409) when a prior
      // refund under this same client_request_id FAILED -- the caller
      // must retry under a NEW id (see errors.py). Without minting a
      // fresh one here, re-clicking Confirm resubmits the identical id and
      // gets the same 409 forever (L1 in FINDINGS.md). Matched on the
      // stable `code` from ApiError, not the message prose -- a copy-edit
      // of the backend's message text used to silently break this check
      // (FINDINGS.md L2). Every OTHER error (network/5xx, validation)
      // keeps the id stable so a genuine lost-response retry still
      // dedupes server-side.
      if (err instanceof ApiError && err.code === "RefundError.PriorAttemptFailed") {
        setClientRequestId(crypto.randomUUID());
      }
    },
  });

  if (!REFUNDABLE_PAYMENT_STATUSES.has(payment.status) || remaining <= 0) return null;

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          setClientRequestId(crypto.randomUUID());
          setOpen(true);
        }}
        aria-label={`Refund payment ${payment.id}`}
        className={BUTTON_CLASS}
      >
        Refund
      </button>
    );
  }

  return (
    <form
      className="flex w-full flex-col gap-2 rounded border border-border p-3 sm:w-auto sm:flex-row sm:items-end"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
    >
      <div>
        <label htmlFor={`refund-amount-${payment.id}`} className={LABEL_CLASS}>
          Amount (blank = full remaining {remaining.toFixed(2)})
        </label>
        <input
          id={`refund-amount-${payment.id}`}
          type="number"
          step="0.01"
          min="0"
          max={remaining}
          placeholder={remaining.toFixed(2)}
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          className={INPUT_CLASS}
        />
      </div>
      <div>
        <label htmlFor={`refund-reason-${payment.id}`} className={LABEL_CLASS}>
          Reason (optional)
        </label>
        <input
          id={`refund-reason-${payment.id}`}
          type="text"
          placeholder="e.g. duplicate charge"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className={INPUT_CLASS}
        />
      </div>
      <div className="flex gap-2">
        <button type="submit" disabled={mutation.isPending} className={BUTTON_CLASS}>
          {mutation.isPending ? "Refunding..." : "Confirm refund"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className={BUTTON_CLASS}>
          Cancel
        </button>
      </div>
      {mutation.isError && (
        <p role="alert" className="w-full text-base text-accent-red">
          {mutation.error instanceof Error
            ? mutation.error.message
            : "Could not issue the refund."}
        </p>
      )}
    </form>
  );
}

// Expandable per-invoice payment/refund/dispute detail -- the plain list
// row only has enough fields for listAdminInvoices' summary shape
// (status/amount/due/paid/memo); this fetches the real per-payment
// breakdown (dispute_status, refund history) on demand via
// getAdminInvoice, same lazy-fetch-on-expand pattern as
// PaymentProofViewer above.
function PaymentsPanel({ invoice }: { invoice: Invoice }) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const detailQuery = useQuery({
    queryKey: ["admin", "invoices", invoice.id, "detail"],
    queryFn: () => getAdminInvoice(invoice.id),
    enabled: open,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: ["admin", "invoices", invoice.id, "detail"],
    });
    queryClient.invalidateQueries({ queryKey: ["admin", "invoices"] });
  };

  if (invoice.status === "draft") return null;

  return (
    <div>
      <button type="button" onClick={() => setOpen((v) => !v)} className={BUTTON_CLASS}>
        {open ? "Hide" : "View"} payments
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-3">
          {detailQuery.isLoading && <p className="text-sm text-fg-muted">Loading...</p>}
          {detailQuery.data?.payments.length === 0 && (
            <p className="text-sm text-fg-muted">No payments recorded yet.</p>
          )}
          {detailQuery.data?.payments.map((payment) => (
            <div
              key={payment.id}
              className="flex flex-col gap-2 rounded border border-border p-3"
            >
              <div className="flex flex-wrap items-center gap-2 text-base text-fg-primary">
                <span>
                  {payment.method} -- {payment.amount} ({payment.status})
                </span>
                {payment.dispute_status && (
                  <span
                    role="status"
                    className="rounded bg-accent-red/10 px-2 py-0.5 text-sm text-accent-red"
                  >
                    {DISPUTE_STATUS_LABEL[payment.dispute_status] ??
                      payment.dispute_status}
                  </span>
                )}
              </div>
              {payment.note && (
                <p className="text-sm text-fg-muted">Note: {payment.note}</p>
              )}
              {payment.refunds.length > 0 && (
                <ul className="flex flex-col gap-1 text-sm text-fg-muted">
                  {payment.refunds.map((refund) => (
                    <li key={refund.id}>
                      Refunded {refund.amount}
                      {refund.reason ? ` -- ${refund.reason}` : ""} (
                      {new Date(refund.created_at).toLocaleDateString()})
                    </li>
                  ))}
                </ul>
              )}
              <RefundForm
                invoiceId={invoice.id}
                payment={payment}
                onRefunded={invalidate}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

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
    mutationFn: () =>
      recordManualPayment(invoice.id, { method, amount, note: note || undefined }),
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
        <button type="submit" disabled={mutation.isPending} className={BUTTON_CLASS}>
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
  unit: "",
};

// Plain useState, not React Hook Form + zod -- the ManualPaymentForm
// above (and every other form in this app) already uses this same plain
// pattern; introducing a form library for just this one form would be
// inconsistent without buying much, given the field count here is small
// and fixed-shape (no dynamic validation schema worth the dependency).
// How long to wait after the last keystroke before actually querying the
// server -- an admin typing "alice" fires this once, not once per
// letter. 250ms is short enough to still feel instant, long enough to
// skip a query for every single keypress of a fast typist.
const CUSTOMER_SEARCH_DEBOUNCE_MS = 250;

function CreateInvoiceForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [customerId, setCustomerId] = useState("");
  // The text actually in the search box -- separate from customerId,
  // since what's typed doesn't necessarily resolve to a real customer
  // yet (still typing, or a typo). Seeded to "" and resolved to a real
  // email once a customer is actually picked (see the datalist onChange
  // handler below).
  const [customerQuery, setCustomerQuery] = useState("");
  const [debouncedCustomerQuery, setDebouncedCustomerQuery] = useState("");
  const [memo, setMemo] = useState("");
  const [lineItems, setLineItems] = useState<CreateInvoiceLineItem[]>([
    { ...EMPTY_LINE_ITEM },
  ]);

  useEffect(() => {
    const timer = setTimeout(
      () => setDebouncedCustomerQuery(customerQuery),
      CUSTOMER_SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [customerQuery]);

  const customersQuery = useQuery({
    // Keyed by the debounced query itself -- a new key per distinct
    // search means TanStack Query caches each search's results
    // separately (retyping "alice" after searching something else
    // doesn't refetch), instead of one shared cache entry the next
    // keystroke would just overwrite.
    queryKey: ["admin", "customers", debouncedCustomerQuery],
    queryFn: () => listCustomers(debouncedCustomerQuery || undefined),
    // Only fetch once the form is actually open -- an admin might never
    // open this on a given visit, and the customer list isn't needed
    // for anything else on this page.
    enabled: open,
  });

  // Reacts to customersQuery.data itself, not just to onChange keystrokes
  // -- resolving the id only inside the input's onChange handler would
  // match against whatever data happened to be cached at THAT keystroke,
  // which is stale (the debounced, server-filtered search for what was
  // just typed hasn't necessarily resolved yet). This re-checks whenever
  // either the typed text or the fetched results change, so the id
  // reliably resolves once a real match actually arrives, however late.
  useEffect(() => {
    const match = customersQuery.data?.find((c) => c.email === customerQuery);
    setCustomerId(match?.id ?? "");
  }, [customerQuery, customersQuery.data]);

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
      setCustomerQuery("");
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

  const [importBomId, setImportBomId] = useState("");
  const [importBuildQuantity, setImportBuildQuantity] = useState("1");
  const bomsQuery = useQuery({
    queryKey: ["admin", "boms"],
    queryFn: listBoms,
    // Same lazy-load-once-open convention as customersQuery above.
    enabled: open,
  });
  const importMutation = useMutation({
    mutationFn: () =>
      getBomCostBreakdown(importBomId, Math.max(1, Number(importBuildQuantity) || 1)),
    onSuccess: (breakdown) => {
      // "It would be nice to give a price breakdown of material and time
      // and overhead" -- directly, as real separate invoice line items,
      // not a single lump sum that hides where the number came from. Each
      // material line keeps its own real quantity/unit price (so it
      // still reads as "12 resistors @ $0.10"); labor and overhead are
      // each their own single line since they don't have a natural
      // per-unit quantity the way a material does.
      const bom = bomsQuery.data?.find((b) => b.id === importBomId);
      const materialLines: CreateInvoiceLineItem[] = breakdown.material_lines.map(
        (line) => ({
          description: line.item_name,
          quantity: String(line.quantity),
          unit_price: line.unit_cost,
          unit: "ea",
        }),
      );
      const laborLine: CreateInvoiceLineItem | null =
        Number(breakdown.labor_hours) > 0
          ? {
              description: `Labor${bom ? ` (${bom.name})` : ""}`,
              quantity: breakdown.labor_hours,
              unit_price: bom?.labor_rate ?? "0",
              unit: "hr",
            }
          : null;
      const overheadLine: CreateInvoiceLineItem | null =
        Number(breakdown.overhead_cost) > 0
          ? {
              description: `Overhead (${breakdown.overhead_percent}%)`,
              quantity: "1",
              unit_price: breakdown.overhead_cost,
              unit: "",
            }
          : null;
      const imported = [
        ...materialLines,
        ...(laborLine ? [laborLine] : []),
        ...(overheadLine ? [overheadLine] : []),
      ];
      // Replaces the current (still-blank, in practice) line items
      // rather than appending -- importing from a BOM is meant to BE the
      // invoice's line items, not mixed in with whatever was already
      // half-typed. An admin who wants both can always click "Add line
      // item" afterward to add more by hand.
      setLineItems(imported.length > 0 ? imported : [{ ...EMPTY_LINE_ITEM }]);
    },
  });

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
        {/* A native <input list> + <datalist> combobox, not a plain
            <select> -- a flat alphabetical dropdown of every customer
            doesn't scale ("customer dropdown needs to have some filter
            in case I have a lot of people"). This gets real
            type-to-filter, keyboard navigation, and screen-reader
            support for free from the browser, without hand-building a
            custom ARIA combobox from scratch. The actual filtering
            happens server-side (debounced, see customersQuery above) --
            the datalist's own options are just whatever that search
            already narrowed down to, not a client-side filter over a
            full customer list that may not even be loaded. */}
        <input
          id="new-invoice-customer"
          type="text"
          required
          autoComplete="off"
          list="new-invoice-customer-options"
          placeholder="Type to search customers..."
          value={customerQuery}
          onChange={(e) => setCustomerQuery(e.target.value)}
          className={INPUT_CLASS}
        />
        <datalist id="new-invoice-customer-options">
          {customersQuery.data?.map((c) => (
            <option key={c.id} value={c.email} />
          ))}
        </datalist>
        {customersQuery.isLoading && (
          <p className="mt-1 text-sm text-fg-muted">Searching...</p>
        )}
        {customerQuery && !customersQuery.isLoading && !customerId && (
          <p className="mt-1 text-sm text-fg-muted">
            No exact match yet -- pick a customer from the list.
          </p>
        )}
        {customersQuery.isError && (
          <p role="alert" className="mt-1 text-base text-accent-red">
            Could not load customer list.
          </p>
        )}
      </div>

      {bomsQuery.data && bomsQuery.data.length > 0 && (
        <div className="flex flex-wrap items-end gap-2 rounded border border-border p-3">
          <div className="min-w-[10rem] flex-1">
            <label htmlFor="import-bom" className={LABEL_CLASS}>
              Import from bill of materials
            </label>
            <select
              id="import-bom"
              value={importBomId}
              onChange={(e) => setImportBomId(e.target.value)}
              className={INPUT_CLASS}
            >
              <option value="">Select a BOM...</option>
              {bomsQuery.data.map((bom) => (
                <option key={bom.id} value={bom.id}>
                  {bom.name}
                </option>
              ))}
            </select>
          </div>
          <div className="w-24">
            <label htmlFor="import-build-qty" className={LABEL_CLASS}>
              Build qty
            </label>
            <input
              id="import-build-qty"
              type="number"
              min={1}
              value={importBuildQuantity}
              onChange={(e) => setImportBuildQuantity(e.target.value)}
              className={INPUT_CLASS}
            />
          </div>
          <button
            type="button"
            disabled={!importBomId || importMutation.isPending}
            onClick={() => importMutation.mutate()}
            className={BUTTON_CLASS}
          >
            Import as line items
          </button>
          {importMutation.isError && (
            <p role="alert" className="w-full text-sm text-accent-red">
              Could not import -- every material line needs a real unit_cost set first.
            </p>
          )}
        </div>
      )}

      <div className="flex flex-col gap-3">
        <span className={LABEL_CLASS}>Line items</span>
        {lineItems.map((item, index) => (
          // items-end -> items-stretch isn't needed here; the row itself
          // just needed more breathing room per-field ("the manual input
          // is too small") -- widened every fixed-width column below and
          // bumped to text-lg so entering several line items in a row
          // doesn't mean squinting at 80px-wide number fields.
          <div key={index} className="flex flex-wrap items-end gap-3">
            <div className="min-w-[14rem] flex-1">
              <label htmlFor={`li-description-${index}`} className={LABEL_CLASS}>
                Description
              </label>
              <input
                id={`li-description-${index}`}
                type="text"
                value={item.description}
                onChange={(e) => updateLineItem(index, { description: e.target.value })}
                className={`${INPUT_CLASS} text-lg`}
              />
            </div>
            <div className="w-28">
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
                className={`${INPUT_CLASS} text-lg`}
              />
            </div>
            <div className="w-24">
              <label htmlFor={`li-unit-${index}`} className={LABEL_CLASS}>
                Unit
              </label>
              <input
                id={`li-unit-${index}`}
                type="text"
                placeholder="hr, ea..."
                value={item.unit}
                onChange={(e) => updateLineItem(index, { unit: e.target.value })}
                className={`${INPUT_CLASS} text-lg`}
              />
            </div>
            <div className="w-36">
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
                className={`${INPUT_CLASS} text-lg`}
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
  const pdfMutation = useMutation({
    mutationFn: (id: string) => openInvoicePdf(`/api/admin/invoices/${id}/pdf`),
  });

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
                <th className="p-2">Paid</th>
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
                  <td className="p-2">
                    {invoice.paid_at
                      ? new Date(invoice.paid_at).toLocaleDateString()
                      : "-"}
                  </td>
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
                    {/* A real fetch+blob open, not a plain <a href> -- see
                        openInvoicePdf's own doc comment ("the PDF option
                        doesn't work" was a real bug: a failing endpoint
                        just opened a blank/raw-error tab with no usable
                        feedback). Admins can preview a draft's PDF too
                        (the backend route has no status restriction),
                        unlike Pay/the customer view. */}
                    <button
                      type="button"
                      onClick={() => pdfMutation.mutate(invoice.id)}
                      disabled={
                        pdfMutation.isPending && pdfMutation.variables === invoice.id
                      }
                      aria-label={`Download PDF for invoice ${invoice.id}`}
                      className={BUTTON_CLASS}
                    >
                      {pdfMutation.isPending && pdfMutation.variables === invoice.id
                        ? "Opening..."
                        : "PDF"}
                    </button>
                    {pdfMutation.isError && pdfMutation.variables === invoice.id && (
                      <p role="alert" className="w-full text-sm text-accent-red">
                        {pdfMutation.error instanceof Error
                          ? pdfMutation.error.message
                          : "Could not open the PDF."}
                      </p>
                    )}
                    <ManualPaymentForm invoice={invoice} onRecorded={invalidate} />
                    <PaymentProofViewer invoiceId={invoice.id} />
                    <PaymentsPanel invoice={invoice} />
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
