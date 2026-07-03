from __future__ import annotations

from scripts.prodtest.env import ProdEnv
from scripts.prodtest.http_client import ProdHttpClient
from scripts.prodtest.revert import Cleanup, Probe


class HealthCheckProbe(Probe):
    name = "health.basic_reachability"
    description = (
        "GET /health returns 200; GET /api/me with no session returns "
        "401 (not 502/connection error)"
    )

    def check_capability(self, env: ProdEnv) -> bool | str:
        return True

    def execute(self, env: ProdEnv, cleanup: Cleanup) -> None:
        with ProdHttpClient(env.base_url) as client:
            health = client.get("/health")
            assert health.status_code == 200, f"/health returned {health.status_code}"

            me = client.get("/api/me")
            assert me.status_code == 401, (
                f"/api/me with no session should 401, got {me.status_code}"
            )
        # Nothing mutated -- no cleanup.defer() calls needed.
