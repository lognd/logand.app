from __future__ import annotations

import os
import platform
from importlib.metadata import PackageNotFoundError, distributions, version

from fastapi import APIRouter, Depends

from logand_backend.auth.sessions import SessionInfo, require_admin

router = APIRouter(prefix="/api/admin/version", tags=["admin", "version"])


def _app_version() -> str:
    try:
        return version("logand-backend")
    except PackageNotFoundError:
        # Not pip-installed as a real distribution (e.g. `uv run` against
        # a raw source checkout with no build step) -- not an error state,
        # just means this specific lookup has nothing to report.
        return "unknown (not installed as a package)"


def _dependency_versions() -> dict[str, str]:
    # EVERY installed distribution, not just backend/pyproject.toml's own
    # direct dependencies -- "what version of dependencies, everything"
    # was the explicit ask. This reflects what's ACTUALLY resolved and
    # installed in this exact environment right now (via importlib.metadata,
    # not by re-parsing pyproject.toml/uv.lock), so it stays correct even
    # if a lockfile update changed a transitive dependency's version
    # without anyone touching this endpoint.
    return {
        dist.metadata["Name"]: dist.version
        for dist in distributions()
        if dist.metadata["Name"]
    }


@router.get("")
async def get_version_info(
    _admin: SessionInfo = Depends(require_admin),
) -> dict:
    """Everything needed to answer "what is actually running on this
    server right now" without SSHing in -- same motivation as
    api/admin_logs.py, just for version/environment info instead of log
    output. Admin-only: dependency version lists are a real
    fingerprinting/recon surface for an attacker, not public information.
    """
    return {
        "app_version": _app_version(),
        # Baked in at Docker build time (see Dockerfile's GIT_COMMIT ARG
        # and .github/workflows/deploy.yml) -- "unknown" outside a real
        # built-and-deployed image (e.g. local `uv run`), which is
        # honest: there's no .git directory in the image to introspect
        # at runtime instead.
        "git_commit": os.environ.get("GIT_COMMIT", "unknown"),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": dict(
            sorted(_dependency_versions().items(), key=lambda kv: kv[0].lower())
        ),
    }
