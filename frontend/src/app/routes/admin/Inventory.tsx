import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  adjustInventoryQuantity,
  createInventoryItem,
  listInventoryAdjustments,
  listInventoryItems,
  setItemUnitCost,
  type InventoryItem,
} from "../../../api/inventory";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

// A two-step confirm ("propose a delta -> see the exact before/after
// diff -> confirm or cancel") for one item, inline in its own row --
// per the site-wide requirement that every destructive/data-changing
// admin action show a real before-to-after diff and require an explicit
// confirmation, not just fire on the first click. The audit trail this
// writes to (InventoryAdjustment, see backend) IS the rollback record:
// undoing a bad adjustment means recording a new one with the reverse
// delta, not editing/deleting the old row.
function AdjustQuantityControl({ item }: { item: InventoryItem }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [delta, setDelta] = useState("");
  const [reason, setReason] = useState("");
  const [showHistory, setShowHistory] = useState(false);

  const adjustMutation = useMutation({
    mutationFn: () =>
      adjustInventoryQuantity(item.id, { delta: Number(delta), reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "inventory"] });
      queryClient.invalidateQueries({
        queryKey: ["admin", "inventory", "adjustments", item.id],
      });
      setEditing(false);
      setDelta("");
      setReason("");
    },
  });

  const historyQuery = useQuery({
    queryKey: ["admin", "inventory", "adjustments", item.id],
    queryFn: () => listInventoryAdjustments(item.id),
    enabled: showHistory,
  });

  const parsedDelta = Number(delta);
  const hasValidDelta = delta !== "" && Number.isInteger(parsedDelta) && parsedDelta !== 0;
  const projectedQuantity = item.quantity + (hasValidDelta ? parsedDelta : 0);
  // A proposed adjustment that would take the item below zero is caught
  // here too (not just server-side) -- catching it before the confirm
  // step even renders is a better experience than letting an admin
  // confirm something the server is just going to reject anyway.
  const wouldGoNegative = hasValidDelta && projectedQuantity < 0;

  if (!editing) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setEditing(true)}
          className={BUTTON_CLASS}
          aria-label={`Adjust quantity for ${item.name}`}
        >
          Adjust
        </button>
        <button
          type="button"
          onClick={() => setShowHistory((v) => !v)}
          className={BUTTON_CLASS}
          aria-label={`${showHistory ? "Hide" : "Show"} adjustment history for ${item.name}`}
        >
          {showHistory ? "Hide history" : "History"}
        </button>
        {showHistory && (
          <div className="mt-2 w-full rounded border border-border p-2 text-sm">
            {historyQuery.isLoading && <p className="text-fg-muted">Loading...</p>}
            {historyQuery.isError && (
              <p role="alert" className="text-accent-red">
                Could not load adjustment history.
              </p>
            )}
            {historyQuery.data?.length === 0 && (
              <p className="text-fg-muted">No adjustments recorded yet.</p>
            )}
            {historyQuery.data?.map((adj) => (
              <div key={adj.id} className="border-b border-border py-1 last:border-b-0">
                <span className="text-fg-primary">
                  {adj.quantity_before} {"->"} {adj.quantity_after}
                </span>
                <span className="text-fg-muted"> ({adj.delta > 0 ? "+" : ""}{adj.delta})</span>
                {" -- "}
                <span className="text-fg-muted">{adj.reason}</span>
                <span className="block text-xs text-fg-muted">
                  {new Date(adj.created_at).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded border border-border p-2">
      <div className="flex flex-wrap items-end gap-2">
        <div>
          <label htmlFor={`delta-${item.id}`} className={LABEL_CLASS}>
            Change by
          </label>
          <input
            id={`delta-${item.id}`}
            type="number"
            step={1}
            placeholder="+5 or -3"
            value={delta}
            onChange={(e) => setDelta(e.target.value)}
            className={`${INPUT_CLASS} w-24`}
          />
        </div>
        <div className="min-w-[10rem] flex-1">
          <label htmlFor={`reason-${item.id}`} className={LABEL_CLASS}>
            Reason
          </label>
          <input
            id={`reason-${item.id}`}
            type="text"
            placeholder="restocked, sold, damaged..."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
      </div>
      {/* The actual diff -- shown BEFORE the confirm button is even
          clickable, not just an alert() after the fact. */}
      {hasValidDelta && (
        <p
          data-testid={`diff-${item.id}`}
          className={`text-base ${wouldGoNegative ? "text-accent-red" : "text-fg-primary"}`}
        >
          Quantity will change from <strong>{item.quantity}</strong> to{" "}
          <strong>{projectedQuantity}</strong>
          {wouldGoNegative && " -- not allowed, quantity can't go below zero"}
        </p>
      )}
      {adjustMutation.isError && (
        <p role="alert" className="text-base text-accent-red">
          Could not save this adjustment.
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => adjustMutation.mutate()}
          disabled={
            !hasValidDelta || !reason.trim() || wouldGoNegative || adjustMutation.isPending
          }
          className={BUTTON_CLASS}
        >
          Confirm adjustment
        </button>
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setDelta("");
            setReason("");
          }}
          className={BUTTON_CLASS}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// Inline unit-cost editor -- the only way to actually populate what a
// BOM's material-cost computation needs (api/bom.ts's getBomCostBreakdown
// 422s on any material line whose item has no unit_cost set at all).
function UnitCostControl({ item }: { item: InventoryItem }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(item.unit_cost ?? "");

  const mutation = useMutation({
    mutationFn: () => setItemUnitCost(item.id, value),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "inventory"] });
      setEditing(false);
    },
  });

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="text-fg-primary underline"
        aria-label={`Set unit cost for ${item.name}`}
      >
        {item.unit_cost ? `$${item.unit_cost}` : "Set cost"}
      </button>
    );
  }

  return (
    <div className="flex items-center gap-1">
      <input
        type="number"
        step="0.0001"
        min="0"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className={`${INPUT_CLASS} w-20`}
      />
      <button
        type="button"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
        className={BUTTON_CLASS}
      >
        Save
      </button>
      <button type="button" onClick={() => setEditing(false)} className={BUTTON_CLASS}>
        Cancel
      </button>
    </div>
  );
}

// TODO(logan): location management + tag/full-text search filters, see
// docs/design/06-inventory.md. This wires up list + create against a
// single default location for now.
export function AdminInventory() {
  const queryClient = useQueryClient();
  const {
    data: items,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["admin", "inventory"],
    queryFn: listInventoryItems,
  });

  const [name, setName] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [locationId, setLocationId] = useState("");

  const createMutation = useMutation({
    mutationFn: createInventoryItem,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "inventory"] });
      setName("");
      setQuantity(1);
    },
  });

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-8">
      <h1 className="mb-6 text-2xl text-fg-primary">Inventory (admin)</h1>

      <form
        className="mb-8 flex flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          createMutation.mutate({
            name,
            quantity,
            location_id: locationId,
            description: null,
            tags: [],
          });
        }}
      >
        <div>
          <label htmlFor="name" className={LABEL_CLASS}>
            Name
          </label>
          <input
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label htmlFor="quantity" className={LABEL_CLASS}>
            Quantity
          </label>
          <input
            id="quantity"
            type="number"
            min={1}
            value={quantity}
            onChange={(e) => setQuantity(Number(e.target.value))}
            required
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label htmlFor="locationId" className={LABEL_CLASS}>
            Location ID
          </label>
          <input
            id="locationId"
            value={locationId}
            onChange={(e) => setLocationId(e.target.value)}
            required
            className={INPUT_CLASS}
          />
        </div>
        <button
          type="submit"
          disabled={createMutation.isPending}
          className={BUTTON_CLASS}
        >
          Add item
        </button>
      </form>

      {isLoading && <p className="text-base text-fg-muted">Loading...</p>}
      {isError && (
        <p role="alert" className="text-base text-accent-red">
          Failed to load inventory.
        </p>
      )}
      {items && (
        <div className="w-full overflow-x-auto">
          <table className="w-full min-w-[480px] text-base text-fg-primary">
            <thead>
              <tr className="border-b border-border text-left">
                <th className="p-2">Name</th>
                <th className="p-2">Quantity</th>
                <th className="p-2">Tags</th>
                <th className="p-2">Unit cost</th>
                <th className="p-2">Adjust</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-b border-border">
                  <td className="p-2">{item.name}</td>
                  <td className="p-2">{item.quantity}</td>
                  <td className="p-2">{item.tags.join(", ")}</td>
                  <td className="p-2">
                    <UnitCostControl item={item} />
                  </td>
                  <td className="p-2">
                    <AdjustQuantityControl item={item} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
