import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addBomMaterialLine,
  consumeBom,
  createBom,
  deleteBom,
  getBomCostBreakdown,
  listBoms,
  removeBomMaterialLine,
  type Bom,
} from "../../../api/bom";
import { listInventoryItems } from "../../../api/inventory";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

function CreateBomForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [laborHours, setLaborHours] = useState("0");
  const [laborRate, setLaborRate] = useState("0");
  const [overheadPercent, setOverheadPercent] = useState("0");

  const mutation = useMutation({
    mutationFn: () =>
      createBom({
        name,
        labor_hours: laborHours,
        labor_rate: laborRate,
        overhead_percent: overheadPercent,
      }),
    onSuccess: () => {
      onCreated();
      setOpen(false);
      setName("");
      setLaborHours("0");
      setLaborRate("0");
      setOverheadPercent("0");
    },
  });

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className={BUTTON_CLASS}>
        New bill of materials
      </button>
    );
  }

  return (
    <form
      className="mb-6 flex flex-col gap-4 rounded border border-border p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!name) return;
        mutation.mutate();
      }}
    >
      <h2 className="text-xl text-fg-primary">New bill of materials</h2>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[12rem] flex-1">
          <label htmlFor="bom-name" className={LABEL_CLASS}>
            Name
          </label>
          <input
            id="bom-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className={INPUT_CLASS}
          />
        </div>
        <div className="w-28">
          <label htmlFor="bom-labor-hours" className={LABEL_CLASS}>
            Labor hrs
          </label>
          <input
            id="bom-labor-hours"
            type="number"
            step="0.01"
            min="0"
            value={laborHours}
            onChange={(e) => setLaborHours(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
        <div className="w-32">
          <label htmlFor="bom-labor-rate" className={LABEL_CLASS}>
            Rate ($/hr)
          </label>
          <input
            id="bom-labor-rate"
            type="number"
            step="0.01"
            min="0"
            value={laborRate}
            onChange={(e) => setLaborRate(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
        <div className="w-28">
          <label htmlFor="bom-overhead" className={LABEL_CLASS}>
            Overhead %
          </label>
          <input
            id="bom-overhead"
            type="number"
            step="0.01"
            min="0"
            value={overheadPercent}
            onChange={(e) => setOverheadPercent(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
      </div>
      <div className="flex gap-2">
        <button type="submit" disabled={mutation.isPending} className={BUTTON_CLASS}>
          Create
        </button>
        <button type="button" onClick={() => setOpen(false)} className={BUTTON_CLASS}>
          Cancel
        </button>
      </div>
      {mutation.isError && (
        <p role="alert" className="text-base text-accent-red">
          Could not create this bill of materials.
        </p>
      )}
    </form>
  );
}

function BomDetail({ bom, onChanged }: { bom: Bom; onChanged: () => void }) {
  const queryClient = useQueryClient();
  const [selectedItemId, setSelectedItemId] = useState("");
  const [quantityPerUnit, setQuantityPerUnit] = useState("1");
  const [buildQuantity, setBuildQuantity] = useState("1");
  const [showConsumeConfirm, setShowConsumeConfirm] = useState(false);
  const [consumeReason, setConsumeReason] = useState("");

  const itemsQuery = useQuery({
    queryKey: ["admin", "inventory"],
    queryFn: listInventoryItems,
  });

  const parsedBuildQuantity = Math.max(1, Number(buildQuantity) || 1);

  const costQuery = useQuery({
    queryKey: ["admin", "boms", bom.id, "cost", parsedBuildQuantity],
    queryFn: () => getBomCostBreakdown(bom.id, parsedBuildQuantity),
  });

  const addLineMutation = useMutation({
    mutationFn: () =>
      addBomMaterialLine(bom.id, selectedItemId, Number(quantityPerUnit)),
    onSuccess: () => {
      setSelectedItemId("");
      setQuantityPerUnit("1");
      queryClient.invalidateQueries({ queryKey: ["admin", "boms", bom.id] });
    },
  });

  const removeLineMutation = useMutation({
    mutationFn: (itemId: string) => removeBomMaterialLine(bom.id, itemId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["admin", "boms", bom.id] }),
  });

  const consumeMutation = useMutation({
    mutationFn: () => consumeBom(bom.id, parsedBuildQuantity, consumeReason || undefined),
    onSuccess: () => {
      setShowConsumeConfirm(false);
      setConsumeReason("");
      queryClient.invalidateQueries({ queryKey: ["admin", "inventory"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "boms", bom.id] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteBom(bom.id),
    onSuccess: onChanged,
  });

  return (
    <div className="rounded border border-border p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg text-fg-primary">{bom.name}</h3>
        <button
          type="button"
          onClick={() => deleteMutation.mutate()}
          className={BUTTON_CLASS}
        >
          Delete BOM
        </button>
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-2">
        <div className="min-w-[12rem] flex-1">
          <label htmlFor={`add-item-${bom.id}`} className={LABEL_CLASS}>
            Add material line
          </label>
          <select
            id={`add-item-${bom.id}`}
            value={selectedItemId}
            onChange={(e) => setSelectedItemId(e.target.value)}
            className={INPUT_CLASS}
          >
            <option value="">Select an item...</option>
            {itemsQuery.data?.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        <div className="w-24">
          <label htmlFor={`add-qty-${bom.id}`} className={LABEL_CLASS}>
            Qty/unit
          </label>
          <input
            id={`add-qty-${bom.id}`}
            type="number"
            min={1}
            value={quantityPerUnit}
            onChange={(e) => setQuantityPerUnit(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
        <button
          type="button"
          disabled={!selectedItemId || addLineMutation.isPending}
          onClick={() => addLineMutation.mutate()}
          className={BUTTON_CLASS}
        >
          Add line
        </button>
      </div>
      {addLineMutation.isError && (
        <p role="alert" className="mb-2 text-sm text-accent-red">
          Could not add that line (already on this BOM?).
        </p>
      )}

      <div className="mb-4">
        <label htmlFor={`build-qty-${bom.id}`} className={LABEL_CLASS}>
          Build quantity (for cost preview + consume)
        </label>
        <input
          id={`build-qty-${bom.id}`}
          type="number"
          min={1}
          value={buildQuantity}
          onChange={(e) => setBuildQuantity(e.target.value)}
          className={`${INPUT_CLASS} w-24`}
        />
      </div>

      {costQuery.isLoading && <p className="text-fg-muted">Loading cost breakdown...</p>}
      {costQuery.isError && (
        <p role="alert" className="text-accent-red">
          Could not compute a cost breakdown -- every material line needs a real
          unit_cost set on its inventory item first.
        </p>
      )}
      {costQuery.data && (
        <div className="mb-4 rounded border border-border p-3 text-sm">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border">
                <th className="p-1">Item</th>
                <th className="p-1">Qty</th>
                <th className="p-1">Unit cost</th>
                <th className="p-1">Line cost</th>
                <th className="p-1" />
              </tr>
            </thead>
            <tbody>
              {costQuery.data.material_lines.map((line) => (
                <tr key={line.item_id} className="border-b border-border">
                  <td className="p-1">{line.item_name}</td>
                  <td className="p-1">{line.quantity}</td>
                  <td className="p-1">${line.unit_cost}</td>
                  <td className="p-1">${line.line_cost}</td>
                  <td className="p-1">
                    <button
                      type="button"
                      onClick={() => removeLineMutation.mutate(line.item_id)}
                      className="text-accent-red underline"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2">Material: ${costQuery.data.material_cost}</p>
          <p>
            Labor: ${costQuery.data.labor_cost} ({costQuery.data.labor_hours} hrs)
          </p>
          <p>
            Overhead ({costQuery.data.overhead_percent}%): ${costQuery.data.overhead_cost}
          </p>
          <p className="font-bold text-fg-primary">
            Total: ${costQuery.data.total_cost}
          </p>
        </div>
      )}

      {!showConsumeConfirm ? (
        <button
          type="button"
          onClick={() => setShowConsumeConfirm(true)}
          className={BUTTON_CLASS}
        >
          Record a build (consume stock)
        </button>
      ) : (
        <div className="flex flex-col gap-2 rounded border border-border p-3">
          <p className="text-base text-fg-primary">
            This will deduct stock for {parsedBuildQuantity}x build
            {parsedBuildQuantity === 1 ? "" : "s"} of {bom.name} from every material
            line above. This cannot be undone automatically -- a new adjustment
            with the reverse delta would be needed to reverse it.
          </p>
          <label htmlFor={`consume-reason-${bom.id}`} className={LABEL_CLASS}>
            Reason (optional)
          </label>
          <input
            id={`consume-reason-${bom.id}`}
            value={consumeReason}
            onChange={(e) => setConsumeReason(e.target.value)}
            className={INPUT_CLASS}
          />
          {consumeMutation.isError && (
            <p role="alert" className="text-base text-accent-red">
              Could not consume -- check that every material line still has enough
              stock.
            </p>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={consumeMutation.isPending}
              onClick={() => consumeMutation.mutate()}
              className={BUTTON_CLASS}
            >
              Confirm consume
            </button>
            <button
              type="button"
              onClick={() => setShowConsumeConfirm(false)}
              className={BUTTON_CLASS}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function AdminBom() {
  const queryClient = useQueryClient();
  const [selectedBomId, setSelectedBomId] = useState<string | null>(null);

  const {
    data: boms,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["admin", "boms"],
    queryFn: listBoms,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["admin", "boms"] });
    setSelectedBomId(null);
  };

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Bills of materials (admin)</h1>
      <CreateBomForm onCreated={invalidate} />

      {isLoading && <p className="text-base text-fg-muted">Loading...</p>}
      {isError && (
        <p role="alert" className="text-base text-accent-red">
          Failed to load bills of materials.
        </p>
      )}
      {boms && (
        <div className="flex flex-col gap-3">
          {boms.map((bom) => (
            <div key={bom.id}>
              <button
                type="button"
                onClick={() =>
                  setSelectedBomId(selectedBomId === bom.id ? null : bom.id)
                }
                className={`${BUTTON_CLASS} w-full text-left`}
              >
                {bom.name}
              </button>
              {selectedBomId === bom.id && (
                <div className="mt-2">
                  <BomDetail bom={bom} onChanged={invalidate} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
