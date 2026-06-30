from __future__ import annotations

import argparse
import os
import time

from dotenv import load_dotenv

from release_watch.config import Config
from release_watch.deploy import redeploy
from release_watch.github import fetch_latest_release
from release_watch.state import read_deployed_tag, write_deployed_tag


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="release-watch",
        description="Checks GitHub for a new tagged release and redeploys if found.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "check", help="check once, redeploy if a new tag is found, then exit"
    )
    sub.add_parser("watch", help="poll forever at the configured interval")
    return parser


def _check_once(cfg: Config) -> bool:
    """Returns True if a redeploy happened."""
    result = fetch_latest_release(cfg.github_repo, cfg.github_token)
    if result.is_err:
        print(f"release-watch: could not fetch latest release: {result.danger_err}")
        return False

    latest = result.danger_ok
    deployed = read_deployed_tag(cfg.state_path)

    if deployed.is_some and deployed.danger_some == latest.tag_name:
        print(f"release-watch: already on {latest.tag_name}, nothing to do")
        return False

    print(
        f"release-watch: new release {latest.tag_name} ({latest.html_url}), deploying"
    )
    deploy_result = redeploy(cfg.compose_dir)
    if deploy_result.is_err:
        print(f"release-watch: deploy failed: {deploy_result.danger_err}")
        return False

    write_deployed_tag(cfg.state_path, latest.tag_name)
    print(f"release-watch: deployed {latest.tag_name}")
    return True


def main() -> None:
    load_dotenv()
    args = _build_parser().parse_args()
    cfg = Config.from_external(dict(os.environ))

    if args.command == "check":
        _check_once(cfg)
        return

    # watch
    while True:
        _check_once(cfg)
        time.sleep(cfg.poll_interval_seconds)


if __name__ == "__main__":
    main()
