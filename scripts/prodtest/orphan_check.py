"""Standalone, reusable check for stray "prodtest"-tagged rows left in
production by a harness run that didn't finish cleanly -- e.g. an
operator killing the `cli.py` process from outside Python (SIGTERM/
SIGKILL bypasses every probe's own `finally: cleanup.close()` in
runner.py, since that only runs for an in-process exception, not an
external kill of the whole interpreter).

Every probe registers its throwaway customers with "prodtest" somewhere
in the local-part of the email (see env.py's `notification_email` and
each probe's own `uuid4().hex`-suffixed address), so searching
`/api/admin/customers?q=prodtest` is a complete, real audit of anything
a probe could have left behind -- not a raw SQL scan, and not guessing
from stdout that may not have flushed before a kill.

Run standalone (same .env/venv setup as cli.py -- see README.md):

    python -m scripts.prodtest.orphan_check          # report only
    python -m scripts.prodtest.orphan_check --delete # report + clean up

Cleanup goes through the same real, audited admin_data hard-delete
route every probe's own cleanup uses (`admin_data_helper.hard_delete_row`),
in the same FK order every probe already respects: refunds, then
payments, then invoices, then the customer row itself.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from scripts.prodtest.admin_data_helper import hard_delete_row, row_exists
from scripts.prodtest.admin_session import (
    close_all_shared_clients,
    get_shared_admin_client,
)
from scripts.prodtest.env import ProdEnv
from scripts.prodtest.http_client import ProdHttpClient

_PRODTEST_QUERY = "prodtest"


@dataclass
class OrphanedCustomer:
    user_id: str
    email: str
    invoice_ids: list[str] = field(default_factory=list)
    payment_ids: list[str] = field(default_factory=list)
    refund_ids: list[str] = field(default_factory=list)


def find_orphans(env: ProdEnv) -> list[OrphanedCustomer]:
    """Every "prodtest"-tagged customer still on production, with every
    invoice/payment/refund attached to them -- the full set a probe's own
    cleanup would have reverted had it run to completion."""
    admin_client = get_shared_admin_client(env)

    search = admin_client.get("/api/admin/customers", params={"q": _PRODTEST_QUERY})
    if search.status_code != 200:
        raise RuntimeError(
            f"customer search failed: {search.status_code} {search.text}"
        )

    orphans = []
    for row in search.json():
        user_id = row["id"]
        orphan = OrphanedCustomer(user_id=user_id, email=row["email"])

        invoices = admin_client.get(
            "/api/admin/invoices", params={"customer_id": user_id}
        )
        if invoices.status_code != 200:
            raise RuntimeError(
                f"invoice list failed for {user_id}: "
                f"{invoices.status_code} {invoices.text}"
            )
        for inv in invoices.json():
            orphan.invoice_ids.append(inv["id"])
            detail = admin_client.get(f"/api/admin/invoices/{inv['id']}")
            if detail.status_code != 200:
                raise RuntimeError(
                    f"invoice detail failed for {inv['id']}: "
                    f"{detail.status_code} {detail.text}"
                )
            for payment in detail.json().get("payments", []):
                orphan.payment_ids.append(payment["id"])
                for refund in payment.get("refunds", []):
                    orphan.refund_ids.append(refund["id"])

        orphans.append(orphan)
    return orphans


def delete_orphan(admin_client: ProdHttpClient, orphan: OrphanedCustomer) -> None:
    """FK order matches every probe's own cleanup: refunds, then
    payments, then invoices, then the customer row itself. Raises (not a
    Result -- this is a hand-run operator tool, not library code) if the
    customer row somehow survives its own delete."""
    for refund_id in orphan.refund_ids:
        hard_delete_row(admin_client, "refunds", refund_id)
    for payment_id in orphan.payment_ids:
        hard_delete_row(admin_client, "payments", payment_id)
    for invoice_id in orphan.invoice_ids:
        hard_delete_row(admin_client, "invoices", invoice_id)
    hard_delete_row(admin_client, "users", orphan.user_id)
    if row_exists(admin_client, "users", orphan.user_id):
        raise RuntimeError(f"customer {orphan.user_id} still exists after delete")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check production for stray 'prodtest'-tagged rows left "
        "by a harness run that didn't finish cleanly (e.g. an external kill "
        "mid-probe), and optionally clean them up."
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to a .env file (default: scripts/prodtest/.env, same as cli.py).",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually hard-delete anything found (default is report-only).",
    )
    args = parser.parse_args()

    env = ProdEnv.from_dotenv(args.env_file)
    print(f"Checking {env.base_url} for orphaned prodtest-tagged rows...")

    try:
        orphans = find_orphans(env)
        if not orphans:
            print("Clean -- 0 orphaned customers found.")
            return 0

        print(f"Found {len(orphans)} orphaned customer(s):")
        for orphan in orphans:
            print(
                f"  - {orphan.email} ({orphan.user_id}): "
                f"{len(orphan.invoice_ids)} invoice(s), "
                f"{len(orphan.payment_ids)} payment(s), "
                f"{len(orphan.refund_ids)} refund(s)"
            )

        if not args.delete:
            print("\nRe-run with --delete to remove these.")
            return 1

        admin_client = get_shared_admin_client(env)
        for orphan in orphans:
            delete_orphan(admin_client, orphan)
            print(f"  deleted {orphan.email}")
        print("Cleanup complete.")
        return 0
    finally:
        close_all_shared_clients()


if __name__ == "__main__":
    sys.exit(main())
