import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createInventoryItem, listInventoryItems } from "../../../api/inventory";
import { BUTTON_CLASS, INPUT_CLASS, LABEL_CLASS } from "../../../styles/a11y";

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
            locationId,
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
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-b border-border">
                  <td className="p-2">{item.name}</td>
                  <td className="p-2">{item.quantity}</td>
                  <td className="p-2">{item.tags.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
