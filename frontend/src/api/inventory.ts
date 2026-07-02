import { apiGet, apiPatch, apiPost } from "./client";

// TODO(logan): replace with generated type once backend/openapi.json exists.
// snake_case location_id (not locationId) -- matches the real backend's
// actual JSON field name (api/inventory.py's _item_summary). Found during
// this session's inventory work: the old camelCase `locationId` field was
// the exact same class of bug already caught and fixed in api/invoices.ts
// -- mocks/data.ts happened to use the same wrong camelCase shape, so the
// mismatch against the REAL backend went unnoticed. Every fetched item's
// location_id silently read as undefined against a real server.
export interface InventoryItem {
  id: string;
  name: string;
  description: string | null;
  quantity: number;
  location_id: string;
  tags: string[];
  // Nullable -- most items have no cost recorded (see backend's own
  // InventoryItem.unit_cost doc comment). Only required in practice for
  // an item referenced by a BOM material line (api/bom.ts).
  unit_cost: string | null;
}

export function listInventoryItems(): Promise<InventoryItem[]> {
  return apiGet<InventoryItem[]>("/api/admin/inventory/items");
}

export interface NewInventoryItem {
  name: string;
  quantity: number;
  location_id: string;
  description?: string | null;
  tags?: string[];
}

// Query params, NOT a JSON body -- api/inventory.py's create() route
// takes name/location_id/quantity/description/tags as plain scalar (or
// list-of-scalar) params, which FastAPI treats as query params by
// default, not a body. The previous version of this function POSTed the
// whole item as a JSON body, which meant this endpoint 422'd "field
// required" on every single real (non-mocked) call -- the admin "Add
// item" form had never actually worked against a real backend. Same
// shape bug, and same fix, as api/invoices.ts's createInvoice.
export function createInventoryItem(item: NewInventoryItem): Promise<{ id: string }> {
  const params = new URLSearchParams({
    name: item.name,
    location_id: item.location_id,
    quantity: String(item.quantity),
  });
  if (item.description) params.set("description", item.description);
  for (const tag of item.tags ?? []) params.append("tags", tag);
  return apiPost<{ id: string }>(`/api/admin/inventory/items?${params.toString()}`);
}

export interface AdjustInventoryQuantity {
  delta: number;
  reason: string;
}

// This one IS a real JSON body (api/inventory.py's AdjustQuantityInput
// pydantic model), unlike createInventoryItem above -- a body-eligible
// Pydantic model param is exactly what makes FastAPI treat the whole
// thing as the request body instead of query params.
export function adjustInventoryQuantity(
  itemId: string,
  adjustment: AdjustInventoryQuantity,
): Promise<{ id: string }> {
  return apiPost<{ id: string }>(
    `/api/admin/inventory/items/${itemId}/adjust`,
    adjustment,
  );
}

export interface InventoryAdjustmentRecord {
  id: string;
  delta: number;
  quantity_before: number;
  quantity_after: number;
  reason: string;
  adjusted_by: string | null;
  created_at: string;
}

export function listInventoryAdjustments(
  itemId: string,
): Promise<InventoryAdjustmentRecord[]> {
  return apiGet<InventoryAdjustmentRecord[]>(
    `/api/admin/inventory/items/${itemId}/adjustments`,
  );
}

// PATCH /items/{id} still exists for the absolute-set path (editing
// location, or a rare direct quantity override) -- kept as its own
// function so callers reaching for the AUDITED delta-based
// adjustInventoryQuantity above don't accidentally reach for this
// unaudited one instead.
export function updateInventoryItem(
  itemId: string,
  patch: { location_id?: string; quantity?: number },
): Promise<{ status: string }> {
  const params = new URLSearchParams();
  if (patch.location_id) params.set("location_id", patch.location_id);
  if (patch.quantity !== undefined) params.set("quantity", String(patch.quantity));
  return apiPatch<{ status: string }>(
    `/api/admin/inventory/items/${itemId}?${params.toString()}`,
  );
}

export function setItemUnitCost(
  itemId: string,
  unitCost: string,
): Promise<{ status: string }> {
  const params = new URLSearchParams({ unit_cost: unitCost });
  return apiPatch<{ status: string }>(
    `/api/admin/inventory/items/${itemId}/unit-cost?${params.toString()}`,
  );
}
