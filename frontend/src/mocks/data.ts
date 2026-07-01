// In-memory fake dataset for MSW handlers (src/mocks/handlers.ts). Mutated
// by POST/PATCH/DELETE handlers so the mockup feels alive across a session
// -- e.g. creating an invoice via the admin form shows up in the list
// afterward. Reset on a full page reload (module re-evaluates), which is
// fine for a local preview/demo, not meant to persist.

import type { Invoice } from "../api/invoices";
import type { BudgetEntry } from "../api/budget";
import type { InventoryItem } from "../api/inventory";

export interface MockInvoiceLineItem {
  id: string;
  description: string;
  quantity: string;
  unitPrice: string;
}

export interface MockPayment {
  id: string;
  method: string;
  amount: string;
  status: string;
  transactionId: string | null;
  note?: string | null;
}

export interface MockInvoiceDetail extends Invoice {
  customerId: string;
  isRecurring: boolean;
  lineItems: MockInvoiceLineItem[];
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
    customerId: MOCK_CUSTOMER_ID,
    status: "draft",
    amountTotal: "450.00",
    currency: "usd",
    memo: "Website redesign, phase 1",
    dueDate: "2026-07-15",
    isRecurring: false,
    lineItems: [
      { id: "li-1", description: "Design mockups", quantity: "1", unitPrice: "300.00" },
      { id: "li-2", description: "Revisions", quantity: "3", unitPrice: "50.00" },
    ],
    payments: [],
  },
  {
    id: "inv-002",
    customerId: MOCK_CUSTOMER_ID,
    status: "sent",
    amountTotal: "1200.00",
    currency: "usd",
    memo: "Monthly retainer -- June",
    dueDate: "2026-06-30",
    isRecurring: true,
    lineItems: [
      {
        id: "li-3",
        description: "Retainer hours",
        quantity: "12",
        unitPrice: "100.00",
      },
    ],
    payments: [],
  },
  {
    id: "inv-003",
    customerId: MOCK_CUSTOMER_ID,
    status: "paid",
    amountTotal: "780.50",
    currency: "usd",
    memo: "Server migration",
    dueDate: "2026-05-20",
    isRecurring: false,
    lineItems: [
      {
        id: "li-4",
        description: "Migration labor",
        quantity: "7.5",
        unitPrice: "104.0667",
      },
    ],
    payments: [
      {
        id: "pay-1",
        method: "stripe",
        amount: "780.50",
        status: "succeeded",
        transactionId: "ch_mock_1",
      },
    ],
  },
  {
    id: "inv-004",
    customerId: MOCK_CUSTOMER_ID,
    status: "overdue",
    amountTotal: "199.99",
    currency: "usd",
    memo: "Domain + hosting renewal",
    dueDate: "2026-06-01",
    isRecurring: true,
    lineItems: [
      {
        id: "li-5",
        description: "Hosting renewal",
        quantity: "1",
        unitPrice: "199.99",
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
    occurredOn: "2026-01-10",
  },
  {
    id: "bud-002",
    amount: "412.55",
    category: "supplies",
    vendor: "DigiKey",
    memo: "Resistor/cap assortment + soldering tips",
    occurredOn: "2026-03-22",
  },
  {
    id: "bud-003",
    amount: "65.00",
    category: "travel",
    vendor: "Amtrak",
    memo: "Client site visit",
    occurredOn: "2026-04-02",
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
    locationId: "loc-001",
    tags: ["resistor", "smd", "0603"],
  },
  {
    id: "item-002",
    name: "Soldering iron tips",
    description: "Conical, 1mm",
    quantity: 8,
    locationId: "loc-002",
    tags: ["soldering", "tips"],
  },
  {
    id: "item-003",
    name: "USB-C cables",
    description: "1m, braided",
    quantity: 15,
    locationId: "loc-003",
    tags: ["cable", "usb-c"],
  },
];
