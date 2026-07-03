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
from scripts.prodtest.runner import FAIL, format_report, run_all


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
    args = parser.parse_args()

    env = ProdEnv.from_dotenv(args.env_file)

    print(f"Target: {env.base_url}  (SSH host alias: {env.ssh_host_alias})")
    print(
        f"Running {len(ALL_PROBES)} probes against PRODUCTION. "
        "This makes real writes.\n"
    )

    outcomes = run_all(ALL_PROBES, env)
    print(format_report(outcomes))

    return 1 if any(o.status == FAIL for o in outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
