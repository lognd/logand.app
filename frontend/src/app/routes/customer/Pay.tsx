import { useEffect, useRef } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { RateLimitedError } from "../../../api/client";
import {
  capturePaypalPayment,
  getPaymentMethods,
  payInvoice,
  payInvoiceViaPaypal,
} from "../../../api/invoices";
import { BUTTON_CLASS } from "../../../styles/a11y";

// TODO(logan): swap the raw client_secret display for an actual Stripe
// Elements/Checkout mount once @stripe/stripe-js + @stripe/react-stripe-js
// are added to package.json -- this proves the data flow (real call to
// POST /api/invoices/:id/pay, real client_secret round trip) without
// pulling in Stripe's JS yet, see docs/design/04-invoices.md.
export function CustomerPay() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();

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

  // PayPal redirects the customer back to this exact page afterward,
  // appending "?token=<order_id>" (see the provider's return_url/
  // cancel_url, built in domain/payments/providers/paypal.py's
  // create_order) -- capture automatically on that return rather than
  // making the customer click a second "confirm" button after they've
  // already approved on PayPal's side.
  const paypalToken = searchParams.get("token");
  const captureMutation = useMutation({
    mutationFn: () => {
      if (!id || !paypalToken) throw new Error("missing invoice id or PayPal token");
      return capturePaypalPayment(id, paypalToken);
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
    if (paypalToken && !hasStartedCaptureRef.current) {
      hasStartedCaptureRef.current = true;
      captureMutation.mutate();
    }
  }, [paypalToken, captureMutation]);

  if (paypalToken) {
    return (
      <main className="mx-auto w-full max-w-md px-4 py-8">
        <h1 className="mb-6 text-2xl text-fg-primary">Pay invoice</h1>
        {captureMutation.isPending && (
          <p className="text-base text-fg-primary">Finishing your PayPal payment...</p>
        )}
        {captureMutation.isSuccess && (
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
          end even when the button above isn't offered. */}
      <p className="mt-6 text-base text-fg-muted">
        Prefer to pay another way? Zelle, PayPal sent directly, or in person are
        all fine -- just contact us and we&apos;ll mark your invoice paid once we
        receive it.
      </p>
    </main>
  );
}
