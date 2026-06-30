import { apiGet, apiPost } from "./client";

// TODO(logan): replace with generated type once backend/openapi.json exists.
export interface InventoryItem {
  id: string;
  name: string;
  description: string | null;
  quantity: number;
  locationId: string;
  tags: string[];
}

export function listInventoryItems(): Promise<InventoryItem[]> {
  return apiGet<InventoryItem[]>("/api/admin/inventory/items");
}

export function createInventoryItem(
  item: Omit<InventoryItem, "id">,
): Promise<InventoryItem> {
  return apiPost<InventoryItem>("/api/admin/inventory/items", item);
}
