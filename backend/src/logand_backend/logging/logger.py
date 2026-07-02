from __future__ import annotations

import logging
import logging.config
import os
import tomllib
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config.toml"
_initialized = False

# Every process (API server, scheduler, one-off scripts) writes to the
# SAME directory -- "centralized, not scattered" -- rather than each
# picking its own default. Overridable via LOG_DIR for containerized
# deployments (docker-compose mounts a shared volume here so the API and
# scheduler containers' logs land in one place on the host).
DEFAULT_LOG_DIR = "./logs"


def _init() -> None:
    global _initialized
    if _initialized:
        return
    with _CONFIG_PATH.open("rb") as f:
        cfg = tomllib.load(f)

    log_dir = Path(os.environ.get("LOG_DIR", DEFAULT_LOG_DIR))
    log_dir.mkdir(parents=True, exist_ok=True)
    cfg["handlers"]["file"]["filename"] = str(log_dir / "app.log")

    logging.config.dictConfig(cfg)
    _initialized = True


def get_logger(name: str) -> logging.Logger:
    _init()
    return logging.getLogger(name)


def log_dir() -> Path:
    """The directory get_logger() is (or will be) writing to -- shared by
    api/admin_logs.py to list/tail/download real log files without
    duplicating the LOG_DIR-resolution logic above."""
    return Path(os.environ.get("LOG_DIR", DEFAULT_LOG_DIR))
