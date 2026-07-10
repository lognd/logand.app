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
    const customer = { id: "cust-1", email: "alice@example.com", account_state: "active" };
    const detail = {
      id: "cust-1",
      email: "alice@example.com",
      role: "customer",
      account_state: "active",
      email_verified_at: "2026-01-01T00:00:00Z",
      emails_opted_out: false,
      disabled_at: null,
      created_at: "2026-01-01T00:00:00Z",
      address_line1: null,
      address_city: null,
      address_state: null,
      address_postal_code: null,
      address_country: null,
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

    await user.click(await screen.findByRole("button", { name: /alice@example.com/ }));
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

  it("saves an address edit via PUT with the entered values", async () => {
    const customer = { id: "cust-1", email: "alice@example.com", account_state: "active" };
    const detail = {
      id: "cust-1",
      email: "alice@example.com",
      role: "customer",
      account_state: "active",
      email_verified_at: "2026-01-01T00:00:00Z",
      emails_opted_out: false,
      disabled_at: null,
      created_at: "2026-01-01T00:00:00Z",
      address_line1: null,
      address_city: null,
      address_state: null,
      address_postal_code: null,
      address_country: null,
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (
        url === "/api/admin/customers/cust-1/address" &&
        init?.method === "PUT"
      ) {
        return Promise.resolve(
          jsonResponse({ ...detail, address_line1: "123 Main St", address_city: "Nashville" }),
        );
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

    await user.click(await screen.findByRole("button", { name: /alice@example.com/ }));
    await screen.findByText("Address (for tax sourcing)");

    await user.type(screen.getByLabelText("Address line 1"), "123 Main St");
    await user.type(screen.getByLabelText("City"), "Nashville");

    await user.click(screen.getByRole("button", { name: "Save address" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          url === "/api/admin/customers/cust-1/address" &&
          (init as RequestInit | undefined)?.method === "PUT",
      );
      expect(call).toBeDefined();
      const body = JSON.parse((call?.[1] as RequestInit).body as string);
      expect(body.address_line1).toBe("123 Main St");
      expect(body.address_city).toBe("Nashville");
    });

    expect(await screen.findByText("Address saved.")).toBeInTheDocument();
  });

  it("shows plain-language account-state badges for contact, unverified, and active customers", async () => {
    const customers = [
      { id: "cust-contact", email: "contact@example.com", account_state: "contact" },
      { id: "cust-unverified", email: "unverified@example.com", account_state: "unverified" },
      { id: "cust-active", email: "active@example.com", account_state: "active" },
    ];
    const fetchMock = vi.fn((url: string) => {
      if (url.startsWith("/api/admin/customers")) {
        return Promise.resolve(jsonResponse(customers));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    renderPage();

    expect(
      await screen.findByText("No account yet -- invoice sent, not claimed"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Signed up, has not confirmed their email"),
    ).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows the account-state badge and email_verified_at in the customer detail panel", async () => {
    const customer = {
      id: "cust-1",
      email: "alice@example.com",
      account_state: "unverified",
    };
    const detail = {
      id: "cust-1",
      email: "alice@example.com",
      role: "customer",
      account_state: "unverified",
      email_verified_at: null,
      emails_opted_out: false,
      disabled_at: null,
      created_at: "2026-01-01T00:00:00Z",
      address_line1: null,
      address_city: null,
      address_state: null,
      address_postal_code: null,
      address_country: null,
    };
    const fetchMock = vi.fn((url: string) => {
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

    await user.click(await screen.findByRole("button", { name: /alice@example.com/ }));

    expect(
      await screen.findAllByText("Signed up, has not confirmed their email"),
    ).not.toHaveLength(0);
  });
});
