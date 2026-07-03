from __future__ import annotations

import uuid

from scripts.prodtest.admin_data_helper import hard_delete_row, row_exists
from scripts.prodtest.admin_session import get_shared_admin_client, login_with_backoff
from scripts.prodtest.env import ProdEnv
from scripts.prodtest.http_client import ProdHttpClient
from scripts.prodtest.revert import Cleanup, Probe


class AdminLoginCsrfLogoutProbe(Probe):
    name = "auth.admin_login_csrf_session_logout"
    description = (
        "One dedicated (non-shared) admin login exercises three things "
        "at once, to stay inside production's real IP-wide login rate "
        "limit (auth/rate_limit.py's LOGIN = 5/15min, shared across every "
        "account -- confirmed the hard way on a first dry run against "
        "prod): /api/me reports role=admin after login, a mutating "
        "request with the session cookie but no CSRF header is rejected "
        "403, and logout actually kills the session (/api/me 401s after)."
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        with ProdHttpClient(env.base_url) as client:
            resp = login_with_backoff(client, env.admin_email, env.admin_password)
            assert resp.status_code == 200, (
                f"admin login failed: {resp.status_code} {resp.text}"
            )

            me = client.get("/api/me")
            assert me.status_code == 200, me.text
            assert me.json()["role"] == "admin", me.json()

            # Bypass ProdHttpClient's automatic CSRF header attachment to
            # simulate a forged cross-site request: real session cookie
            # (sent automatically), no CSRF header (an attacker's origin
            # can't read our non-HttpOnly CSRF cookie to forge one --
            # that's the double-submit pattern's whole point).
            forged = client._client.post(  # noqa: SLF001 -- deliberately bypassing the helper
                "/api/admin/budget",
                params={
                    "amount": "1.00",
                    "category": "prodtest-should-never-be-created",
                    "occurred_on": "2020-01-01",
                },
            )
            assert forged.status_code == 403, (
                f"expected CSRF rejection (403), got "
                f"{forged.status_code}: {forged.text}"
            )

            logout = client.logout()
            assert logout.status_code == 200, logout.text

            me_after = client.get("/api/me")
            assert me_after.status_code == 401, (
                f"session should be dead after logout, got {me_after.status_code}"
            )


class WrongPasswordRejectedProbe(Probe):
    name = "auth.wrong_password_rejected"
    description = (
        "Logging in with the right email and a wrong password 401s "
        "and sets no session cookie"
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        with ProdHttpClient(env.base_url) as client:
            resp = login_with_backoff(
                client, env.admin_email, env.admin_password + "-wrong"
            )
            assert resp.status_code == 401, f"expected 401, got {resp.status_code}"
            assert not client.is_authenticated, (
                "a failed login must not set a session cookie"
            )


class CustomerRegisterLoginLogoutProbe(Probe):
    name = "auth.customer_register_login_logout"
    description = (
        "Self-registration creates a customer (never admin) account; "
        "that account can log in and out; the account is hard-deleted "
        "afterward"
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        test_email = f"prodtest-{uuid.uuid4()}@example.invalid"
        test_password = "prodtest-harness-password-1"

        with ProdHttpClient(env.base_url) as customer_client:
            register = customer_client.post(
                "/api/auth/register",
                json={"email": test_email, "password": test_password},
            )
            assert register.status_code == 200, register.text

            me = customer_client.get("/api/me")
            assert me.status_code == 200, me.text
            assert me.json()["role"] == "customer", (
                f"self-registration must never create an admin, got {me.json()}"
            )
            user_id = me.json()["user_id"]

            def _delete_test_user() -> None:
                admin_client = get_shared_admin_client(env)
                hard_delete_row(admin_client, "users", user_id)
                if row_exists(admin_client, "users", user_id):
                    raise RuntimeError(
                        f"user {user_id} still exists in the users table after delete"
                    )

            cleanup.defer(f"hard-delete prodtest user {test_email}", _delete_test_user)

            logout = customer_client.logout()
            assert logout.status_code == 200, logout.text

            me_after = customer_client.get("/api/me")
            assert me_after.status_code == 401


class SessionKillAllProbe(Probe):
    name = "auth.admin_kill_all_sessions"
    description = (
        "domain/auth/sessions.py::revoke_all_sessions_globally deletes every "
        "session row, including the caller's own -- verified end to end by "
        "checking the harness's own admin session dies too"
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        # There is deliberately no public HTTP route wired to
        # revoke_all_sessions_globally() yet (grepped api/*.py -- only
        # revoke_session/revoke_all_sessions_for_user are reachable over
        # HTTP today). Skip cleanly rather than reaching around the API
        # surface via SSH/raw SQL to exercise a function the product
        # doesn't actually expose to an admin yet.
        return "no HTTP route currently wires up revoke_all_sessions_globally()"

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        raise NotImplementedError("unreachable -- check_capability() always skips")
