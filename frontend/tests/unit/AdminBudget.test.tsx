import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AdminBudget } from "../../src/app/routes/admin/Budget";
import type { BudgetEntry } from "../../src/api/budget";

// Integration-layer test, same convention as AdminInvoices.test.tsx --
// real api/budget.ts module, only fetch() mocked. Exists specifically to
// guard against reintroducing the bug this test suite caught during a
// real end-to-end pass: createBudgetEntry() sending a JSON body when the
// real backend (api/budget.py's create(), all scalar params) only ever
// accepts query params.

const entry: BudgetEntry = {
  id: "bud-1",
  amount: "42.50",
  category: "supplies",
  vendor: "Acme",
  memo: null,
  occurred_on: "2026-01-01",
  corrects_entry_id: null,
};

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
      <AdminBudget />
    </QueryClientProvider>,
  );
}

describe("AdminBudget (integration)", () => {
  beforeEach(() => {
    document.cookie = "csrf_token=test-csrf";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders real budget entries using occurred_on, not occurredOn", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([entry]));
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(await screen.findByText("2026-01-01")).toBeInTheDocument();
    expect(screen.getByText("42.50")).toBeInTheDocument();
  });

  it("creating an entry sends amount/category/occurred_on as query params, no body", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.startsWith("/api/admin/budget?")) {
        return Promise.resolve(jsonResponse({ id: "bud-new" }));
      }
      return Promise.resolve(jsonResponse([]));
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();

    await user.type(await screen.findByLabelText("Amount"), "42.50");
    await user.type(screen.getByLabelText("Category"), "supplies");
    await user.type(screen.getByLabelText("Date"), "2026-01-01");
    await user.click(screen.getByRole("button", { name: "Add entry" }));

    await waitFor(() => {
      const createCall = fetchMock.mock.calls.find(([url]) =>
        String(url).startsWith("/api/admin/budget?"),
      ) as [string, RequestInit] | undefined;
      expect(createCall).toBeDefined();
      const [url, init] = createCall!;
      expect(url).toBe(
        "/api/admin/budget?amount=42.50&category=supplies&occurred_on=2026-01-01",
      );
      expect(init.body).toBeUndefined();
    });
  });

  it("uploading evidence sends a real multipart FormData body, no JSON Content-Type", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === "/api/admin/budget") {
        return Promise.resolve(jsonResponse([entry]));
      }
      if (url === "/api/admin/budget/bud-1/evidence") {
        return Promise.resolve(jsonResponse({ id: "evi-1" }));
      }
      return Promise.resolve(jsonResponse([]));
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    renderPage();

    const fileInput = await screen.findByLabelText(
      "Upload evidence for entry on 2026-01-01",
    );
    const file = new File(["fake-pdf-bytes"], "receipt.pdf", {
      type: "application/pdf",
    });
    await user.upload(fileInput, file);

    await waitFor(() => {
      const uploadCall = fetchMock.mock.calls.find(
        ([url]) => url === "/api/admin/budget/bud-1/evidence",
      ) as [string, RequestInit] | undefined;
      expect(uploadCall).toBeDefined();
      const [, init] = uploadCall!;
      expect(init.body).toBeInstanceOf(FormData);
      const headers = new Headers(init.headers);
      expect(headers.get("Content-Type")).toBeNull();
    });
  });
});
