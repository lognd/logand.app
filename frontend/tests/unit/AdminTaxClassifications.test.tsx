import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminTaxClassifications } from "../../src/app/routes/admin/TaxClassifications";
import type { TaxClassification } from "../../src/api/tax";

// Integration-layer test per docs/design/12: real api/tax.ts module, only
// fetch() is mocked -- proves the pending-review table, confirm action, and
// override form all shape their requests correctly.

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
      <AdminTaxClassifications />
    </QueryClientProvider>,
  );
}

const pendingRow: TaxClassification = {
  id: "cls-1",
  normalized_key: "widget xl",
  description: "Widget XL",
  category: "tangible-goods",
  taxable: true,
  hts_code: "9999.00.00",
  status: "pending",
  source: "model",
  model: "claude-sonnet-5",
  rationale: "Physical good sold to end consumer.",
  confirmed_at: null,
  updated_at: "2026-07-01T00:00:00Z",
};

describe("AdminTaxClassifications (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders a pending classification and confirms it", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (
        url.startsWith("/api/admin/tax/classifications/widget%20xl/confirm") &&
        init?.method === "POST"
      ) {
        return Promise.resolve(
          jsonResponse({ ...pendingRow, status: "confirmed" }),
        );
      }
      if (url.startsWith("/api/admin/tax/classifications")) {
        return Promise.resolve(jsonResponse([pendingRow]));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("Widget XL")).toBeInTheDocument();
    expect(screen.getByText("tangible-goods")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url, init]) =>
          String(url).startsWith(
            "/api/admin/tax/classifications/widget%20xl/confirm",
          ) && (init as RequestInit | undefined)?.method === "POST",
        ),
      ).toBe(true);
    });
  });

  it("submits an override with the edited fields", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (
        url.startsWith("/api/admin/tax/classifications/widget%20xl/override") &&
        init?.method === "POST"
      ) {
        return Promise.resolve(
          jsonResponse({ ...pendingRow, status: "overridden", category: "services" }),
        );
      }
      if (url.startsWith("/api/admin/tax/classifications")) {
        return Promise.resolve(jsonResponse([pendingRow]));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Widget XL");
    await user.click(screen.getByRole("button", { name: "Override" }));

    const categoryInput = screen.getByDisplayValue("tangible-goods");
    await user.clear(categoryInput);
    await user.type(categoryInput, "services");

    await user.click(screen.getByRole("button", { name: "Save override" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) =>
        String(url).startsWith(
          "/api/admin/tax/classifications/widget%20xl/override",
        ),
      );
      expect(call).toBeDefined();
      const body = JSON.parse((call?.[1] as RequestInit).body as string);
      expect(body.category).toBe("services");
      expect(body.taxable).toBe(true);
    });
  });
});
