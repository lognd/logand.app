"""Shared helper: runs the backend's own
`python -m logand_backend.scripts.health_check` INSIDE the deployed
container over SSH, and returns its full stdout for probes to inspect.

Deliberately reuses that script rather than re-implementing "is Stripe
configured/valid" or "is SMTP reachable" checks here -- it already does
the real, correct thing (a live `stripe.Balance.retrieve()` call, a real
TCP connect to SMTP_HOST:SMTP_PORT) and already reports exactly which
subsystem failed. Running it via SSH+docker exec, not importing it
directly, is what lets this check the REAL deployed backend/.env values
rather than whatever happens to be in this harness's own environment.

Zero mutation: every check `health_check.py` performs is read-only
(a Stripe balance read, a TCP connect, a Postgres `SELECT 1`, etc) --
nothing here needs a `cleanup.defer()`.
"""

from __future__ import annotations

from scripts.prodtest.env import ProdEnv
from scripts.prodtest.ssh_client import SshCommandError


def run_health_check(env: ProdEnv, *, skip_http: bool = True) -> str:
    """Returns the script's full stdout, regardless of its exit code.

    health_check.py exits 1 if ANY section fails (not just the one a
    given probe cares about -- e.g. a misconfigured backup destination
    would make this exit non-zero even though Stripe/SMTP are both
    fine). A non-zero exit therefore raises SshCommandError from
    docker_exec, but subprocess still captures stdout regardless of
    exit code -- pull the report out of the exception rather than
    losing it, so a caller can grep for the one section it's actually
    testing.
    """
    args = ["python", "-m", "logand_backend.scripts.health_check"]
    if skip_http:
        args.append("--skip-http")
    try:
        return env.ssh.docker_exec(env.backend_container, *args)
    except SshCommandError as exc:
        return exc.stdout
