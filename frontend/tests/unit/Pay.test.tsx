import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/invoices/inv-1/pay"]}>
        <Routes>
          <Route path="/invoices/:id/pay" element={<CustomerPay />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CustomerPay (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the real configured Zelle handle", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ stripe: true, paypal: false, zelle_handle: "logan@logand.app" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(await screen.findByText("logan@logand.app")).toBeInTheDocument();
  });

  it("does not show a Zelle line when unconfigured", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ stripe: true, paypal: false, zelle_handle: null }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    await screen.findByText("Other ways to pay");
    expect(screen.queryByText(/Zelle:/)).not.toBeInTheDocument();
  });

  it("uploading a proof file sends a real multipart request to the real endpoint", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/invoices/payment-methods") {
        return Promise.resolve(
          jsonResponse({ stripe: true, paypal: false, zelle_handle: "logan@logand.app" }),
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
    expect(
      await screen.findByText(/Uploaded\. We'll take a look/),
    ).toBeInTheDocument();
  });
});
