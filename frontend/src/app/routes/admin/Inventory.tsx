import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createInventoryItem, listInventoryItems } from "../../../api/inventory";

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
    <main>
      <h1>Inventory (admin)</h1>

      <form
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
        <label htmlFor="name">Name</label>
        <input
          id="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <label htmlFor="quantity">Quantity</label>
        <input
          id="quantity"
          type="number"
          min={1}
          value={quantity}
          onChange={(e) => setQuantity(Number(e.target.value))}
          required
        />
        <label htmlFor="locationId">Location ID</label>
        <input
          id="locationId"
          value={locationId}
          onChange={(e) => setLocationId(e.target.value)}
          required
        />
        <button type="submit" disabled={createMutation.isPending}>
          Add item
        </button>
      </form>

      {isLoading && <p>Loading...</p>}
      {isError && <p role="alert">Failed to load inventory.</p>}
      {items && (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Quantity</th>
              <th>Tags</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>{item.name}</td>
                <td>{item.quantity}</td>
                <td>{item.tags.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
