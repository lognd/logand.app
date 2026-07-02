import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminCustomers } from "../../src/app/routes/admin/Customers";

// Integration-layer test per docs/design/12: real api/customers.ts
// module, only fetch() is mocked -- proves the confirm-before-deactivate
// flow (the site-wide "confirmations on everything" requirement) fires
// the real request only after an explicit second click, not the first.

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
      <AdminCustomers />
    </QueryClientProvider>,
  );
}

describe("AdminCustomers (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("deactivating a customer requires an explicit confirm click before the real request fires", async () => {
    const customer = { id: "cust-1", email: "alice@example.com" };
    const detail = {
      id: "cust-1",
      email: "alice@example.com",
      role: "customer",
      emails_opted_out: false,
      disabled_at: null,
      created_at: "2026-01-01T00:00:00Z",
    };
    const fetchMock = vi.fn((url: string) => {
      if (url.startsWith("/api/admin/customers/cust-1/deactivate")) {
        return Promise.resolve(jsonResponse({ status: "deactivated" }));
      }
      if (url === "/api/admin/customers/cust-1") {
        return Promise.resolve(jsonResponse(detail));
      }
      if (url.startsWith("/api/admin/customers")) {
        return Promise.resolve(jsonResponse([customer]));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "alice@example.com" }));
    await user.click(
      await screen.findByRole("button", { name: "Deactivate account" }),
    );

    // The confirm step's own text must be visible -- and crucially, no
    // deactivate request has fired yet from the first click alone.
    expect(
      await screen.findByText(/This will immediately prevent/),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).startsWith("/api/admin/customers/cust-1/deactivate"),
      ),
    ).toBe(false);

    await user.click(screen.getByRole("button", { name: "Confirm deactivate" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/admin/customers/cust-1/deactivate",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });
});
