from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class Config(BaseModel):
    model_config = {}

    # owner/repo on GitHub, e.g. "lognd/logand.app"
    github_repo: str = "lognd/logand.app"

    # Where the last-deployed tag is recorded. Lives outside the repo checkout so a
    # `git pull` / redeploy never clobbers it.
    state_path: Path = Path("/var/lib/logand/deployed_version")

    # Directory containing docker-compose.yml on the VPS.
    compose_dir: Path = Path("/srv/logand-app")

    # Optional GitHub token to raise the unauthenticated rate limit (60/hr -> 5000/hr).
    # NOTE(logan): if set via env var, this is read through os.environ by from_external,
    # never by reading a .env file directly -- see ~/.claude/refs and docs/design/00-overview.md.
    github_token: str | None = None

    poll_interval_seconds: int = 300

    @classmethod
    def from_external(cls, env: dict[str, str]) -> "Config":
        merged: dict[str, object] = {}
        if "RELEASE_WATCH_REPO" in env:
            merged["github_repo"] = env["RELEASE_WATCH_REPO"]
        if "RELEASE_WATCH_STATE_PATH" in env:
            merged["state_path"] = Path(env["RELEASE_WATCH_STATE_PATH"])
        if "RELEASE_WATCH_COMPOSE_DIR" in env:
            merged["compose_dir"] = Path(env["RELEASE_WATCH_COMPOSE_DIR"])
        if "GITHUB_TOKEN" in env:
            merged["github_token"] = env["GITHUB_TOKEN"]
        if "RELEASE_WATCH_POLL_INTERVAL_SECONDS" in env:
            merged["poll_interval_seconds"] = int(
                env["RELEASE_WATCH_POLL_INTERVAL_SECONDS"]
            )
        return cls(**merged)
