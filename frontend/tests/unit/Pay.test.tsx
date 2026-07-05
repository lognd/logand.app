import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

// Integration-layer test per docs/design/12: real api/invoices.ts
// module, only fetch() is mocked -- proves the upload UI, the real
// multipart FormData request, and the Zelle-handle display all work
// together against the real API module's request shaping.
//
// Stripe's OWN libraries are the one exception: Payment Element lives
// in Stripe-hosted iframes talking to Stripe's servers, which no test
// double can stand in for -- so the stripe-js boundary is mocked and
// these tests own everything up to it (intent creation, form mount,
// confirm call shape, outcome/error rendering, redirect returns).
const { confirmPaymentMock } = vi.hoisted(() => ({ confirmPaymentMock: vi.fn() }));
vi.mock("@stripe/stripe-js", () => ({
  loadStripe: vi.fn(() => Promise.resolve({})),
}));
vi.mock("@stripe/react-stripe-js", () => ({
  Elements: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  PaymentElement: () => <div data-testid="payment-element" />,
  useStripe: () => ({ confirmPayment: confirmPaymentMock }),
  useElements: () => ({}),
}));

import { CustomerPay, stripeAppearance } from "../../src/app/routes/customer/Pay";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

// What a Stripe-configured backend's payment-methods route returns --
// most tests here want the card button visible.
const PAYMENT_METHODS = {
  stripe: true,
  stripe_publishable_key: "pk_test_fake",
  paypal: false,
  zelle_handle: null,
  paypal_receive_email: null,
};

const SENT_INVOICE = {
  id: "inv-1",
  status: "sent",
  amount_total: "42.00",
  currency: "usd",
  memo: null,
  due_date: null,
  paid_at: null,
};

function renderPage(initialEntries: string[] = ["/invoices/inv-1/pay"]) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  let lastSearch = "";
  function LocationProbe() {
    const [params] = useSearchParams();
    lastSearch = params.toString();
    return null;
  }
  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <LocationProbe />
        <Routes>
          <Route path="/invoices/:id/pay" element={<CustomerPay />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, getLastSearch: () => lastSearch };
}

describe("CustomerPay (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    confirmPaymentMock.mockReset();
  });

  it("shows the real configured Zelle handle", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(
        jsonResponse({ ...PAYMENT_METHODS, zelle_handle: "logan@logand.app" }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(await screen.findByText("logan@logand.app")).toBeInTheDocument();
  });

  it("shows the configured PayPal email, labeled distinctly from Zelle", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(
        jsonResponse({
          ...PAYMENT_METHODS,
          zelle_handle: "logan@logand.app",
          paypal_receive_email: "paypal@logand.app",
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    // Both are emails, so the "Zelle:" / "PayPal:" labels are what tell a
    // customer which address goes with which service -- assert the labels
    // sit with the right address, not just that the address appears.
    const zelleLine = (await screen.findByText(/Zelle:/)).closest("p");
    expect(zelleLine).toHaveTextContent("logan@logand.app");
    const paypalLine = screen.getByText(/PayPal:/).closest("p");
    expect(paypalLine).toHaveTextContent("paypal@logand.app");
  });

  it("does not show a PayPal line when the receive email is unconfigured", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(jsonResponse(PAYMENT_METHODS));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    await screen.findByText("Other ways to pay");
    expect(screen.queryByText(/PayPal:/)).not.toBeInTheDocument();
  });

  it("does not show a Zelle line when unconfigured", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(
        jsonResponse(PAYMENT_METHODS),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    await screen.findByText("Other ways to pay");
    expect(screen.queryByText(/Zelle:/)).not.toBeInTheDocument();
  });

  it("uploading a proof file sends a real multipart request to the real endpoint", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      if (url === "/api/invoices/payment-methods") {
        return Promise.resolve(
          jsonResponse({ ...PAYMENT_METHODS, zelle_handle: "logan@logand.app" }),
        );
      }
      if (url === "/api/invoices/inv-1/payment-proof") {
        return Promise.resolve(jsonResponse({ id: "proof-1" }));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    const fileInput = await screen.findByLabelText(
      /Already sent it\? Upload a screenshot as proof/,
    );
    const file = new File(["fake-bytes"], "zelle.png", { type: "image/png" });
    await user.upload(fileInput, file);
    await user.click(screen.getByRole("button", { name: "Upload proof" }));

    await waitFor(() => {
      const uploadCall = fetchMock.mock.calls.find(
        ([url]) => url === "/api/invoices/inv-1/payment-proof",
      ) as [string, RequestInit] | undefined;
      expect(uploadCall).toBeDefined();
      const [, init] = uploadCall!;
      // A real FormData body, not JSON -- the whole point of this test.
      expect(init.body).toBeInstanceOf(FormData);
      expect((init.body as FormData).get("file")).toBe(file);
    });
    expect(await screen.findByText(/Uploaded\. We'll take a look/)).toBeInTheDocument();
  });

  it("hides the pay buttons and shows a status message for an already-paid invoice", async () => {
    // Regression test for FE2.
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(
          jsonResponse({
            ...SENT_INVOICE,
            status: "paid",
            paid_at: "2026-01-01T00:00:00Z",
          }),
        );
      }
      return Promise.resolve(
        jsonResponse(PAYMENT_METHODS),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(
      await screen.findByText("This invoice has already been paid. Thank you!"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Pay with card" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    ["void", "This invoice has been voided and is no longer payable."],
    ["draft", "This invoice isn't ready to be paid yet."],
  ])("shows the right status message for a %s invoice", async (status, message) => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse({ ...SENT_INVOICE, status }));
      }
      return Promise.resolve(jsonResponse(PAYMENT_METHODS));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Pay with card" }),
    ).not.toBeInTheDocument();
  });

  it("shows pay buttons for a sent invoice", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(
        jsonResponse(PAYMENT_METHODS),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(
      await screen.findByRole("button", { name: "Pay with card" }),
    ).toBeInTheDocument();
  });

  it("strips the PayPal return token from the URL after firing capture", async () => {
    // Regression test for FE3: a reload/back-navigation while ?token=
    // is still present would re-fire capture against the same order.
    // The page must strip the token from the URL right after starting
    // the capture request.
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1/pay/paypal/capture") {
        return Promise.resolve(jsonResponse({ status: "captured" }));
      }
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse({ ...SENT_INVOICE, status: "paid" }));
      }
      return Promise.resolve(
        jsonResponse(PAYMENT_METHODS),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const { getLastSearch } = renderPage(["/invoices/inv-1/pay?token=FAKE-ORDER-1"]);

    expect(await screen.findByText("Payment received. Thank you!")).toBeInTheDocument();
    await waitFor(() => {
      expect(getLastSearch()).not.toContain("token");
    });
    // The capture-status page keeps showing even though the token has
    // been stripped from the URL -- must not flip back to the "pay
    // buttons" branch mid/post-capture.
    expect(
      screen.queryByRole("button", { name: "Pay with card" }),
    ).not.toBeInTheDocument();
  });

  it("a pending PayPal capture shows the under-review message", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1/pay/paypal/capture") {
        return Promise.resolve(jsonResponse({ status: "pending" }));
      }
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(jsonResponse(PAYMENT_METHODS));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage(["/invoices/inv-1/pay?token=FAKE-ORDER-1"]);

    expect(
      await screen.findByText(/being reviewed by PayPal/),
    ).toBeInTheDocument();
  });

  it("a failed PayPal capture shows the contact-us error", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1/pay/paypal/capture") {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: "capture failed" }), {
            status: 502,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(jsonResponse(PAYMENT_METHODS));
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage(["/invoices/inv-1/pay?token=FAKE-ORDER-1"]);

    expect(
      await screen.findByText(/Could not confirm your PayPal payment/),
    ).toBeInTheDocument();
  });

  // -- Stripe card flow ----------------------------------------------------

  // Handles the three requests every card-flow test makes: the invoice,
  // payment-methods, and the intent-minting POST /pay.
  function cardFlowFetchMock() {
    return vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/invoices/inv-1/pay" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ client_secret: "pi_1_secret_test" }));
      }
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(jsonResponse(PAYMENT_METHODS));
    });
  }

  it("hides the card button when the backend has no publishable key", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(
        jsonResponse({
          ...PAYMENT_METHODS,
          stripe: false,
          stripe_publishable_key: null,
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    // The manual-payment fallback must still render -- the page is never
    // a dead end even with no self-serve processor configured at all.
    await screen.findByText("Other ways to pay");
    expect(
      screen.queryByRole("button", { name: "Pay with card" }),
    ).not.toBeInTheDocument();
  });

  it("clicking Pay with card mints an intent and mounts the card form", async () => {
    const fetchMock = cardFlowFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Pay with card" }));

    expect(await screen.findByTestId("payment-element")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pay now" })).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) => url === "/api/invoices/inv-1/pay" && init?.method === "POST",
      ),
    ).toBe(true);
  });

  it("a successful inline confirm shows the success message", async () => {
    confirmPaymentMock.mockResolvedValue({ paymentIntent: { status: "succeeded" } });
    vi.stubGlobal("fetch", cardFlowFetchMock());
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Pay with card" }));
    await user.click(await screen.findByRole("button", { name: "Pay now" }));

    expect(await screen.findByText("Payment received. Thank you!")).toBeInTheDocument();
    // The confirm call must carry the elements instance, land back on
    // THIS page if a redirect-based method needs it, and stay inline
    // otherwise -- the exact contract CardPaymentForm owns.
    expect(confirmPaymentMock).toHaveBeenCalledWith(
      expect.objectContaining({
        confirmParams: {
          return_url: expect.stringContaining("/invoices/inv-1/pay"),
        },
        redirect: "if_required",
      }),
    );
  });

  it("a declined card shows Stripe's own message and allows retrying", async () => {
    confirmPaymentMock.mockResolvedValue({
      error: { type: "card_error", message: "Your card was declined." },
    });
    vi.stubGlobal("fetch", cardFlowFetchMock());
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Pay with card" }));
    await user.click(await screen.findByRole("button", { name: "Pay now" }));

    expect(await screen.findByText("Your card was declined.")).toBeInTheDocument();
    // Still on the form, ready for another attempt -- a decline is not a
    // terminal state.
    expect(screen.getByRole("button", { name: "Pay now" })).toBeInTheDocument();
  });

  it("a succeeded redirect return shows success and strips Stripe's params", async () => {
    vi.stubGlobal("fetch", cardFlowFetchMock());

    const { getLastSearch } = renderPage([
      "/invoices/inv-1/pay?payment_intent=pi_1&payment_intent_client_secret=cs_test&redirect_status=succeeded",
    ]);

    expect(await screen.findByText("Payment received. Thank you!")).toBeInTheDocument();
    await waitFor(() => {
      expect(getLastSearch()).toBe("");
    });
    expect(
      screen.queryByRole("button", { name: "Pay with card" }),
    ).not.toBeInTheDocument();
  });

  it("a processing inline confirm shows the pending message, not success", async () => {
    confirmPaymentMock.mockResolvedValue({ paymentIntent: { status: "processing" } });
    vi.stubGlobal("fetch", cardFlowFetchMock());
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Pay with card" }));
    await user.click(await screen.findByRole("button", { name: "Pay now" }));

    expect(
      await screen.findByText(/Your payment is processing/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Payment received. Thank you!")).not.toBeInTheDocument();
  });

  it("a non-card confirm error shows the generic message, not Stripe internals", async () => {
    // api_error/network messages are written for developers, not
    // customers -- they must never be shown verbatim.
    confirmPaymentMock.mockResolvedValue({
      error: { type: "api_error", message: "No such payment_intent: pi_1" },
    });
    vi.stubGlobal("fetch", cardFlowFetchMock());
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Pay with card" }));
    await user.click(await screen.findByRole("button", { name: "Pay now" }));

    expect(
      await screen.findByText(/Something went wrong confirming your payment/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/No such payment_intent/)).not.toBeInTheDocument();
  });

  it("a card error without a message falls back to a usable line", async () => {
    confirmPaymentMock.mockResolvedValue({ error: { type: "card_error" } });
    vi.stubGlobal("fetch", cardFlowFetchMock());
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Pay with card" }));
    await user.click(await screen.findByRole("button", { name: "Pay now" }));

    expect(
      await screen.findByText("Your card could not be charged. Try again."),
    ).toBeInTheDocument();
  });

  it("a rate-limited intent request shows the retry-after message", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/invoices/inv-1/pay" && init?.method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: "rate limited" }), {
            status: 429,
            headers: { "Retry-After": "30", "Content-Type": "application/json" },
          }),
        );
      }
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(jsonResponse(PAYMENT_METHODS));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Pay with card" }));

    expect(
      await screen.findByText(/Too many attempts -- try again in 30s/),
    ).toBeInTheDocument();
    // No client_secret means no card form to mount.
    expect(screen.queryByTestId("payment-element")).not.toBeInTheDocument();
  });

  it("a failed intent request shows the generic start-payment error", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/invoices/inv-1/pay" && init?.method === "POST") {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: "boom" }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(jsonResponse(PAYMENT_METHODS));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Pay with card" }));

    expect(
      await screen.findByText("Could not start payment. Try again shortly."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("payment-element")).not.toBeInTheDocument();
  });

  it("mounting the card form replaces the pay buttons, PayPal included", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/invoices/inv-1/pay" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ client_secret: "pi_1_secret_test" }));
      }
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(jsonResponse({ ...PAYMENT_METHODS, paypal: true }));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    // Both self-serve options offered up front...
    expect(
      await screen.findByRole("button", { name: "Pay with PayPal" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pay with card" }));

    // ...but once the customer committed to the card path, the buttons
    // give way to the form -- no second payment path left clickable
    // mid-checkout.
    await screen.findByTestId("payment-element");
    expect(
      screen.queryByRole("button", { name: "Pay with card" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Pay with PayPal" }),
    ).not.toBeInTheDocument();
  });

  it("a processing redirect return shows the pending message and strips params", async () => {
    vi.stubGlobal("fetch", cardFlowFetchMock());

    const { getLastSearch } = renderPage([
      "/invoices/inv-1/pay?payment_intent=pi_1&payment_intent_client_secret=cs_test&redirect_status=processing",
    ]);

    expect(
      await screen.findByText(/Your payment is processing/),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(getLastSearch()).toBe("");
    });
  });

  it("a failed redirect return warns but leaves the pay buttons usable", async () => {
    vi.stubGlobal("fetch", cardFlowFetchMock());

    renderPage([
      "/invoices/inv-1/pay?payment_intent=pi_1&payment_intent_client_secret=cs_test&redirect_status=failed",
    ]);

    expect(
      await screen.findByText(/Your payment was not completed/),
    ).toBeInTheDocument();
    // Failure is retryable -- the normal payable page (card button
    // included) must still be offered underneath the warning.
    expect(
      await screen.findByRole("button", { name: "Pay with card" }),
    ).toBeInTheDocument();
  });
});

describe("stripeAppearance", () => {
  // Regression test for FINDINGS.md L1: a desynced/renamed CSS custom
  // property must not silently feed Stripe an empty-string color -- it
  // should fall back to a real hex default instead.
  it("falls back to a hardcoded default when a CSS token resolves empty", () => {
    const style = document.createElement("style");
    style.textContent = ":root { --bg-secondary: #123456; --fg-primary: #abcdef; }";
    document.head.appendChild(style);

    const appearance = stripeAppearance();

    expect(appearance.variables?.colorBackground).toBe("#123456");
    expect(appearance.variables?.colorText).toBe("#abcdef");
    // --accent-orange, --fg-muted, --accent-red were never set above --
    // must resolve to non-empty fallback values, never "".
    expect(appearance.variables?.colorPrimary).not.toBe("");
    expect(appearance.variables?.colorTextSecondary).not.toBe("");
    expect(appearance.variables?.colorDanger).not.toBe("");

    document.head.removeChild(style);
  });
});
