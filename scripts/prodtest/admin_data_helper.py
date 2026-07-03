"""Shared cleanup helper: hard-deletes a row through the real
/api/admin/data generic table route (api/admin_data.py) rather than
dropping to raw SQL over SSH wherever the API itself already exposes a
delete path for that table. Preferred over ssh_client.VpsSsh.psql_delete_row
whenever it works, since it exercises the same code path a real admin
using the admin data browser would use; SSH-level SQL is reserved for
tables genuinely append-only from the API's perspective (see
invoice_flow.py, budget_flow.py).

Every call here writes one AdminAuditLog row (api/admin_data.py's
delete_row route). That's an unavoidable, permanent, and correct
byproduct of using an audited admin action to clean up -- the audit log
exists specifically so that it never silently disappears, so this
harness does not attempt to remove its own audit trail. See the
harness README for why that's the honest tradeoff, not a gap.
"""

from __future__ import annotations

from scripts.prodtest.http_client import ProdHttpClient


def hard_delete_row(client: ProdHttpClient, table: str, row_id: str) -> None:
    resp = client.delete(f"/api/admin/data/tables/{table}/rows/{row_id}")
    if resp.status_code != 200:
        raise RuntimeError(
            f"admin_data hard delete failed for {table}/{row_id}: "
            f"{resp.status_code} {resp.text}"
        )


def row_exists(client: ProdHttpClient, table: str, row_id: str) -> bool:
    resp = client.get(f"/api/admin/data/tables/{table}/rows/{row_id}")
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    raise RuntimeError(
        f"admin_data row lookup failed for {table}/{row_id}: "
        f"{resp.status_code} {resp.text}"
    )
