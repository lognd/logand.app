import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import type { Appearance, Stripe as StripeClient } from "@stripe/stripe-js";
import { loadStripe } from "@stripe/stripe-js";
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from "@stripe/react-stripe-js";
import { RateLimitedError } from "../../../api/client";
import {
  capturePaypalPayment,
  getInvoice,
  getPaymentMethods,
  payInvoice,
  payInvoiceViaPaypal,
  uploadPaymentProof,
} from "../../../api/invoices";
import { logError, logInfo, logWarn } from "../../../lib/logging";
import { BUTTON_CLASS } from "../../../styles/a11y";

// Invoice statuses the pay endpoints will actually accept -- matches the
// backend's own check (api/invoices_public.py's pay routes all 409 on
// anything else). Used purely to decide what this page SHOWS; the
// backend's own check is still the real enforcement.
const PAYABLE_STATUSES = new Set(["sent", "overdue"]);

// Memoized across the whole tab, not per mount -- loadStripe injects the
// js.stripe.com script tag on first call, and calling it again with the
// same key must reuse that one instance instead of re-injecting/re-
// initializing on every visit to this page. Keyed so a (never expected
// in practice) publishable-key change between fetches doesn't silently
// keep using a client built for the old key.
let stripeClientPromise: Promise<StripeClient | null> | null = null;
let stripeClientKey: string | null = null;
function getStripeClient(publishableKey: string): Promise<StripeClient | null> {
  if (!stripeClientPromise || stripeClientKey !== publishableKey) {
    stripeClientKey = publishableKey;
    stripeClientPromise = loadStripe(publishableKey);
  }
  return stripeClientPromise;
}

// Payment Element renders inside Stripe-hosted iframes that can't see
// this page's stylesheet -- feed it the SAME design tokens (tokens.css
// CSS variables) at runtime rather than duplicating their hex values
// here, so a future theme change can't desync the card form from the
// rest of the page.
// Fallback hex values for stripeAppearance()'s token() lookups below --
// only ever used if a referenced CSS custom property resolves to "" (not
// yet applied, or renamed in a future tokens.css refactor). Without a
// fallback, an empty string fed into Stripe's `variables` is silently
// ignored/warned by Stripe.js and the form just degrades to default
// styling with no build-time or test signal (FINDINGS.md L1) -- these
// mirror tokens.css's own current values for each variable so the
// degraded case still looks like this app, not stock Stripe.
const STRIPE_TOKEN_FALLBACKS: Record<string, string> = {
  "--accent-orange": "#f97316",
  "--bg-secondary": "#1a1a1a",
  "--fg-primary": "#f5f5f5",
  "--fg-muted": "#a3a3a3",
  "--accent-red": "#ef4444",
};

// Payment Element renders inside Stripe-hosted iframes that can't see
// this page's stylesheet -- feed it the SAME design tokens (tokens.css
// CSS variables) at runtime rather than duplicating their hex values
// here, so a future theme change can't desync the card form from the
// rest of the page.
export function stripeAppearance(): Appearance {
  const css = getComputedStyle(document.documentElement);
  const token = (name: string) => {
    const value = css.getPropertyValue(name).trim();
    if (value === "") {
      logWarn(
        "stripe appearance token missing",
        `${name} resolved empty; falling back to hardcoded default`,
      );
      return STRIPE_TOKEN_FALLBACKS[name] ?? "";
    }
    return value;
  };
  return {
    theme: "night",
    variables: {
      colorPrimary: token("--accent-orange"),
      colorBackground: token("--bg-secondary"),
      colorText: token("--fg-primary"),
      colorTextSecondary: token("--fg-muted"),
      colorDanger: token("--accent-red"),
      borderRadius: "4px",
    },
  };
}

// The card form proper -- must be a separate component because
// useStripe/useElements only work below an <Elements> provider, which
// CustomerPay itself renders.
function CardPaymentForm({
  invoiceId,
  onComplete,
}: {
  invoiceId: string;
  onComplete: (status: "succeeded" | "processing") => void;
}) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    // Both are null only until Stripe.js finishes loading -- the submit
    // button below is disabled until then, so this is just belt for the
    // types, not a state a user can actually reach.
    if (!stripe || !elements) return;
    setSubmitting(true);
    setErrorMessage(null);
    logInfo("stripe confirm started", `invoice ${invoiceId}`);
    // redirect: "if_required" -- plain card payments settle inline with
    // no navigation; return_url only comes into play for redirect-based
    // methods (3DS challenges etc.), which land back on this page with
    // ?redirect_status=... (handled by CustomerPay's snapshot).
    const { error, paymentIntent } = await stripe.confirmPayment({
      elements,
      confirmParams: {
        return_url: `${window.location.origin}/invoices/${invoiceId}/pay`,
      },
      redirect: "if_required",
    });
    setSubmitting(false);
    if (error) {
      // card_error/validation_error messages are written by Stripe for
      // customers ("Your card was declined.") -- show them verbatim;
      // anything else (network, config) gets a generic retry line.
      const friendly =
        error.type === "card_error" || error.type === "validation_error"
          ? (error.message ?? "Your card could not be charged. Try again.")
          : "Something went wrong confirming your payment. Try again shortly.";
      logWarn(
        "stripe confirm failed",
        `invoice ${invoiceId}: ${error.type}: ${error.message ?? "(no message)"}`,
      );
      setErrorMessage(friendly);
      return;
    }
    // With redirect: "if_required" and no error, Stripe guarantees a
    // paymentIntent; "processing" covers slow-settling methods, anything
    // else here means the charge went through.
    const status = paymentIntent.status === "processing" ? "processing" : "succeeded";
    logInfo("stripe confirm settled", `invoice ${invoiceId}: ${paymentIntent.status}`);
    onComplete(status);
  }

  return (
    <form onSubmit={handleSubmit} aria-label="Card payment">
      <PaymentElement />
      <button
        type="submit"
        disabled={!stripe || !elements || submitting}
        className={`${BUTTON_CLASS} mt-4`}
      >
        {submitting ? "Confirming..." : "Pay now"}
      </button>
      {errorMessage && (
        <p role="alert" className="mt-4 text-base text-accent-red">
          {errorMessage}
        </p>
      )}
    </form>
  );
}

// The customer-facing pay page: real Stripe card payments (Payment
// Element, confirmed inline), the PayPal approval/capture round trip,
// and the manual-payment escape hatches (Zelle handle, proof upload).
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
    // The client_secret itself is deliberately NOT logged -- whoever
    // holds it can confirm (or cancel) the intent, so it stays out of
    // the exportable client log buffer.
    onSuccess: () => logInfo("stripe payment intent ready", `invoice ${id}`),
    onError: (error) =>
      logError("stripe payment intent request failed", `invoice ${id}: ${error}`),
  });

  // Outcome of an INLINE confirmPayment (no redirect happened) -- set by
  // CardPaymentForm once Stripe settles the charge. Held here (not in
  // the form) so the success message survives the form unmounting.
  const [cardOutcome, setCardOutcome] = useState<"succeeded" | "processing" | null>(
    null,
  );

  // Redirect-based card flows (3DS challenges and friends) land back on
  // this page with Stripe's own ?payment_intent=...&redirect_status=...
  // appended to the return_url. Snapshotted once (lazy useState) and
  // then stripped from the URL, for exactly the reasons documented on
  // capturePaypalToken below -- and only treated as a Stripe return when
  // payment_intent_client_secret is present too, so nothing else that
  // happens to name a param "redirect_status" can trip this branch.
  const [stripeRedirectStatus] = useState(() =>
    searchParams.get("payment_intent_client_secret")
      ? searchParams.get("redirect_status")
      : null,
  );
  const hasStrippedStripeReturnRef = useRef(false);
  useEffect(() => {
    if (stripeRedirectStatus && !hasStrippedStripeReturnRef.current) {
      hasStrippedStripeReturnRef.current = true;
      const log = stripeRedirectStatus === "failed" ? logWarn : logInfo;
      log("stripe redirect return", `invoice ${id}: ${stripeRedirectStatus}`);
      // Strip Stripe's return params -- a reload/bookmark of the bare
      // pay page URL must not keep re-showing a stale outcome (and the
      // client_secret shouldn't linger in the address bar/history).
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("payment_intent");
          next.delete("payment_intent_client_secret");
          next.delete("redirect_status");
          return next;
        },
        { replace: true },
      );
    }
  }, [stripeRedirectStatus, id, setSearchParams]);

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

  // Card payment settled (inline confirm or a redirect return) -- takes
  // precedence over the isPayable branch below on purpose: right after a
  // successful charge the webhook may not have marked the invoice paid
  // yet, and this page must say "payment received", not still offer the
  // pay buttons against a stale "sent" status. A FAILED redirect return
  // deliberately falls through to the normal payable page (with an alert
  // there) so the customer can immediately try again.
  const cardResult =
    cardOutcome ??
    (stripeRedirectStatus === "succeeded" || stripeRedirectStatus === "processing"
      ? stripeRedirectStatus
      : null);
  if (cardResult) {
    return (
      <main className="mx-auto w-full max-w-md px-4 py-8">
        <h1 className="mb-6 text-2xl text-fg-primary">Pay invoice</h1>
        {cardResult === "processing" ? (
          <p className="text-base text-fg-primary">
            Your payment is processing; we&apos;ll email you once it clears.
          </p>
        ) : (
          <p className="text-base text-fg-primary">Payment received. Thank you!</p>
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

  // The card option needs BOTH flags: "stripe" says the backend can mint
  // PaymentIntents, the pk_ is what the browser itself needs to mount the
  // card form. The backend only ever sends them together (see
  // get_payment_methods), so this is one condition, not a half-configured
  // third state to design UI for.
  const stripePublishableKey = paymentMethods.data?.stripe
    ? paymentMethods.data.stripe_publishable_key
    : null;

  return (
    <main className="mx-auto w-full max-w-md px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Pay invoice</h1>

      {stripeRedirectStatus === "failed" && (
        <p role="alert" className="mb-4 text-base text-accent-red">
          Your payment was not completed and you have not been charged. You can
          try again below.
        </p>
      )}

      {mutation.data && stripePublishableKey && id ? (
        // The intent exists -- swap the pay buttons for the real card
        // form. Payment Element renders inside Stripe-hosted iframes;
        // card data never touches this app or its backend (see
        // docs/design/04-invoices.md).
        <Elements
          stripe={getStripeClient(stripePublishableKey)}
          options={{
            clientSecret: mutation.data.client_secret,
            appearance: stripeAppearance(),
          }}
        >
          <CardPaymentForm invoiceId={id} onComplete={setCardOutcome} />
        </Elements>
      ) : (
        <div className="flex flex-wrap gap-3">
          {stripePublishableKey && (
            <button
              type="button"
              disabled={mutation.isPending}
              onClick={() => mutation.mutate()}
              className={BUTTON_CLASS}
            >
              {mutation.isPending ? "Starting payment..." : "Pay with card"}
            </button>
          )}
          {paymentMethods.data?.paypal && (
            <button
              type="button"
              disabled={paypalMutation.isPending}
              onClick={() => paypalMutation.mutate()}
              className={BUTTON_CLASS}
            >
              {paypalMutation.isPending
                ? "Redirecting to PayPal..."
                : "Pay with PayPal"}
            </button>
          )}
        </div>
      )}

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
