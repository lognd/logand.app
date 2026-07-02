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

// item_id -> its adjustment history, newest first -- module-level (not
// part of data.ts's InventoryItem fixtures) since it's a separate table
// on the real backend (InventoryAdjustment), not a field on the item
// itself.
const inventoryAdjustments = new Map<
  string,
  {
    id: string;
    delta: number;
    quantity_before: number;
    quantity_after: number;
    reason: string;
    adjusted_by: string | null;
    created_at: string;
  }[]
>();

interface MockAdminDataChange {
  id: string;
  admin_id: string | null;
  action: string;
  target_table: string;
  target_id: string;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  created_at: string;
}

const adminDataChanges: MockAdminDataChange[] = [];

interface MockBom {
  id: string;
  name: string;
  description: string | null;
  labor_hours: string;
  labor_rate: string;
  overhead_percent: string;
}

// A real, working starter BOM in mock mode -- resistor assortment from
// inventoryItems above (which has a real unit_cost) -- so "Import from
// BOM" and the /admin/boms page both have something real to demo without
// an admin needing to create one from scratch first.
const boms: MockBom[] = [
  {
    id: "bom-001",
    name: "Sample PCB",
    description: "Demo BOM for mock mode",
    labor_hours: "1.5",
    labor_rate: "35.00",
    overhead_percent: "12.00",
  },
];

// bom_id -> its material lines -- separate from the boms array itself,
// same real-table-not-a-field reasoning as inventoryAdjustments above.
const bomMaterialLines = new Map<
  string,
  { item_id: string; quantity_per_unit: number }[]
>([["bom-001", [{ item_id: "item-001", quantity_per_unit: 25 }]]]);

// invoice_id -> its uploaded payment-proof records, newest first --
// same real-table-not-a-field reasoning as inventoryAdjustments/
// bomMaterialLines above.
const paymentProofs = new Map<
  string,
  { id: string; content_type: string; created_at: string }[]
>();

// customer id -> the ISO timestamp it was deactivated at -- absent means
// active. Same real-table-not-a-field reasoning as the other mock state
// maps above.
const disabledCustomers = new Map<string, string>();

const MOCK_ADMIN_EMAIL = "admin@logand.app";
const MOCK_CUSTOMER_EMAIL = "customer@example.com";
const MIN_PASSWORD_LENGTH = 8;

// A few extra mock customers beyond MOCK_CUSTOMER_EMAIL so the admin
// create-invoice form's search/filter combobox has something real to
// search over in mock/dev mode -- one customer alone can't demonstrate
// "in case I have a lot of people."
const EXTRA_MOCK_CUSTOMERS = [
  { id: "cust-alice", email: "alice.wong@gmail.com" },
  { id: "cust-bob", email: "bob.martinez@outlook.com" },
  { id: "cust-carol", email: "carol.singh@example.com" },
  { id: "cust-dave", email: "dave.oconnor@yahoo.com" },
];

// Self-registered (mock) accounts, beyond the two seeded fixtures above.
// sessionStorage-backed for the same reason readCurrentRole/writeCurrentRole
// are -- registering then logging in again after a reload should work.
function readRegisteredEmails(): string[] {
  try {
    return JSON.parse(sessionStorage.getItem("mock-registered-emails") ?? "[]");
  } catch {
    return [];
  }
}

function addRegisteredEmail(email: string): void {
  const emails = readRegisteredEmails();
  emails.push(email.toLowerCase());
  sessionStorage.setItem("mock-registered-emails", JSON.stringify(emails));
}

function isRegisteredEmail(email: string): boolean {
  return readRegisteredEmails().includes(email.toLowerCase());
}

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
  const { id, status, amount_total, currency, memo, due_date, paid_at } = inv;
  return { id, status, amount_total, currency, memo, due_date, paid_at };
}

export const handlers = [
  // -- auth --------------------------------------------------------------
  http.post("/api/auth/login", async ({ request }) => {
    const body = (await request.json()) as { email: string; password: string };
    if (body.email === MOCK_ADMIN_EMAIL) {
      writeCurrentRole("admin");
    } else if (body.email === MOCK_CUSTOMER_EMAIL || isRegisteredEmail(body.email)) {
      writeCurrentRole("customer");
    } else {
      return HttpResponse.json({ detail: "invalid credentials" }, { status: 401 });
    }
    setMockCsrfCookie();
    return HttpResponse.json({ status: "ok" });
  }),

  http.post("/api/auth/register", async ({ request }) => {
    const body = (await request.json()) as { email: string; password: string };
    if (body.email === MOCK_ADMIN_EMAIL || isRegisteredEmail(body.email)) {
      return HttpResponse.json({ detail: "email already registered" }, { status: 409 });
    }
    if (body.password.length < MIN_PASSWORD_LENGTH) {
      return HttpResponse.json({ detail: "password too short" }, { status: 422 });
    }
    // Self-registration always creates a customer-role account, same as the
    // real backend's register() -- there is no path here to create an admin.
    addRegisteredEmail(body.email);
    writeCurrentRole("customer");
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
    // user_id (not id) -- matches the real backend's actual MeResponse
    // shape (api/health.py), see api/auth.ts's Me interface doc comment.
    return HttpResponse.json({
      user_id: currentRole === "admin" ? "mock-admin-id" : MOCK_CUSTOMER_ID,
      role: currentRole,
    });
  }),

  // -- customer invoices ---------------------------------------------------
  http.get("/api/invoices", () => {
    const denied = requireRole("customer");
    if (denied) return denied;
    return HttpResponse.json(invoices.map(toListShape));
  }),

  // Registered BEFORE "/api/invoices/:id" -- same reasoning as the real
  // backend's identical route-ordering comment (api/invoices_public.py):
  // MSW matches path patterns in registration order, so ":id" would
  // otherwise swallow the literal "payment-methods" segment as if it
  // were an invoice ID.
  http.get("/api/invoices/payment-methods", () => {
    const denied = requireRole("customer");
    if (denied) return denied;
    // PayPal always "unavailable" in mock mode -- there's no real
    // provider to hook the fake create/capture flow up to here, so the
    // mock UI shows only the always-real Stripe path plus the "contact
    // us for Zelle/PayPal/in-person" messaging. A real-looking Zelle
    // handle so the mock Pay page actually demos that display too.
    return HttpResponse.json({
      stripe: true,
      paypal: false,
      zelle_handle: "logan@logand.app",
    });
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
    return HttpResponse.json({ client_secret: "pi_mock_secret_" + invoice.id });
  }),

  // -- admin customers (lookup for the create-invoice form) --------------
  http.get("/api/admin/customers", ({ request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const all = [
      { id: MOCK_CUSTOMER_ID, email: MOCK_CUSTOMER_EMAIL },
      ...EXTRA_MOCK_CUSTOMERS,
    ];
    const q = new URL(request.url).searchParams.get("q");
    const filtered = q
      ? all.filter((c) => c.email.toLowerCase().includes(q.toLowerCase()))
      : all;
    return HttpResponse.json(filtered);
  }),

  http.get("/api/admin/customers/:id", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const all = [
      { id: MOCK_CUSTOMER_ID, email: MOCK_CUSTOMER_EMAIL },
      ...EXTRA_MOCK_CUSTOMERS,
    ];
    const customer = all.find((c) => c.id === params.id);
    if (!customer) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    return HttpResponse.json({
      id: customer.id,
      email: customer.email,
      role: "customer",
      emails_opted_out: false,
      disabled_at: disabledCustomers.get(customer.id) ?? null,
      created_at: "2026-01-01T00:00:00Z",
    });
  }),

  http.post("/api/admin/customers/:id/deactivate", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    disabledCustomers.set(params.id as string, new Date().toISOString());
    return HttpResponse.json({ status: "deactivated" });
  }),

  http.post("/api/admin/customers/:id/reactivate", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    disabledCustomers.delete(params.id as string);
    return HttpResponse.json({ status: "reactivated" });
  }),

  http.post("/api/admin/customers/:id/reset-password", async ({ request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const body = (await request.json()) as { new_password: string };
    if (body.new_password.length < 8) {
      return HttpResponse.json(
        { detail: "password must be at least 8 characters" },
        { status: 422 },
      );
    }
    return HttpResponse.json({ status: "reset" });
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
    // customer_id/memo as QUERY PARAMS, line_items as the bare JSON array
    // body -- matches the real backend's actual request shape now that
    // AdminInvoices.tsx's create-invoice form actually calls this (see
    // api/invoices.ts's createInvoice doc comment for why the shape is
    // what it is).
    const url = new URL(request.url);
    const customerId = url.searchParams.get("customer_id");
    const memo = url.searchParams.get("memo");
    const rawLineItems = (await request.json()) as {
      description: string;
      quantity: string;
      unit_price: string;
      unit?: string | null;
    }[];
    const lineItems = rawLineItems.map((li) => ({
      id: mockId("li"),
      description: li.description,
      quantity: li.quantity,
      unit_price: li.unit_price,
      unit: li.unit ?? null,
    }));
    const amountTotal = lineItems
      .reduce((sum, li) => sum + Number(li.quantity) * Number(li.unit_price), 0)
      .toFixed(2);
    const invoice: MockInvoiceDetail = {
      id: mockId("inv"),
      customer_id: customerId ?? MOCK_CUSTOMER_ID,
      status: "draft",
      amount_total: amountTotal,
      currency: "usd",
      memo: memo ?? null,
      due_date: null,
      paid_at: null,
      is_recurring: false,
      line_items: lineItems,
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

  http.post("/api/admin/invoices/:id/payments/manual", async ({ params, request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const invoice = invoices.find((i) => i.id === params.id);
    if (!invoice) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    if (invoice.status !== "sent" && invoice.status !== "overdue") {
      return HttpResponse.json(
        { detail: "invoice is not in a state that allows this operation" },
        { status: 409 },
      );
    }
    const body = (await request.json()) as {
      method: string;
      amount: string;
      note?: string;
    };
    const paymentId = mockId("pay");
    invoice.payments.push({
      id: paymentId,
      method: body.method,
      amount: body.amount,
      status: "succeeded",
      transaction_id: null,
      note: body.note ?? null,
    });
    const paidSoFar = invoice.payments.reduce((sum, p) => sum + Number(p.amount), 0);
    if (paidSoFar >= Number(invoice.amount_total)) {
      invoice.status = "paid";
      invoice.paid_at = new Date().toISOString();
    }
    return HttpResponse.json({ id: paymentId });
  }),

  // Real multipart upload -- mirrors api/invoices_public.py's
  // upload_payment_proof, same as budget evidence's mock handler.
  http.post(
    "/api/invoices/:id/payment-proof",
    async ({ params, request }) => {
      const denied = requireRole("customer");
      if (denied) return denied;
      const invoice = invoices.find((i) => i.id === params.id);
      if (!invoice) return HttpResponse.json({ detail: "not found" }, { status: 404 });
      if (invoice.status === "draft" || invoice.status === "void") {
        return HttpResponse.json(
          { detail: "invoice is not in a state that allows this operation" },
          { status: 409 },
        );
      }
      const formData = await request.formData();
      const file = formData.get("file") as File | null;
      if (!file) return HttpResponse.json({ detail: "no file" }, { status: 422 });
      const allowed = ["image/png", "image/jpeg", "image/webp", "application/pdf"];
      if (!allowed.includes(file.type)) {
        return HttpResponse.json(
          { detail: "payment proof must be an image or PDF" },
          { status: 415 },
        );
      }
      const proof = {
        id: mockId("proof"),
        content_type: file.type,
        created_at: new Date().toISOString(),
      };
      const proofs = paymentProofs.get(invoice.id) ?? [];
      proofs.unshift(proof);
      paymentProofs.set(invoice.id, proofs);
      return HttpResponse.json({ id: proof.id });
    },
  ),

  http.get("/api/admin/invoices/:id/payment-proof", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const invoice = invoices.find((i) => i.id === params.id);
    if (!invoice) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    return HttpResponse.json(paymentProofs.get(invoice.id) ?? []);
  }),

  // -- admin budget ------------------------------------------------------
  http.get("/api/admin/budget", ({ request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const url = new URL(request.url);
    const category = url.searchParams.get("category");
    const dateFrom = url.searchParams.get("date_from");
    const dateTo = url.searchParams.get("date_to");
    const filtered = budgetEntries.filter((b) => {
      if (category && b.category !== category) return false;
      if (dateFrom && b.occurred_on < dateFrom) return false;
      if (dateTo && b.occurred_on > dateTo) return false;
      return true;
    });
    return HttpResponse.json(filtered);
  }),

  // Query params, no body -- matches api/budget.py's create() route
  // exactly (every param is a plain scalar). Was previously read as a
  // JSON body here, silently agreeing with a frontend bug that sent one
  // -- see api/budget.ts's doc comment for the real-vs-mocked-backend
  // divergence this masked until a real end-to-end pass caught it.
  http.post("/api/admin/budget", ({ request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const url = new URL(request.url);
    const entry: BudgetEntry = {
      id: mockId("bud"),
      amount: url.searchParams.get("amount") ?? "0",
      category: url.searchParams.get("category") ?? "",
      occurred_on: url.searchParams.get("occurred_on") ?? "",
      vendor: url.searchParams.get("vendor"),
      memo: url.searchParams.get("memo"),
      corrects_entry_id: null,
    };
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
        `${b.id},${b.occurred_on},${b.category},${b.vendor ?? ""},${b.amount},${b.memo ?? ""}`,
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
    if (locationId) results = results.filter((i) => i.location_id === locationId);
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

  // Query params, not a JSON body -- matches the real backend's actual
  // request shape (api/inventory.py's create() route), same fix as
  // api/inventory.ts's own createInventoryItem doc comment.
  http.post("/api/admin/inventory/items", ({ request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const params = new URL(request.url).searchParams;
    const item: InventoryItem = {
      id: mockId("item"),
      name: params.get("name") ?? "",
      location_id: params.get("location_id") ?? "",
      quantity: Number(params.get("quantity") ?? "1"),
      description: params.get("description"),
      tags: params.getAll("tags"),
      unit_cost: params.get("unit_cost"),
    };
    inventoryItems.push(item);
    return HttpResponse.json({ id: item.id }, { status: 201 });
  }),

  http.patch("/api/admin/inventory/items/:id", ({ params, request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const item = inventoryItems.find((i) => i.id === params.id);
    if (!item) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    const q = new URL(request.url).searchParams;
    const newLocationId = q.get("location_id");
    const newQuantity = q.get("quantity");
    if (newLocationId !== null) item.location_id = newLocationId;
    if (newQuantity !== null) item.quantity = Number(newQuantity);
    return HttpResponse.json({ status: "ok" });
  }),

  http.patch("/api/admin/inventory/items/:id/unit-cost", ({ params, request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const item = inventoryItems.find((i) => i.id === params.id);
    if (!item) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    const unitCost = new URL(request.url).searchParams.get("unit_cost");
    item.unit_cost = unitCost;
    return HttpResponse.json({ status: "ok" });
  }),

  // The audited delta-based adjustment path (distinct from the plain
  // PATCH above) -- mirrors api/inventory.py's real
  // adjust_item_quantity/list_item_adjustments behavior closely enough
  // to exercise the frontend's confirm+diff UI and history view against
  // real request/response shapes in mock mode.
  http.post(
    "/api/admin/inventory/items/:id/adjust",
    async ({ params, request }) => {
      const denied = requireRole("admin");
      if (denied) return denied;
      const item = inventoryItems.find((i) => i.id === params.id);
      if (!item) return HttpResponse.json({ detail: "not found" }, { status: 404 });
      const body = (await request.json()) as { delta: number; reason: string };
      const quantityAfter = item.quantity + body.delta;
      if (quantityAfter < 0) {
        return HttpResponse.json(
          { detail: "adjustment would take quantity below zero" },
          { status: 422 },
        );
      }
      const adjustment = {
        id: mockId("adj"),
        delta: body.delta,
        quantity_before: item.quantity,
        quantity_after: quantityAfter,
        reason: body.reason,
        adjusted_by:
          readCurrentRole() === "admin" ? "mock-admin-id" : null,
        created_at: new Date().toISOString(),
      };
      item.quantity = quantityAfter;
      const history = inventoryAdjustments.get(item.id) ?? [];
      history.unshift(adjustment);
      inventoryAdjustments.set(item.id, history);
      return HttpResponse.json({ id: adjustment.id });
    },
  ),

  http.get("/api/admin/inventory/items/:id/adjustments", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const item = inventoryItems.find((i) => i.id === params.id);
    if (!item) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    return HttpResponse.json(inventoryAdjustments.get(item.id) ?? []);
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

  // -- admin bills of materials -------------------------------------------
  http.get("/api/admin/boms", () => {
    const denied = requireRole("admin");
    if (denied) return denied;
    return HttpResponse.json(boms);
  }),

  http.post("/api/admin/boms", async ({ request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const body = (await request.json()) as {
      name: string;
      labor_hours?: string;
      labor_rate?: string;
      overhead_percent?: string;
      description?: string | null;
    };
    const bom: MockBom = {
      id: mockId("bom"),
      name: body.name,
      description: body.description ?? null,
      labor_hours: body.labor_hours ?? "0",
      labor_rate: body.labor_rate ?? "0",
      overhead_percent: body.overhead_percent ?? "0",
    };
    boms.push(bom);
    bomMaterialLines.set(bom.id, []);
    return HttpResponse.json({ id: bom.id }, { status: 201 });
  }),

  http.get("/api/admin/boms/:id", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const bom = boms.find((b) => b.id === params.id);
    if (!bom) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    return HttpResponse.json(bom);
  }),

  http.delete("/api/admin/boms/:id", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const index = boms.findIndex((b) => b.id === params.id);
    if (index === -1)
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    boms.splice(index, 1);
    bomMaterialLines.delete(params.id as string);
    return HttpResponse.json({ status: "deleted" });
  }),

  http.post("/api/admin/boms/:id/lines", async ({ params, request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const bom = boms.find((b) => b.id === params.id);
    if (!bom) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    const body = (await request.json()) as {
      item_id: string;
      quantity_per_unit: number;
    };
    const item = inventoryItems.find((i) => i.id === body.item_id);
    if (!item) return HttpResponse.json({ detail: "item not found" }, { status: 404 });
    const lines = bomMaterialLines.get(bom.id) ?? [];
    if (lines.some((l) => l.item_id === body.item_id)) {
      return HttpResponse.json(
        { detail: "this item already has a material line on this bom" },
        { status: 409 },
      );
    }
    lines.push({ item_id: body.item_id, quantity_per_unit: body.quantity_per_unit });
    bomMaterialLines.set(bom.id, lines);
    return HttpResponse.json({ id: mockId("line") });
  }),

  http.delete("/api/admin/boms/:bomId/lines/:itemId", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const lines = bomMaterialLines.get(params.bomId as string);
    if (!lines) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    const next = lines.filter((l) => l.item_id !== params.itemId);
    if (next.length === lines.length) {
      return HttpResponse.json({ detail: "not found" }, { status: 404 });
    }
    bomMaterialLines.set(params.bomId as string, next);
    return HttpResponse.json({ status: "removed" });
  }),

  http.get("/api/admin/boms/:id/cost", ({ params, request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const bom = boms.find((b) => b.id === params.id);
    if (!bom) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    const buildQuantity = Number(
      new URL(request.url).searchParams.get("build_quantity") ?? "1",
    );
    const lines = bomMaterialLines.get(bom.id) ?? [];
    const materialLines = [];
    let materialCost = 0;
    for (const line of lines) {
      const item = inventoryItems.find((i) => i.id === line.item_id);
      if (!item || item.unit_cost === null) {
        return HttpResponse.json(
          { detail: "an item on this bill of materials has no unit_cost set" },
          { status: 422 },
        );
      }
      const quantity = line.quantity_per_unit * buildQuantity;
      const lineCost = Number(item.unit_cost) * quantity;
      materialCost += lineCost;
      materialLines.push({
        item_id: item.id,
        item_name: item.name,
        quantity,
        unit_cost: item.unit_cost,
        line_cost: lineCost.toFixed(4),
      });
    }
    const laborHours = Number(bom.labor_hours) * buildQuantity;
    const laborCost = laborHours * Number(bom.labor_rate);
    const overheadCost = (materialCost + laborCost) * (Number(bom.overhead_percent) / 100);
    const totalCost = materialCost + laborCost + overheadCost;
    return HttpResponse.json({
      material_lines: materialLines,
      material_cost: materialCost.toFixed(4),
      labor_hours: String(laborHours),
      labor_cost: laborCost.toFixed(4),
      overhead_percent: bom.overhead_percent,
      overhead_cost: overheadCost.toFixed(4),
      total_cost: totalCost.toFixed(4),
    });
  }),

  http.post("/api/admin/boms/:id/consume", async ({ params, request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const bom = boms.find((b) => b.id === params.id);
    if (!bom) return HttpResponse.json({ detail: "not found" }, { status: 404 });
    const body = (await request.json()) as {
      build_quantity: number;
      reason?: string;
    };
    const lines = bomMaterialLines.get(bom.id) ?? [];
    // Two-phase, same as the real backend: check every line first, only
    // apply if everything has enough stock.
    for (const line of lines) {
      const item = inventoryItems.find((i) => i.id === line.item_id);
      if (!item || item.quantity < line.quantity_per_unit * body.build_quantity) {
        return HttpResponse.json(
          { detail: "adjustment would take quantity below zero" },
          { status: 422 },
        );
      }
    }
    const adjustmentIds: string[] = [];
    for (const line of lines) {
      const item = inventoryItems.find((i) => i.id === line.item_id)!;
      const need = line.quantity_per_unit * body.build_quantity;
      const quantityBefore = item.quantity;
      item.quantity -= need;
      const adjustment = {
        id: mockId("adj"),
        delta: -need,
        quantity_before: quantityBefore,
        quantity_after: item.quantity,
        reason: body.reason || `BOM consumption: ${bom.name} x${body.build_quantity}`,
        adjusted_by: readCurrentRole() === "admin" ? "mock-admin-id" : null,
        created_at: new Date().toISOString(),
      };
      const history = inventoryAdjustments.get(item.id) ?? [];
      history.unshift(adjustment);
      inventoryAdjustments.set(item.id, history);
      adjustmentIds.push(adjustment.id);
    }
    return HttpResponse.json({ adjustment_ids: adjustmentIds });
  }),

  // -- admin generic data browser/editor -----------------------------------
  // Mocked over just "inventory_items" (the real backend is reflection-based
  // over every table -- see domain/admin_data/service.py -- but a full mock
  // of every table's schema isn't worth it for a demo dataset) so the page
  // has something real to browse/edit/revert without a backend.
  http.get("/api/admin/data/tables", () => {
    const denied = requireRole("admin");
    if (denied) return denied;
    return HttpResponse.json(["inventory_items", "inventory_locations"]);
  }),

  http.get("/api/admin/data/tables/:table/schema", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    if (params.table === "inventory_items") {
      return HttpResponse.json([
        { name: "id", type: "UUID", nullable: false, primary_key: true, editable: false },
        {
          name: "name",
          type: "VARCHAR",
          nullable: false,
          primary_key: false,
          editable: true,
        },
        {
          name: "quantity",
          type: "INTEGER",
          nullable: false,
          primary_key: false,
          editable: true,
        },
      ]);
    }
    return HttpResponse.json({ detail: "no such table" }, { status: 404 });
  }),

  http.get("/api/admin/data/tables/:table/rows", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    if (params.table === "inventory_items") return HttpResponse.json(inventoryItems);
    if (params.table === "inventory_locations")
      return HttpResponse.json(inventoryLocations);
    return HttpResponse.json({ detail: "no such table" }, { status: 404 });
  }),

  http.get("/api/admin/data/tables/:table/rows/:id", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const row = inventoryItems.find((i) => i.id === params.id);
    if (!row) return HttpResponse.json({ detail: "row was not found" }, { status: 404 });
    return HttpResponse.json(row);
  }),

  http.patch("/api/admin/data/tables/:table/rows/:id", async ({ params, request }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const item = inventoryItems.find((i) => i.id === params.id) as
      | Record<string, unknown>
      | undefined;
    if (!item) return HttpResponse.json({ detail: "row was not found" }, { status: 404 });
    const body = (await request.json()) as { changes: Record<string, unknown> };
    const before = { ...item };
    Object.assign(item, body.changes);
    const changeId = mockId("change");
    adminDataChanges.unshift({
      id: changeId,
      admin_id: "mock-admin-id",
      action: "data.update",
      target_table: String(params.table),
      target_id: String(params.id),
      before_state: before,
      after_state: { ...item },
      created_at: new Date().toISOString(),
    });
    return HttpResponse.json({ change_id: changeId });
  }),

  http.delete("/api/admin/data/tables/:table/rows/:id", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const index = inventoryItems.findIndex((i) => i.id === params.id);
    if (index === -1)
      return HttpResponse.json({ detail: "row was not found" }, { status: 404 });
    const [removed] = inventoryItems.splice(index, 1);
    const changeId = mockId("change");
    adminDataChanges.unshift({
      id: changeId,
      admin_id: "mock-admin-id",
      action: "data.delete",
      target_table: String(params.table),
      target_id: String(params.id),
      before_state: removed as unknown as Record<string, unknown>,
      after_state: null,
      created_at: new Date().toISOString(),
    });
    return HttpResponse.json({ change_id: changeId });
  }),

  http.get("/api/admin/data/changes", () => {
    const denied = requireRole("admin");
    if (denied) return denied;
    return HttpResponse.json(adminDataChanges);
  }),

  http.post("/api/admin/data/changes/:id/revert", ({ params }) => {
    const denied = requireRole("admin");
    if (denied) return denied;
    const entry = adminDataChanges.find((c) => c.id === params.id);
    if (!entry)
      return HttpResponse.json(
        { detail: "audit log entry was not found" },
        { status: 404 },
      );
    if (entry.action === "data.update" && entry.before_state) {
      const item = inventoryItems.find((i) => i.id === entry.target_id) as
        | Record<string, unknown>
        | undefined;
      if (item) Object.assign(item, entry.before_state);
    } else if (entry.action === "data.delete" && entry.before_state) {
      inventoryItems.push(entry.before_state as unknown as InventoryItem);
    }
    return HttpResponse.json({ change_id: mockId("change") });
  }),

  // -- admin server logs ----------------------------------------------------
  http.get("/api/admin/logs/files", () => {
    const denied = requireRole("admin");
    if (denied) return denied;
    return HttpResponse.json([
      { name: "app.log", size_bytes: 4096, modified_at: Date.now() / 1000 },
      {
        name: "app.log.2026-07-01",
        size_bytes: 20480,
        modified_at: Date.now() / 1000 - 86400,
      },
    ]);
  }),

  http.get("/api/admin/logs/tail", () => {
    const denied = requireRole("admin");
    if (denied) return denied;
    return HttpResponse.json([
      JSON.stringify({
        timestamp: new Date().toISOString(),
        level: "INFO",
        logger: "logand_backend.access",
        message: "request complete",
        request_id: "mock-request-id",
      }),
    ]);
  }),

  http.get("/api/admin/logs/files/:name", () => {
    const denied = requireRole("admin");
    if (denied) return denied;
    return new HttpResponse("{}\n", {
      status: 200,
      headers: { "Content-Type": "application/x-ndjson" },
    });
  }),
];
