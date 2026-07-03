import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { RateLimitedError } from "../../../api/client";
import {
  capturePaypalPayment,
  getInvoice,
  getPaymentMethods,
  payInvoice,
  payInvoiceViaPaypal,
  uploadPaymentProof,
} from "../../../api/invoices";
import { BUTTON_CLASS } from "../../../styles/a11y";

// Invoice statuses the pay endpoints will actually accept -- matches the
// backend's own check (api/invoices_public.py's pay routes all 409 on
// anything else). Used purely to decide what this page SHOWS; the
// backend's own check is still the real enforcement.
const PAYABLE_STATUSES = new Set(["sent", "overdue"]);

// TODO(logan): swap the raw client_secret display for an actual Stripe
// Elements/Checkout mount once @stripe/stripe-js + @stripe/react-stripe-js
// are added to package.json -- this proves the data flow (real call to
// POST /api/invoices/:id/pay, real client_secret round trip) without
// pulling in Stripe's JS yet, see docs/design/04-invoices.md.
export function CustomerPay() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  // Fetched up front so the page can gate the pay buttons on the
  // invoice's actual current status -- without this, an already-paid/
  // void/draft invoice still showed "Pay with card"/"Pay with PayPal",
  // and clicking either just 409ed with a generic "try again shortly"
  // message that made no sense for a done invoice.
  const invoiceQuery = useQuery({
    queryKey: ["invoice", id],
    queryFn: () => {
      if (!id) throw new Error("missing invoice id");
      return getInvoice(id);
    },
    enabled: !!id,
  });
  const isPayable = invoiceQuery.data
    ? PAYABLE_STATUSES.has(invoiceQuery.data.status)
    : false;

  const mutation = useMutation({
    mutationFn: () => {
      if (!id) throw new Error("missing invoice id");
      return payInvoice(id);
    },
  });

  // GET /api/invoices/payment-methods -- "paypal" only comes back true
  // once real API credentials are actually configured (see backend's
  // domain/payments/providers/paypal.py is_configured), so this button
  // only ever shows up when it would genuinely work, rather than
  // offering a PayPal option that 503s the moment it's clicked.
  const paymentMethods = useQuery({
    queryKey: ["payment-methods"],
    queryFn: getPaymentMethods,
  });

  const paypalMutation = useMutation({
    mutationFn: () => {
      if (!id) throw new Error("missing invoice id");
      return payInvoiceViaPaypal(id);
    },
    onSuccess: (order) => {
      // A real redirect to PayPal's own approval page -- not a fetch,
      // since the customer needs to actually authenticate/approve on
      // PayPal's own site, not inside this app.
      if (order.approval_url) window.location.assign(order.approval_url);
    },
  });

  // "An optional place to put a screenshot or something to show that
  // they sent something" -- a customer who paid via Zelle/PayPal-direct
  // outside this app can attach proof for an admin to review.
  const [proofFile, setProofFile] = useState<File | null>(null);
  const proofMutation = useMutation({
    mutationFn: () => {
      if (!id) throw new Error("missing invoice id");
      if (!proofFile) throw new Error("no file selected");
      return uploadPaymentProof(id, proofFile);
    },
    onSuccess: () => setProofFile(null),
  });

  // PayPal redirects the customer back to this exact page afterward,
  // appending "?token=<order_id>" (see the provider's return_url/
  // cancel_url, built in domain/payments/providers/paypal.py's
  // create_order) -- capture automatically on that return rather than
  // making the customer click a second "confirm" button after they've
  // already approved on PayPal's side.
  //
  // Snapshotted into useState (lazy init), NOT read live from
  // searchParams on every render: this value is used both by
  // mutationFn (below) and to decide which branch of this page to show.
  // react-query's useMutation re-binds its internal mutationFn reference
  // synchronously on every render (not just via this effect) -- stripping
  // "?token=" from the URL (see the effect below) triggers a re-render
  // with searchParams.get("token") now null BEFORE the in-flight capture
  // call actually reads it, which raced the mutationFn's own "live"
  // paypalToken closure into throwing "missing ... PayPal token" on every
  // single real capture attempt. A stable snapshot captured once, before
  // that render ever happens, closes the race entirely; it also means
  // stripping the token from the URL can never flip this page back to
  // the "show pay buttons" branch mid-capture, without needing separate
  // state for that.
  const [capturePaypalToken] = useState(() => searchParams.get("token"));
  const captureMutation = useMutation({
    mutationFn: () => {
      if (!id || !capturePaypalToken) {
        throw new Error("missing invoice id or PayPal token");
      }
      return capturePaypalPayment(id, capturePaypalToken);
    },
  });
  // A ref guard (not captureMutation.isPending/isSuccess in the deps
  // array) -- useMutation returns a new object identity every render, so
  // depending on it directly would either re-run this effect constantly
  // or force an exhaustive-deps lint fight; a ref that's only ever set
  // once per mount is simpler and does exactly what's needed here (fire
  // capture exactly once when a PayPal return token is present).
  const hasStartedCaptureRef = useRef(false);
  useEffect(() => {
    if (capturePaypalToken && !hasStartedCaptureRef.current) {
      hasStartedCaptureRef.current = true;
      captureMutation.mutate();
      // Strip ?token= from the URL right after firing -- the in-flight
      // capture call already has its own snapshot (capturePaypalToken
      // above), so this can't affect it. Without this, a reload or
      // back/forward navigation while `?token=` is still in the address
      // bar re-runs this effect from scratch (a fresh capturePaypalToken
      // snapshot, a fresh hasStartedCaptureRef) and fires a SECOND
      // capture attempt against the same (already captured, or
      // in-flight) PayPal order -- harmless only because the backend
      // happens to reject a re-capture, not because this page avoids
      // retrying it.
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("token");
          return next;
        },
        { replace: true },
      );
    }
  }, [capturePaypalToken, captureMutation, setSearchParams]);

  if (capturePaypalToken) {
    return (
      <main className="mx-auto w-full max-w-md px-4 py-8">
        <h1 className="mb-6 text-2xl text-fg-primary">Pay invoice</h1>
        {captureMutation.isPending && (
          <p className="text-base text-fg-primary">Finishing your PayPal payment...</p>
        )}
        {captureMutation.isSuccess && captureMutation.data?.status === "pending" && (
          <p className="text-base text-fg-primary">
            Your payment is being reviewed by PayPal; we&apos;ll email you once it
            clears.
          </p>
        )}
        {captureMutation.isSuccess && captureMutation.data?.status !== "pending" && (
          <p className="text-base text-fg-primary">Payment received. Thank you!</p>
        )}
        {captureMutation.isError && (
          <p role="alert" className="text-base text-accent-red">
            Could not confirm your PayPal payment. Contact us if you were charged.
          </p>
        )}
      </main>
    );
  }

  if (invoiceQuery.isLoading) {
    return (
      <main className="mx-auto w-full max-w-md px-4 py-8">
        <h1 className="mb-6 text-2xl text-fg-primary">Pay invoice</h1>
        <p className="text-base text-fg-muted">Loading...</p>
      </main>
    );
  }

  // Regression fix for FE2: an already-paid/void/draft invoice must not
  // still show live "Pay with card"/"Pay with PayPal" buttons -- clicking
  // either just 409ed against a state the customer had no way to
  // understand from this page alone ("Could not start payment. Try again
  // shortly." on an invoice that's already fully paid is actively
  // misleading).
  if (invoiceQuery.data && !isPayable) {
    return (
      <main className="mx-auto w-full max-w-md px-4 py-8">
        <h1 className="mb-6 text-2xl text-fg-primary">Pay invoice</h1>
        <p className="text-base text-fg-primary">
          {invoiceQuery.data.status === "paid"
            ? "This invoice has already been paid. Thank you!"
            : invoiceQuery.data.status === "void"
              ? "This invoice has been voided and is no longer payable."
              : "This invoice isn't ready to be paid yet."}
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-md px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Pay invoice</h1>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate()}
          className={BUTTON_CLASS}
        >
          {mutation.isPending ? "Starting payment..." : "Pay with card"}
        </button>
        {paymentMethods.data?.paypal && (
          <button
            type="button"
            disabled={paypalMutation.isPending}
            onClick={() => paypalMutation.mutate()}
            className={BUTTON_CLASS}
          >
            {paypalMutation.isPending ? "Redirecting to PayPal..." : "Pay with PayPal"}
          </button>
        )}
      </div>

      {mutation.isError &&
        (mutation.error instanceof RateLimitedError ? (
          <p role="alert" className="mt-4 text-base text-accent-red">
            Too many attempts -- try again in {mutation.error.retryAfterSeconds}s.
          </p>
        ) : (
          <p role="alert" className="mt-4 text-base text-accent-red">
            Could not start payment. Try again shortly.
          </p>
        ))}

      {paypalMutation.isError && (
        <p role="alert" className="mt-4 text-base text-accent-red">
          Could not start PayPal payment. Try again shortly.
        </p>
      )}

      {mutation.data && (
        <p className="mt-4 text-base text-fg-primary">
          Payment intent ready (client_secret received) -- Stripe Elements mount
          pending.
        </p>
      )}

      {/* Always shown -- an admin can record any of these regardless of
          whether PayPal's own API is configured, so this is never a dead
          end even when the button above isn't offered. The real Zelle
          handle is shown directly (not just "contact us about Zelle")
          once one is actually configured -- "I need to have my Zelle tag
          and whatnot on the customer invoice so that they can see the
          options of where they can pay." */}
      <div className="mt-6 rounded border border-border p-4">
        <p className="text-base text-fg-primary">Other ways to pay</p>
        {paymentMethods.data?.zelle_handle && (
          <p className="mt-2 text-base text-fg-primary">
            Zelle: <span className="font-mono">{paymentMethods.data.zelle_handle}</span>
          </p>
        )}
        <p className="mt-2 text-base text-fg-muted">
          PayPal sent directly or in person are also fine -- just contact us and
          we&apos;ll mark your invoice paid once we receive it.
        </p>

        <div className="mt-4 border-t border-border pt-4">
          <label
            htmlFor="payment-proof"
            className="mb-1 block text-base text-fg-primary"
          >
            Already sent it? Upload a screenshot as proof (optional)
          </label>
          <input
            id="payment-proof"
            type="file"
            accept="image/png,image/jpeg,image/webp,application/pdf"
            onChange={(e) => setProofFile(e.target.files?.[0] ?? null)}
            className="block w-full text-base text-fg-primary"
          />
          <button
            type="button"
            disabled={!proofFile || proofMutation.isPending}
            onClick={() => proofMutation.mutate()}
            className={`${BUTTON_CLASS} mt-2`}
          >
            {proofMutation.isPending ? "Uploading..." : "Upload proof"}
          </button>
          {proofMutation.isSuccess && (
            <p className="mt-2 text-base text-fg-primary">
              Uploaded. We&apos;ll take a look and mark your invoice paid.
            </p>
          )}
          {proofMutation.isError && (
            <p role="alert" className="mt-2 text-base text-accent-red">
              Could not upload that file -- only images and PDFs are accepted.
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
