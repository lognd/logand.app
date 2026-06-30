// MSW v2 request handlers mirroring the real backend's API surface (see
// docs/design/04/05/06 + backend/src/logand_backend/api/*.py), backed by
// the in-memory fake dataset in ./data.ts. Enabled only when
// VITE_USE_MOCKS=true (see src/mocks/browser.ts and main.tsx) so this code
// never ships in a normal production build.
//
// Session/auth simulation: MSW intercepts fetch() in the browser via a real
// Service Worker, which means a mocked response's Set-Cookie header is NOT
// applied by the browser (the Fetch API forbids scripts -- including
// service workers -- from setting cookies via a synthesized Response).
// So login here does two things instead of relying on Set-Cookie:
//   1. Sets the CSRF cookie directly via `document.cookie` (this works
//      fine -- it's a plain script-set cookie, no Set-Cookie header
//      involved, and src/api/client.ts already reads it that way).
//   2. Tracks "is logged in, as which role" in an in-memory module
//      variable (`currentRole` below), which GET /api/me and every
//      protected handler check instead of a real session cookie.
// This is a mock-only shortcut -- it has no bearing on the real backend's
// HttpOnly-cookie session design in docs/design/02.

import { http, HttpResponse, type DefaultBodyType } from "msw";
import {
  budgetEntries,
  inventoryItems,
  inventoryLocations,
  invoices,
  mockId,
  MOCK_CUSTOMER_ID,
  type MockInvoiceDetail,
} from "./data";
import type { Invoice } from "../api/invoices";
import type { BudgetEntry } from "../api/budget";
import type { InventoryItem } from "../api/inventory";

type Role = "admin" | "customer" | null;

// MSW v2's browser handlers run in the page's own JS context (the generated
// mockServiceWorker.js is a thin postMessage proxy, not where handler code
// executes) -- so a plain module variable here is wiped by any full page
// reload. The real backend persists sessions via an HttpOnly cookie that
// survives reloads; sessionStorage is the closest mock-mode equivalent so a
// manual browser refresh during preview doesn't surprise-logout the user.
function readCurrentRole(): Role {
  const stored = sessionStorage.getItem("mock-role");
  return stored === "admin" || stored === "customer" ? stored : null;
}

function writeCurrentRole(role: Role): void {
  if (role === null) {
    sessionStorage.removeItem("mock-role");
  } else {
    sessionStorage.setItem("mock-role", role);
  }
}

const MOCK_ADMIN_EMAIL = "admin@logand.app";
const MOCK_CUSTOMER_EMAIL = "customer@example.com";

function setMockCsrfCookie(): void {
  document.cookie = "csrf_token=mock-csrf-token; path=/";
}

function clearMockCsrfCookie(): void {
  document.cookie = "csrf_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}

function requireRole(role: Exclude<Role, null>): HttpResponse<DefaultBodyType> | null {
  if (readCurrentRole() !== role) {
    return HttpResponse.json({ detail: "unauthenticated (mock)" }, { status: 401 });
  }
  return null;
}

function toListShape(inv: MockInvoiceDetail): Invoice {
  const { id, status, amountTotal, currency, memo, dueDate } = inv;
  return { id, status, amountTotal, currency, memo, dueDate };
}

export const handlers = [
  // -- auth --------------------------------------------------------------
  http.post("/api/auth/login", async ({ request }) => {
    const body = (await request.json()) as { email: string; password: string };
    if (body.email === MOCK_ADMIN_EMAIL) {
      writeCurrentRole("admin");
    } else if (body.email === MOCK_CUSTOMER_EMAIL) {
      writeCurrentRole("customer");
    } else {
      return HttpResponse.json({ detail: "invalid credentials" }, { status: 401 });
    }
    setMockCsrfCookie();
    return HttpResponse.json({ status: "ok" });
  }),

  http.post("/api/auth/logout", () => {
    writeCurrentRole(null);
    clearMockCsrfCookie();
    return HttpResponse.json({ status: "ok" });
  }),

  http.get("/api/me", () => {
    const currentRole = readCurrentRole();
    if (currentRole === null) {
      return HttpResponse.json({ detail: "unauthenticated (mock)" }, { status: 401 });
    }
    return HttpResponse.json({
      id: currentRole === "admin" ? "mock-admin-id" : MOCK_CUSTOMER_ID,
      email: currentRole === "admin" ? MOCK_ADMIN_EMAIL : MOCK_CUSTOMER_EMAIL,
      role: currentRole,
    });
  }),

  // -- customer invoices ---------------------------------------------------
  http.get("/api/invoices", () => {
    const denied = requireRole("customer");
    if (denied) return denied;
    return HttpResponse.json(invoices.map(toListShape));
  }),

  http.get("/api/invoices/:id", ({ params }) => {
    const denied = requireRole("customer");
    if (denied) return denied;
    const invoice = invoices.find((i) => i.id === params.id);
    if (!invoice) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    return HttpResponse.json(toListShape(invoice));
  }),

  http.post("/api/invoices/:id/pay", ({ params }) => {
    const denied = requireRole("customer");
    if (denied) return denied;
    const invoice = invoices.find((i) => i.id === params.id);
    if (!invoice) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    // Real Stripe Elements aren't mounted in mock mode -- return a fake
    // client_secret shaped like the real response so the calling code path
    // still exercises normally.
    return HttpResponse.json({ clientSecret: "pi_mock_secret_" + invoice.id });
  }),

  // -- admin invoices --------------------------------------------------
  http.get("/api/admin/invoices", () => {
    const denied = requireRole("admin");
    if (denied) return denied;
    return HttpResponse.json(invoices.map(toListShape));
  }),

  http.get("/api/admin/invoices/:id", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const invoice = invoices.find((i) => i.id === params.id);
    if (!invoice) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    return HttpResponse.json(invoice);
  }),

  http.post("/api/admin/invoices", async ({ request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const body = (await request.json()) as {
      customerId?: string;
      memo?: string | null;
      lineItems?: { description: string; quantity: string; unitPrice: string }[];
    };
    const lineItems = (body.lineItems ?? []).map((li) => ({
      id: mockId("li"),
      description: li.description,
      quantity: li.quantity,
      unitPrice: li.unitPrice,
    }));
    const amountTotal = lineItems
      .reduce((sum, li) => sum + Number(li.quantity) * Number(li.unitPrice), 0)
      .toFixed(2);
    const invoice: MockInvoiceDetail = {
      id: mockId("inv"),
      customerId: body.customerId ?? MOCK_CUSTOMER_ID,
      status: "draft",
      amountTotal,
      currency: "usd",
      memo: body.memo ?? null,
      dueDate: null,
      isRecurring: false,
      lineItems,
      payments: [],
    };
    invoices.push(invoice);
    return HttpResponse.json({ id: invoice.id }, { status: 201 });
  }),

  http.post("/api/admin/invoices/:id/send", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const invoice = invoices.find((i) => i.id === params.id);
    if (!invoice) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    invoice.status = "sent";
    return HttpResponse.json(toListShape(invoice));
  }),

  http.post("/api/admin/invoices/:id/void", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const invoice = invoices.find((i) => i.id === params.id);
    if (!invoice) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    invoice.status = "void";
    return HttpResponse.json(toListShape(invoice));
  }),

  // -- admin budget ------------------------------------------------------
  http.get("/api/admin/budget", () => {
    const denied = requireRole("admin");
    if (denied) return denied;
    return HttpResponse.json(budgetEntries);
  }),

  http.post("/api/admin/budget", async ({ request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const body = (await request.json()) as Omit<BudgetEntry, "id">;
    const entry: BudgetEntry = { id: mockId("bud"), ...body };
    budgetEntries.push(entry);
    return HttpResponse.json({ id: entry.id }, { status: 201 });
  }),

  http.post("/api/admin/budget/:id/evidence", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const entry = budgetEntries.find((b) => b.id === params.id);
    if (!entry) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    return HttpResponse.json({ id: mockId("evi") }, { status: 201 });
  }),

  http.get("/api/admin/budget/export", () => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const header = "id,occurred_on,category,vendor,amount,memo";
    const rows = budgetEntries.map(
      (b) =>
        `${b.id},${b.occurredOn},${b.category},${b.vendor ?? ""},${b.amount},${b.memo ?? ""}`,
    );
    return new HttpResponse<BodyInit>([header, ...rows].join("\n"), {
      headers: {
        "Content-Type": "text/csv",
        "Content-Disposition": "attachment; filename=budget_export.csv",
      },
    });
  }),

  // -- admin inventory ---------------------------------------------------
  http.get("/api/admin/inventory/locations", () => {
    const denied = requireRole("admin");
    if (denied) return denied;
    return HttpResponse.json(inventoryLocations);
  }),

  http.post("/api/admin/inventory/locations", async ({ request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const body = (await request.json()) as {
      name: string;
      description?: string | null;
    };
    const location = {
      id: mockId("loc"),
      name: body.name,
      description: body.description ?? null,
    };
    inventoryLocations.push(location);
    return HttpResponse.json({ id: location.id }, { status: 201 });
  }),

  http.get("/api/admin/inventory/items", ({ request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const url = new URL(request.url);
    const q = url.searchParams.get("q")?.toLowerCase();
    const locationId = url.searchParams.get("location_id");
    const tag = url.searchParams.get("tag");
    let results: InventoryItem[] = inventoryItems;
    if (locationId) results = results.filter((i) => i.locationId === locationId);
    if (tag) results = results.filter((i) => i.tags.includes(tag));
    if (q) {
      results = results.filter(
        (i) =>
          i.name.toLowerCase().includes(q) ||
          (i.description ?? "").toLowerCase().includes(q),
      );
    }
    return HttpResponse.json(results);
  }),

  http.post("/api/admin/inventory/items", async ({ request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const body = (await request.json()) as Omit<InventoryItem, "id">;
    const item: InventoryItem = { id: mockId("item"), ...body };
    inventoryItems.push(item);
    return HttpResponse.json({ id: item.id }, { status: 201 });
  }),

  http.patch("/api/admin/inventory/items/:id", async ({ params, request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const item = inventoryItems.find((i) => i.id === params.id);
    if (!item) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    const body = (await request.json()) as Partial<InventoryItem>;
    if (body.locationId !== undefined) item.locationId = body.locationId;
    if (body.quantity !== undefined) item.quantity = body.quantity;
    return HttpResponse.json({ status: "ok" });
  }),

  http.delete("/api/admin/inventory/items/:id", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const index = inventoryItems.findIndex((i) => i.id === params.id);
    if (index === -1)
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    inventoryItems.splice(index, 1);
    return HttpResponse.json({ status: "deleted" });
  }),
];
