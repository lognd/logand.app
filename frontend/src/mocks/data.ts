// In-memory fake dataset for MSW handlers (src/mocks/handlers.ts). Mutated
// by POST/PATCH/DELETE handlers so the mockup feels alive across a session
// -- e.g. creating an invoice via the admin form shows up in the list
// afterward. Reset on a full page reload (module re-evaluates), which is
// fine for a local preview/demo, not meant to persist.

import type { Invoice } from "../api/invoices";
import type { BudgetEntry } from "../api/budget";
import type { InventoryItem } from "../api/inventory";

// snake_case fields (unit_price, transaction_id, etc.), not camelCase --
// matches the real backend's actual JSON field names (see api/invoices.ts's
// Invoice interface doc comment for the full story on why this matters:
// these mocks previously used camelCase, which happened to match an
// equally-wrong camelCase frontend type, so the mismatch against the REAL
// backend went unnoticed).
export interface MockInvoiceLineItem {
  id: string;
  description: string;
  quantity: string;
  unit_price: string;
  unit: string | null;
}

export interface MockRefund {
  id: string;
  amount: string;
  reason: string | null;
  status: string;
  stripe_refund_id: string | null;
  paypal_refund_id: string | null;
  recorded_by: string;
  created_at: string;
}

export interface MockPayment {
  id: string;
  method: string;
  amount: string;
  status: string;
  transaction_id: string | null;
  note?: string | null;
  dispute_status?: string | null;
  refunds?: MockRefund[];
}

export interface MockInvoiceDetail extends Invoice {
  customer_id: string;
  is_recurring: boolean;
  line_items: MockInvoiceLineItem[];
  payments: MockPayment[];
}

export const MOCK_CUSTOMER_ID = "11111111-1111-4111-8111-111111111111";

let nextId = 1000;
export function mockId(prefix: string): string {
  nextId += 1;
  return `${prefix}-${nextId}`;
}

export const invoices: MockInvoiceDetail[] = [
  {
    id: "inv-001",
    customer_id: MOCK_CUSTOMER_ID,
    status: "draft",
    amount_total: "450.00",
    currency: "usd",
    memo: "Website redesign, phase 1",
    due_date: "2026-07-15",
    paid_at: null,
    is_recurring: false,
    line_items: [
      { id: "li-1", description: "Design mockups", quantity: "1", unit_price: "300.00", unit: null },
      { id: "li-2", description: "Revisions", quantity: "3", unit_price: "50.00", unit: "revision" },
    ],
    payments: [],
  },
  {
    id: "inv-002",
    customer_id: MOCK_CUSTOMER_ID,
    status: "sent",
    amount_total: "1200.00",
    currency: "usd",
    memo: "Monthly retainer -- June",
    due_date: "2026-06-30",
    paid_at: null,
    is_recurring: true,
    line_items: [
      {
        id: "li-3",
        description: "Retainer hours",
        quantity: "12",
        unit_price: "100.00",
        unit: "hr",
      },
    ],
    payments: [],
  },
  {
    id: "inv-003",
    customer_id: MOCK_CUSTOMER_ID,
    status: "paid",
    amount_total: "780.50",
    currency: "usd",
    memo: "Server migration",
    due_date: "2026-05-20",
    paid_at: "2026-05-18T14:32:00Z",
    is_recurring: false,
    line_items: [
      {
        id: "li-4",
        description: "Migration labor",
        quantity: "7.5",
        unit_price: "104.0667",
        unit: "hr",
      },
    ],
    payments: [
      {
        id: "pay-1",
        method: "stripe",
        amount: "780.50",
        status: "succeeded",
        transaction_id: "ch_mock_1",
      },
    ],
  },
  {
    id: "inv-004",
    customer_id: MOCK_CUSTOMER_ID,
    status: "overdue",
    amount_total: "199.99",
    currency: "usd",
    memo: "Domain + hosting renewal",
    due_date: "2026-06-01",
    paid_at: null,
    is_recurring: true,
    line_items: [
      {
        id: "li-5",
        description: "Hosting renewal",
        quantity: "1",
        unit_price: "199.99",
        unit: null,
      },
    ],
    payments: [],
  },
];

export const budgetEntries: BudgetEntry[] = [
  {
    id: "bud-001",
    amount: "89.00",
    category: "software",
    vendor: "JetBrains",
    memo: "Annual IDE license",
    occurred_on: "2026-01-10",
    corrects_entry_id: null,
  },
  {
    id: "bud-002",
    amount: "412.55",
    category: "supplies",
    vendor: "DigiKey",
    memo: "Resistor/cap assortment + soldering tips",
    occurred_on: "2026-03-22",
    corrects_entry_id: null,
  },
  {
    id: "bud-003",
    amount: "65.00",
    category: "travel",
    vendor: "Amtrak",
    memo: "Client site visit",
    occurred_on: "2026-04-02",
    corrects_entry_id: null,
  },
];

export interface MockInventoryLocation {
  id: string;
  name: string;
  description: string | null;
}

export const inventoryLocations: MockInventoryLocation[] = [
  { id: "loc-001", name: "Garage shelf 3", description: "Bins A-F" },
  { id: "loc-002", name: "Desk drawer A", description: "Small components" },
  { id: "loc-003", name: "Closet bin 2", description: "Cables and adapters" },
];

export const inventoryItems: InventoryItem[] = [
  {
    id: "item-001",
    name: "0603 resistor assortment",
    description: "1% tolerance, 170 values",
    quantity: 12,
    location_id: "loc-001",
    tags: ["resistor", "smd", "0603"],
    unit_cost: "0.02",
  },
  {
    id: "item-002",
    name: "Soldering iron tips",
    description: "Conical, 1mm",
    quantity: 8,
    location_id: "loc-002",
    tags: ["soldering", "tips"],
    unit_cost: "3.50",
  },
  {
    id: "item-003",
    name: "USB-C cables",
    description: "1m, braided",
    quantity: 15,
    location_id: "loc-003",
    tags: ["cable", "usb-c"],
    unit_cost: null,
  },
];
