import { useMutation } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { RateLimitedError } from "../../../api/client";
import { payInvoice } from "../../../api/invoices";

// TODO(logan): swap the raw client_secret display for an actual Stripe
// Elements/Checkout mount once @stripe/stripe-js + @stripe/react-stripe-js
// are added to package.json -- this proves the data flow (real call to
// POST /api/invoices/:id/pay, real client_secret round trip) without
// pulling in Stripe's JS yet, see docs/design/04-invoices.md.
export function CustomerPay() {
  const { id } = useParams<{ id: string }>();
  const mutation = useMutation({
    mutationFn: () => {
      if (!id) throw new Error("missing invoice id");
      return payInvoice(id);
    },
  });

  return (
    <main>
      <h1>Pay invoice</h1>
      <button
        type="button"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? "Starting payment..." : "Start payment"}
      </button>

      {mutation.isError &&
        (mutation.error instanceof RateLimitedError ? (
          <p role="alert">
            Too many attempts -- try again in {mutation.error.retryAfterSeconds}s.
          </p>
        ) : (
          <p role="alert">Could not start payment. Try again shortly.</p>
        ))}

      {mutation.data && (
        <p>
          Payment intent ready (client_secret received) -- Stripe Elements mount
          pending.
        </p>
      )}
    </main>
  );
}
