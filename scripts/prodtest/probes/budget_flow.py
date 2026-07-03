from __future__ import annotations

from scripts.prodtest.admin_data_helper import hard_delete_row, row_exists
from scripts.prodtest.admin_session import get_shared_admin_client
from scripts.prodtest.env import ProdEnv
from scripts.prodtest.revert import Cleanup, Probe


class BudgetEntryLifecycleProbe(Probe):
    name = "budget.create_entry_and_upload_evidence"
    description = (
        "Admin creates a budget ledger entry and attaches evidence (an "
        "uploaded file); confirms it appears in the ledger listing; "
        "hard-deletes the entry (cascades the evidence row) and confirms "
        "the uploaded file is actually gone from disk on the VPS"
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        admin_client = get_shared_admin_client(env)

        create = admin_client.post(
            "/api/admin/budget",
            params={
                "amount": "12.34",
                "category": "prodtest-harness",
                "occurred_on": "2020-01-01",
                "vendor": "prodtest harness vendor",
                "memo": "created and deleted automatically by scripts/prodtest",
            },
        )
        assert create.status_code == 200, create.text
        entry_id = create.json()["id"]

        evidence_path_holder: dict[str, str] = {}

        def _delete_entry() -> None:
            # The DB row cascade (budget_evidence -> budget_entries,
            # ondelete=CASCADE) never touches the storage backend --
            # domain/budget/service.py's attach_evidence writes bytes to
            # storage separately from the DB row, and nothing in this
            # codebase deletes evidence files today (there's no "delete
            # budget entry" product feature at all, by design -- see
            # docs/design/05-budget.md's correction-not-overwrite
            # invariant). This harness must therefore remove the
            # uploaded bytes itself, explicitly.
            hard_delete_row(admin_client, "budget_entries", entry_id)
            if row_exists(admin_client, "budget_entries", entry_id):
                raise RuntimeError(f"budget entry {entry_id} still exists")
            path = evidence_path_holder.get("path")
            if path and env.ssh.is_reachable():
                full_path = f"{env.storage_local_dir}/{path}"
                env.ssh.docker_exec(env.backend_container, "rm", "-f", full_path)
                if env.ssh.file_exists_in_container(env.backend_container, full_path):
                    raise RuntimeError(f"evidence file {path} still exists on disk")

        cleanup.defer(f"hard-delete prodtest budget entry {entry_id}", _delete_entry)

        evidence = admin_client.post(
            f"/api/admin/budget/{entry_id}/evidence",
            files={
                "file": ("prodtest-evidence.png", b"\x89PNG-fake-bytes", "image/png")
            },
        )
        assert evidence.status_code == 200, evidence.text
        evidence_path_holder["path"] = (
            f"budget-evidence/{entry_id}/prodtest-evidence.png"
        )

        listing = admin_client.get(
            "/api/admin/budget", params={"category": "prodtest-harness"}
        )
        assert listing.status_code == 200, listing.text
        assert any(row["id"] == entry_id for row in listing.json()), listing.json()
