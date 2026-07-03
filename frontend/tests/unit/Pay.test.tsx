import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useSearchParams } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CustomerPay } from "../../src/app/routes/customer/Pay";

// Integration-layer test per docs/design/12: real api/invoices.ts
// module, only fetch() is mocked -- proves the upload UI, the real
// multipart FormData request, and the Zelle-handle display all work
// together against the real API module's request shaping.

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

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
  });

  it("shows the real configured Zelle handle", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(
        jsonResponse({ stripe: true, paypal: false, zelle_handle: "logan@logand.app" }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(await screen.findByText("logan@logand.app")).toBeInTheDocument();
  });

  it("does not show a Zelle line when unconfigured", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(
        jsonResponse({ stripe: true, paypal: false, zelle_handle: null }),
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
          jsonResponse({
            stripe: true,
            paypal: false,
            zelle_handle: "logan@logand.app",
          }),
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
        jsonResponse({ stripe: true, paypal: false, zelle_handle: null }),
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

  it("shows pay buttons for a sent invoice", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/inv-1") {
        return Promise.resolve(jsonResponse(SENT_INVOICE));
      }
      return Promise.resolve(
        jsonResponse({ stripe: true, paypal: false, zelle_handle: null }),
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
        jsonResponse({ stripe: true, paypal: false, zelle_handle: null }),
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
});
