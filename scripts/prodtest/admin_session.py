"""One shared, process-wide admin session, reused by every probe that
just needs to act as an admin (create an invoice, upload a document,
etc). Production's login rate limiter (auth/rate_limit.py's LOGIN =
(5, 15*60), IP-keyed, shared across every account) means a harness that
logged in fresh per probe would blow through its own budget almost
immediately -- confirmed by an actual dry run against production, not a
theoretical concern (see README.md). Only the probes that specifically
test login/rate-limiting mechanics (auth_flow.py) perform their own
dedicated login calls, and they use login_with_backoff below so a 429
becomes a real wait, not a false failure.
"""

from __future__ import annotations

import time

import httpx

from scripts.prodtest.env import ProdEnv
from scripts.prodtest.http_client import ProdHttpClient

_shared_clients: dict[tuple[str, str], ProdHttpClient] = {}


def login_with_backoff(
    client: ProdHttpClient, email: str, password: str, *, max_wait_s: float = 920.0
) -> httpx.Response:
    """Logs in, honoring a 429's Retry-After by sleeping and retrying
    once rather than treating "another probe already used the shared
    IP-wide login budget this window" as this probe's own failure. Only
    retries on 429 -- any other status is returned immediately, since
    that's a real result (wrong password, 200 success, etc), not
    something backoff can fix.
    """
    resp = client.login(email, password)
    if resp.status_code != 429:
        return resp

    retry_after = resp.headers.get("Retry-After")
    wait_s = (
        min(float(retry_after), max_wait_s) if retry_after else min(60.0, max_wait_s)
    )
    time.sleep(wait_s)
    return client.login(email, password)


def get_shared_admin_client(env: ProdEnv) -> ProdHttpClient:
    """Returns a single, process-wide, already-authenticated admin
    ProdHttpClient for `env`, logging in (with backoff) only the first
    time it's requested. NOT closed/logged-out by callers -- it outlives
    any one probe by design; runner.py logs it out once at the very end
    of the whole run (see main_run_all_and_logout_shared_session below).
    """
    key = (env.base_url, env.admin_email)
    existing = _shared_clients.get(key)
    if existing is not None and existing.is_authenticated:
        return existing

    client = ProdHttpClient(env.base_url)
    resp = login_with_backoff(client, env.admin_email, env.admin_password)
    if resp.status_code != 200:
        raise RuntimeError(
            f"shared admin session login failed: {resp.status_code} {resp.text}"
        )
    _shared_clients[key] = client
    return client


def close_all_shared_clients() -> None:
    for client in _shared_clients.values():
        try:
            client.logout()
        except Exception:  # noqa: BLE001 -- best-effort, run is ending regardless
            pass
        client.close()
    _shared_clients.clear()
