"""Harness configuration -- loaded from scripts/prodtest/.env (see
.env.example in this directory), never from backend/.env. This is a
separate, harness-only credential: a real admin account on production
that this suite is allowed to log in as. Do not point SEED_ADMIN_* at
this file or vice versa.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from scripts.prodtest.ssh_client import VpsSsh


@dataclass(frozen=True)
class ProdEnv:
    base_url: str
    ssh_host_alias: str
    admin_email: str
    admin_password: str
    backend_container: str
    postgres_container: str
    db_user: str
    db_name: str
    storage_local_dir: str
    # The real address a notification-flow probe registers its throwaway
    # customer under (see probes/notification_flow.py) -- deliberately
    # configurable, not hardcoded to a specific person's inbox. Defaults
    # to a "prodtest" prefix under the deployment's own domain rather than
    # a made-up example.com address, since the whole point of this probe
    # is a REAL send through the REAL configured SMTP credentials; an
    # address nothing can actually deliver to would make the probe
    # meaningless. Override this if your domain's mail routing doesn't
    # forward every address to one inbox the way logand.app's catch-all
    # currently does, or if you'd rather use a dedicated mailbox instead
    # of piggybacking on the catch-all.
    notification_email: str

    @property
    def ssh(self) -> VpsSsh:
        return VpsSsh(self.ssh_host_alias)

    @classmethod
    def from_dotenv(cls, dotenv_path: str | None = None) -> "ProdEnv":
        load_dotenv(dotenv_path)

        def require(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(
                    f"{name} is not set -- copy scripts/prodtest/.env.example to "
                    f"scripts/prodtest/.env and fill it in."
                )
            return value

        return cls(
            base_url=os.environ.get("PRODTEST_BASE_URL", "https://logand.app"),
            ssh_host_alias=os.environ.get("PRODTEST_SSH_HOST", "hetzner"),
            admin_email=require("PRODTEST_ADMIN_EMAIL"),
            admin_password=require("PRODTEST_ADMIN_PASSWORD"),
            backend_container=os.environ.get(
                "PRODTEST_BACKEND_CONTAINER", "logandapp-backend-1"
            ),
            postgres_container=os.environ.get(
                "PRODTEST_POSTGRES_CONTAINER", "logandapp-postgres-1"
            ),
            db_user=os.environ.get("PRODTEST_DB_USER", "logand"),
            db_name=os.environ.get("PRODTEST_DB_NAME", "logand"),
            storage_local_dir=os.environ.get(
                "PRODTEST_STORAGE_LOCAL_DIR", "/app/data/storage"
            ),
            notification_email=os.environ.get(
                "PRODTEST_NOTIFICATION_EMAIL", "prodtest@logand.app"
            ),
        )
