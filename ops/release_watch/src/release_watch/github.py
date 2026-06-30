from __future__ import annotations

import httpx
from pydantic import BaseModel
from typani.error_set import ErrorSet
from typani.result import Err, Ok, Result


class ReleaseError(ErrorSet):
    NotFound = "Repository has no releases"
    RateLimited = "GitHub API rate limit exceeded"
    NetworkError = "Could not reach GitHub API"


class Release(BaseModel):
    model_config = {}

    tag_name: str
    html_url: str
    published_at: str


def fetch_latest_release(
    repo: str, token: str | None = None
) -> Result[Release, ReleaseError]:
    """Hits GET /repos/{repo}/releases/latest. `repo` is "owner/name"."""
    headers = {"Accept": "application/vnd.github+json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        resp = httpx.get(url, headers=headers, timeout=10.0)
    except httpx.HTTPError:
        return Err(ReleaseError.NetworkError)

    if resp.status_code == 404:
        return Err(ReleaseError.NotFound)
    if resp.status_code == 403:
        return Err(ReleaseError.RateLimited)
    if resp.status_code != 200:
        return Err(ReleaseError.NetworkError)

    body = resp.json()
    return Ok(
        Release(
            tag_name=body["tag_name"],
            html_url=body["html_url"],
            published_at=body["published_at"],
        )
    )
