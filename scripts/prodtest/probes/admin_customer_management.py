from __future__ import annotations

import uuid

from scripts.prodtest.admin_data_helper import hard_delete_row, row_exists
from scripts.prodtest.admin_session import get_shared_admin_client, login_with_backoff
from scripts.prodtest.env import ProdEnv
from scripts.prodtest.http_client import ProdHttpClient
from scripts.prodtest.revert import Cleanup, Probe


class AdminCustomerManagementProbe(Probe):
    name = "admin_customers.full_lifecycle_on_dummy_user"
    description = (
        "Registers a real dummy customer, then as admin: finds them via "
        "the customer search/lookup list, views their detail, deactivates "
        "them (confirms the account can no longer log in), reactivates "
        "them (confirms login works again), resets their password (confirms "
        "the OLD password is rejected and the NEW one works), then "
        "hard-deletes the dummy account -- the full real admin_users.py "
        "surface, end to end, against the real running site. Uses "
        "login_with_backoff for the four real customer-side login checks "
        "this needs -- these are separate from the shared admin session "
        "and count against the same IP-wide login rate limit as every "
        "other probe, so a 429 here becomes a real wait, not a failure."
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        admin_client = get_shared_admin_client(env)
        test_email = f"prodtest-admin-mgmt-{uuid.uuid4()}@example.invalid"
        original_password = "prodtest-harness-original-1"
        reset_password = "prodtest-harness-reset-2"

        register_client = ProdHttpClient(env.base_url)
        register = register_client.post(
            "/api/auth/register",
            json={"email": test_email, "password": original_password},
        )
        assert register.status_code == 200, register.text
        user_id = register_client.get("/api/me").json()["user_id"]
        register_client.logout()
        register_client.close()

        def _delete_dummy_user() -> None:
            hard_delete_row(admin_client, "users", user_id)
            if row_exists(admin_client, "users", user_id):
                raise RuntimeError(f"dummy user {user_id} still exists")

        cleanup.defer(
            f"hard-delete prodtest dummy customer {test_email}", _delete_dummy_user
        )

        # 1. Findable through the admin customer picker (substring,
        # case-insensitive, per admin_users.py's own doc comment).
        search = admin_client.get(
            "/api/admin/customers", params={"q": test_email.split("@")[0][:20]}
        )
        assert search.status_code == 200, search.text
        assert any(row["id"] == user_id for row in search.json()), search.json()

        # 2. Detail view.
        detail = admin_client.get(f"/api/admin/customers/{user_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["email"] == test_email
        assert detail.json()["role"] == "customer"
        assert detail.json()["disabled_at"] is None

        # 3. Deactivate -- account must lose login ability immediately.
        deactivate = admin_client.post(f"/api/admin/customers/{user_id}/deactivate")
        assert deactivate.status_code == 200, deactivate.text

        detail_after_deactivate = admin_client.get(f"/api/admin/customers/{user_id}")
        assert detail_after_deactivate.json()["disabled_at"] is not None

        with ProdHttpClient(env.base_url) as blocked_client:
            blocked_login = login_with_backoff(
                blocked_client, test_email, original_password
            )
            assert blocked_login.status_code in (401, 403), (
                f"deactivated account should not be able to log in, "
                f"got {blocked_login.status_code}: {blocked_login.text}"
            )

        # 4. Reactivate -- login must work again.
        reactivate = admin_client.post(f"/api/admin/customers/{user_id}/reactivate")
        assert reactivate.status_code == 200, reactivate.text

        detail_after_reactivate = admin_client.get(f"/api/admin/customers/{user_id}")
        assert detail_after_reactivate.json()["disabled_at"] is None

        with ProdHttpClient(env.base_url) as reactivated_client:
            revived_login = login_with_backoff(
                reactivated_client, test_email, original_password
            )
            assert revived_login.status_code == 200, (
                f"reactivated account should log in again, "
                f"got {revived_login.status_code}: {revived_login.text}"
            )
            reactivated_client.logout()

        # 5. Admin-forced password reset -- old password rejected, new
        # password accepted.
        reset = admin_client.post(
            f"/api/admin/customers/{user_id}/reset-password",
            json={"new_password": reset_password},
        )
        assert reset.status_code == 200, reset.text

        with ProdHttpClient(env.base_url) as post_reset_client:
            old_pw_login = login_with_backoff(
                post_reset_client, test_email, original_password
            )
            assert old_pw_login.status_code == 401, (
                f"old password must be rejected after admin reset, "
                f"got {old_pw_login.status_code}"
            )
            assert not post_reset_client.is_authenticated

        with ProdHttpClient(env.base_url) as final_client:
            new_pw_login = login_with_backoff(final_client, test_email, reset_password)
            assert new_pw_login.status_code == 200, (
                f"new password must work after admin reset, "
                f"got {new_pw_login.status_code}: {new_pw_login.text}"
            )
            final_client.logout()
