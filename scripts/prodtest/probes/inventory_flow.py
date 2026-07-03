from __future__ import annotations

import uuid

from scripts.prodtest.admin_data_helper import hard_delete_row, row_exists
from scripts.prodtest.admin_session import get_shared_admin_client
from scripts.prodtest.env import ProdEnv
from scripts.prodtest.revert import Cleanup, Probe


class InventoryItemLifecycleProbe(Probe):
    name = "inventory.location_item_adjust_delete"
    description = (
        "Creates a real location and item, adjusts quantity (audited "
        "path), searches full-text for it, deletes the item via the real "
        "DELETE route (a genuine hard delete already -- see "
        "domain/inventory/service.py::delete_item), then hard-deletes "
        "the location (no delete route exists for locations at all)"
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        admin_client = get_shared_admin_client(env)
        location_name = f"prodtest-location-{uuid.uuid4()}"

        loc = admin_client.post(
            "/api/admin/inventory/locations", params={"name": location_name}
        )
        assert loc.status_code == 200, loc.text
        location_id = loc.json()["id"]

        def _delete_location() -> None:
            hard_delete_row(admin_client, "inventory_locations", location_id)
            if row_exists(admin_client, "inventory_locations", location_id):
                raise RuntimeError(f"location {location_id} still exists")

        # Deferred first (LIFO -> runs LAST), since inventory_items has
        # an ondelete=RESTRICT FK to inventory_locations -- the item
        # must be gone before the location delete is attempted.
        cleanup.defer(
            f"hard-delete prodtest location {location_name}", _delete_location
        )

        item_name = f"prodtest-item-{uuid.uuid4()}"
        item = admin_client.post(
            "/api/admin/inventory/items",
            params={
                "name": item_name,
                "location_id": location_id,
                "quantity": 10,
                "description": "prodtest harness item",
            },
        )
        assert item.status_code == 200, item.text
        item_id = item.json()["id"]

        def _delete_item() -> None:
            delete_resp = admin_client.delete(f"/api/admin/inventory/items/{item_id}")
            if delete_resp.status_code != 200:
                raise RuntimeError(
                    f"item delete failed: {delete_resp.status_code} {delete_resp.text}"
                )
            if row_exists(admin_client, "inventory_items", item_id):
                raise RuntimeError(f"item {item_id} still exists after DELETE route")

        cleanup.defer(f"delete prodtest item {item_name}", _delete_item)

        adjust = admin_client.post(
            f"/api/admin/inventory/items/{item_id}/adjust",
            json={"delta": -3, "reason": "prodtest harness adjustment"},
        )
        assert adjust.status_code == 200, adjust.text

        search = admin_client.get("/api/admin/inventory/items", params={"q": item_name})
        assert search.status_code == 200, search.text
        found = next((row for row in search.json() if row["id"] == item_id), None)
        assert found is not None, f"full-text search did not find {item_name}"
        assert found["quantity"] == 7, found
