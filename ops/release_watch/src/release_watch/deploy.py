from __future__ import annotations

import subprocess
from pathlib import Path

from typani.error_set import ErrorSet
from typani.result import Err, Ok, Result


class DeployError(ErrorSet):
    PullFailed = "docker compose pull failed"
    MigrateFailed = "migration job failed"
    UpFailed = "docker compose up failed"


def redeploy(compose_dir: Path) -> Result[None, DeployError]:
    """Pulls new images, runs the one-shot migration, then restarts backend + caddy.

    NOTE(logan): this is the pull-based counterpart to
    .github/workflows/deploy.yml's push-based deploy. Run this as a systemd
    timer / cron job on the VPS as a fallback reconciliation path -- if a
    push deploy fails partway (e.g. SSH action times out), this catches the
    drift on its next poll instead of leaving the VPS stuck on an old tag.
    """
    pull = subprocess.run(
        ["docker", "compose", "pull", "backend"], cwd=compose_dir, capture_output=True
    )
    if pull.returncode != 0:
        return Err(DeployError.PullFailed)

    migrate = subprocess.run(
        ["docker", "compose", "--profile", "migrate", "run", "--rm", "migrate"],
        cwd=compose_dir,
        capture_output=True,
    )
    if migrate.returncode != 0:
        return Err(DeployError.MigrateFailed)

    up = subprocess.run(
        ["docker", "compose", "up", "-d", "backend", "caddy"],
        cwd=compose_dir,
        capture_output=True,
    )
    if up.returncode != 0:
        return Err(DeployError.UpFailed)

    return Ok(None)
