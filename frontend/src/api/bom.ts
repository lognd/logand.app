import { apiDelete, apiGet, apiPost } from "./client";

// TODO(logan): replace with generated type once backend/openapi.json exists.
export interface Bom {
  id: string;
  name: string;
  description: string | null;
  labor_hours: string;
  labor_rate: string;
  overhead_percent: string;
}

export interface NewBom {
  name: string;
  labor_hours?: string;
  labor_rate?: string;
  overhead_percent?: string;
  description?: string | null;
}

export function listBoms(): Promise<Bom[]> {
  return apiGet<Bom[]>("/api/admin/boms");
}

export function getBom(id: string): Promise<Bom> {
  return apiGet<Bom>(`/api/admin/boms/${id}`);
}

export function createBom(bom: NewBom): Promise<{ id: string }> {
  return apiPost<{ id: string }>("/api/admin/boms", bom);
}

export function deleteBom(id: string): Promise<{ status: string }> {
  return apiDelete<{ status: string }>(`/api/admin/boms/${id}`);
}

export function addBomMaterialLine(
  bomId: string,
  itemId: string,
  quantityPerUnit: number,
): Promise<{ id: string }> {
  return apiPost<{ id: string }>(`/api/admin/boms/${bomId}/lines`, {
    item_id: itemId,
    quantity_per_unit: quantityPerUnit,
  });
}

export function removeBomMaterialLine(
  bomId: string,
  itemId: string,
): Promise<{ status: string }> {
  return apiDelete<{ status: string }>(`/api/admin/boms/${bomId}/lines/${itemId}`);
}

export interface BomMaterialLineCost {
  item_id: string;
  item_name: string;
  quantity: number;
  unit_cost: string;
  line_cost: string;
}

export interface BomCostBreakdown {
  material_lines: BomMaterialLineCost[];
  material_cost: string;
  labor_hours: string;
  labor_cost: string;
  overhead_percent: string;
  overhead_cost: string;
  total_cost: string;
}

export function getBomCostBreakdown(
  bomId: string,
  buildQuantity: number,
): Promise<BomCostBreakdown> {
  const params = new URLSearchParams({ build_quantity: String(buildQuantity) });
  return apiGet<BomCostBreakdown>(`/api/admin/boms/${bomId}/cost?${params.toString()}`);
}

export function consumeBom(
  bomId: string,
  buildQuantity: number,
  reason?: string,
): Promise<{ adjustment_ids: string[] }> {
  return apiPost<{ adjustment_ids: string[] }>(`/api/admin/boms/${bomId}/consume`, {
    build_quantity: buildQuantity,
    reason,
  });
}
