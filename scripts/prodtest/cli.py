"""Entry point: `uv run python -m scripts.prodtest.cli` (from the repo
root, with backend's venv active so `httpx`/`python-dotenv` resolve --
see README.md for the exact invocation and one-time setup).

Deliberately NOT wired into any CI workflow (.github/workflows/*.yml) --
this hits the real production site and a real customer-facing domain on
every run. Run it by hand, whenever you want live confidence in prod,
never on every push. scripts/prodtest/tests/ (the harness's own unit
tests, no network) is what runs in CI instead -- see that directory's
own README note and ci.yml's prodtest-self-test job.
"""

from __future__ import annotations

import argparse
import sys

from scripts.prodtest.env import ProdEnv
from scripts.prodtest.probes import ALL_PROBES
from scripts.prodtest.revert import Probe
from scripts.prodtest.runner import FAIL, SKIP, ProbeOutcome, format_report, run_all


def select_probes(
    probes: list[Probe], keyword: str | None
) -> tuple[list[Probe], list[Probe]]:
    """Splits `probes` into (selected, skipped) by a pytest `-k`-style
    case-insensitive substring match against each probe's `name`. No
    keyword means everything is selected and nothing is skipped -- pure
    logic, no network, so it's covered by a real unit test in
    tests/test_cli_filter.py rather than only ever being exercised by a
    live run against production.
    """
    if not keyword:
        return probes, []
    needle = keyword.lower()
    selected = [p for p in probes if needle in p.name.lower()]
    skipped = [p for p in probes if needle not in p.name.lower()]
    return selected, skipped


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Black-box production test suite for logand.app. "
        "Hits the real running site over HTTPS and the real VPS over SSH. "
        "Every probe reverts everything it creates -- see revert.py."
    )
    parser.add_argument(
        "--env-file",
        default=None,
        help="Path to a .env file (default: scripts/prodtest/.env via python-dotenv's "
        "normal cwd-upward search)",
    )
    parser.add_argument(
        "-k",
        dest="keyword",
        default=None,
        help="Only run probes whose name contains this substring (pytest -k "
        "style, case-insensitive), e.g. `-k notifications` to run just the "
        "email-sending probes. Probes that don't match are reported as SKIP, "
        "same as a capability-gated skip, so the summary line still "
        "accounts for every probe in ALL_PROBES.",
    )
    args = parser.parse_args()

    env = ProdEnv.from_dotenv(args.env_file)
    selected, skipped = select_probes(ALL_PROBES, args.keyword)

    print(f"Target: {env.base_url}  (SSH host alias: {env.ssh_host_alias})")
    if args.keyword:
        print(
            f"Running {len(selected)}/{len(ALL_PROBES)} probes matching "
            f"-k {args.keyword!r} against PRODUCTION. This makes real writes.\n"
        )
    else:
        print(
            f"Running {len(selected)} probes against PRODUCTION. "
            "This makes real writes.\n"
        )

    outcomes = run_all(selected, env)
    outcomes.extend(
        ProbeOutcome(p.name, SKIP, f"excluded by -k {args.keyword!r}", 0.0)
        for p in skipped
    )
    print(format_report(outcomes))

    return 1 if any(o.status == FAIL for o in outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
