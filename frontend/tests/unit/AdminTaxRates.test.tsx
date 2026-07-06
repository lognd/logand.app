import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminTaxRates } from "../../src/app/routes/admin/TaxRates";
import type { TaxRule } from "../../src/api/tax";

// Integration-layer test per docs/design/12: real api/tax.ts module, only
// fetch() is mocked.

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminTaxRates />
    </QueryClientProvider>,
  );
}

const rule: TaxRule = {
  id: "rule-1",
  jurisdiction: "US-TN",
  tax_type: "sales",
  category: "*",
  rate: "0.07",
  source: "TN DOR 2026",
  citation_url: "https://www.tn.gov/revenue.html",
  effective_from: "2026-07-01T00:00:00Z",
};

describe("AdminTaxRates (integration)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists a current rule including its citation link", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse([rule])));
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    renderPage();

    expect(await screen.findByText("US-TN")).toBeInTheDocument();
    expect(screen.getByText("7%")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "source" });
    expect(link).toHaveAttribute("href", "https://www.tn.gov/revenue.html");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("submits the add form with the correct body", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/admin/tax/rules" && init?.method === "POST") {
        return Promise.resolve(jsonResponse(rule));
      }
      return Promise.resolve(jsonResponse([]));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await screen.findByText("No rates entered yet.");

    await user.type(screen.getByLabelText("Jurisdiction (e.g. US-TN)"), "US-TN");
    await user.type(screen.getByLabelText("Rate (percent, e.g. 7 for 7%)"), "7");
    await user.type(screen.getByLabelText("Source"), "TN DOR 2026");
    await user.type(
      screen.getByLabelText(
        "Government source URL (.gov/.mil/.us or an allowlisted state site)",
      ),
      "https://www.tn.gov/revenue.html",
    );

    await user.click(screen.getByRole("button", { name: "Add rate" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([url, init]) =>
          url === "/api/admin/tax/rules" &&
          (init as RequestInit | undefined)?.method === "POST",
      );
      expect(call).toBeDefined();
      const body = JSON.parse((call?.[1] as RequestInit).body as string);
      expect(body).toEqual({
        jurisdiction: "US-TN",
        tax_type: "sales",
        category: "*",
        rate: "0.07",
        source: "TN DOR 2026",
        citation_url: "https://www.tn.gov/revenue.html",
      });
    });
  });

  it("shows the server's error message on a 400", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/admin/tax/rules" && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse(
            { detail: "citation_url is not a recognized government source" },
            400,
          ),
        );
      }
      return Promise.resolve(jsonResponse([]));
    });
    vi.stubGlobal("fetch", fetchMock);
    document.cookie = "csrf_token=test-csrf";

    const user = userEvent.setup();
    renderPage();

    await screen.findByText("No rates entered yet.");

    await user.type(screen.getByLabelText("Jurisdiction (e.g. US-TN)"), "US-TN");
    await user.type(screen.getByLabelText("Rate (percent, e.g. 7 for 7%)"), "7");
    await user.type(screen.getByLabelText("Source"), "some blog");
    await user.type(
      screen.getByLabelText(
        "Government source URL (.gov/.mil/.us or an allowlisted state site)",
      ),
      "https://example.com",
    );

    await user.click(screen.getByRole("button", { name: "Add rate" }));

    expect(
      await screen.findByText("citation_url is not a recognized government source"),
    ).toBeInTheDocument();
  });
});
