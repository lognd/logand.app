from __future__ import annotations

from scripts.prodtest.admin_data_helper import hard_delete_row, row_exists
from scripts.prodtest.admin_session import get_shared_admin_client
from scripts.prodtest.env import ProdEnv
from scripts.prodtest.revert import Cleanup, Probe


class DocumentUploadDeleteProbe(Probe):
    name = "documents.upload_soft_delete_then_hard_delete"
    description = (
        "Uploads a real document file, confirms it downloads back byte-"
        "identical, calls the real DELETE route (domain/documents/service.py's "
        "delete_document is soft-delete only -- sets deleted_at, leaves the "
        "row and the storage file), then hard-deletes the row and the file "
        "so nothing is left over"
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        admin_client = get_shared_admin_client(env)
        contents = b"%PDF-1.4 prodtest harness fake document bytes"

        create = admin_client.post(
            "/api/admin/documents",
            params={"title": "prodtest harness document", "category": "other"},
            files={"file": ("prodtest.pdf", contents, "application/pdf")},
        )
        assert create.status_code == 200, create.text
        document_id = create.json()["id"]
        file_path = f"documents/{document_id}/prodtest.pdf"

        def _remove_all_traces() -> None:
            # The real DELETE route first, exercising the actual soft-
            # delete code path a real admin uses...
            admin_client.delete(f"/api/admin/documents/{document_id}")
            # ...then hard-delete, since soft-delete alone leaves a real
            # row (deleted_at set, but still a row) -- unacceptable for
            # "zero artifacts left."
            hard_delete_row(admin_client, "documents", document_id)
            if row_exists(admin_client, "documents", document_id):
                raise RuntimeError(f"document {document_id} row still exists")
            if env.ssh.is_reachable():
                full_path = f"{env.storage_local_dir}/{file_path}"
                env.ssh.docker_exec(env.backend_container, "rm", "-f", full_path)
                if env.ssh.file_exists_in_container(env.backend_container, full_path):
                    raise RuntimeError(
                        f"document file {file_path} still exists on disk"
                    )

        cleanup.defer(f"remove prodtest document {document_id}", _remove_all_traces)

        download = admin_client.get(f"/api/admin/documents/{document_id}/file")
        assert download.status_code == 200, download.text
        assert download.content == contents, (
            "downloaded bytes must match uploaded bytes"
        )

        listing = admin_client.get("/api/admin/documents", params={"category": "other"})
        assert listing.status_code == 200, listing.text
        assert any(d["id"] == document_id for d in listing.json()), listing.json()
