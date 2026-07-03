from __future__ import annotations

import time
import traceback
from dataclasses import dataclass

from scripts.prodtest.admin_session import close_all_shared_clients
from scripts.prodtest.env import ProdEnv
from scripts.prodtest.revert import Cleanup, Probe

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass
class ProbeOutcome:
    name: str
    status: str
    detail: str
    duration_s: float


def run_probe(probe: Probe, env: ProdEnv) -> ProbeOutcome:
    start = time.monotonic()

    try:
        capability = probe.check_capability(env)
    except Exception as exc:  # noqa: BLE001 -- a broken capability check is still a FAIL
        return ProbeOutcome(probe.name, FAIL, f"check_capability() raised: {exc}", 0.0)

    if capability is not True:
        reason = capability if isinstance(capability, str) else "capability not present"
        return ProbeOutcome(probe.name, SKIP, reason, time.monotonic() - start)

    cleanup = Cleanup()
    exec_error: str | None = None
    try:
        probe.execute(env, cleanup)
    except Exception:  # noqa: BLE001 -- must still run cleanup below
        exec_error = traceback.format_exc(limit=6)
    finally:
        cleanup_errors = cleanup.close()

    duration = time.monotonic() - start

    if cleanup_errors:
        # A cleanup failure is the worst outcome this harness can produce
        # (real artifacts may remain on production) -- always FAIL,
        # regardless of whether execute() itself succeeded, and say so
        # unmistakably rather than folding it into a generic error string.
        lines = "\n".join(f"  - {e.description}: {e.error}" for e in cleanup_errors)
        detail = (
            f"CLEANUP FAILED -- POSSIBLE PRODUCTION ARTIFACTS LEFT BEHIND:\n{lines}"
        )
        if exec_error:
            detail = f"{detail}\n\nAlso, execute() failed:\n{exec_error}"
        return ProbeOutcome(probe.name, FAIL, detail, duration)

    if exec_error:
        return ProbeOutcome(probe.name, FAIL, exec_error, duration)

    return ProbeOutcome(probe.name, PASS, "", duration)


def run_all(probes: list[Probe], env: ProdEnv) -> list[ProbeOutcome]:
    try:
        return [run_probe(probe, env) for probe in probes]
    finally:
        # The shared admin session (admin_session.py) outlives any one
        # probe by design -- log it out once here, after every probe
        # (including their cleanup) has finished, not per-probe.
        close_all_shared_clients()


def format_report(outcomes: list[ProbeOutcome]) -> str:
    lines = []
    width = max((len(o.name) for o in outcomes), default=4)
    for o in outcomes:
        lines.append(f"{o.status:>4}  {o.name.ljust(width)}  ({o.duration_s:.2f}s)")
        if o.detail:
            for detail_line in o.detail.splitlines():
                lines.append(f"        {detail_line}")
    passed = sum(1 for o in outcomes if o.status == PASS)
    failed = sum(1 for o in outcomes if o.status == FAIL)
    skipped = sum(1 for o in outcomes if o.status == SKIP)
    lines.append("")
    lines.append(f"{passed} passed, {failed} failed, {skipped} skipped")
    return "\n".join(lines)
