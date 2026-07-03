from __future__ import annotations

from scripts.prodtest.admin_data_helper import hard_delete_row, row_exists
from scripts.prodtest.admin_session import get_shared_admin_client
from scripts.prodtest.env import ProdEnv
from scripts.prodtest.revert import Cleanup, Probe


class ReceiptUploadDeleteProbe(Probe):
    name = "receipts.capture_soft_delete_then_hard_delete"
    description = (
        "Captures a receipt (photo/PDF + metadata), confirms it downloads "
        "back byte-identical, calls the real DELETE route (soft-delete "
        "only, same as documents), then hard-deletes the row and the "
        "storage file"
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        admin_client = get_shared_admin_client(env)
        contents = b"fake-jpeg-bytes-prodtest-harness"

        create = admin_client.post(
            "/api/admin/receipts",
            params={
                "vendor": "prodtest harness vendor",
                "amount": "5.00",
                "category": "prodtest-harness",
                "occurred_on": "2020-01-01",
                "note": "created and deleted automatically by scripts/prodtest",
            },
            files={"file": ("prodtest.jpg", contents, "image/jpeg")},
        )
        assert create.status_code == 200, create.text
        receipt_id = create.json()["id"]
        file_path = f"receipts/{receipt_id}/prodtest.jpg"

        def _remove_all_traces() -> None:
            admin_client.delete(f"/api/admin/receipts/{receipt_id}")
            hard_delete_row(admin_client, "receipts", receipt_id)
            if row_exists(admin_client, "receipts", receipt_id):
                raise RuntimeError(f"receipt {receipt_id} row still exists")
            if env.ssh.is_reachable():
                full_path = f"{env.storage_local_dir}/{file_path}"
                env.ssh.docker_exec(env.backend_container, "rm", "-f", full_path)
                if env.ssh.file_exists_in_container(env.backend_container, full_path):
                    raise RuntimeError(f"receipt file {file_path} still exists on disk")

        cleanup.defer(f"remove prodtest receipt {receipt_id}", _remove_all_traces)

        download = admin_client.get(f"/api/admin/receipts/{receipt_id}/file")
        assert download.status_code == 200, download.text
        assert download.content == contents

        listing = admin_client.get(
            "/api/admin/receipts", params={"category": "prodtest-harness"}
        )
        assert listing.status_code == 200, listing.text
        assert any(r["id"] == receipt_id for r in listing.json()), listing.json()
