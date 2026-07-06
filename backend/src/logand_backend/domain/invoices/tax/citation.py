from __future__ import annotations

from urllib.parse import urlparse

from logand_backend.logging import get_logger

_log = get_logger(__name__)

# Government-citation policy (docs/design/16-sales-tax.md): every admin-
# entered tax_rules row must cite a government source URL. Claude only ever
# classifies items into categories -- it never sets or approves a rate. This
# is the one place that decides whether a URL counts as "government."


def is_government_source(url: str, allowed_domains: list[str]) -> bool:
    """True if `url` is a valid http(s) URL whose host is a .gov/.mil/.us
    domain, or ends with one of `allowed_domains` (e.g. a state revenue
    site like floridarevenue.com that doesn't happen to be under .gov)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host.endswith(".gov") or host.endswith(".mil") or host.endswith(".us"):
        return True
    for domain in allowed_domains:
        domain = domain.strip().lower()
        if not domain:
            continue
        if host == domain or host.endswith("." + domain):
            return True
    return False


def assert_government_citation(url: str, allowed_domains: list[str]) -> None:
    """Raises ValueError with a clear message if `url` doesn't satisfy
    is_government_source. Used at the point a rate is about to be written,
    so a non-government citation can never reach the tax_rules table."""
    if is_government_source(url, allowed_domains):
        return
    _log.warning(
        "tax citation rejected: not a recognized government source",
        extra={"url": url, "allowed_domains": allowed_domains},
    )
    accepted = ", ".join([".gov", ".mil", ".us", *allowed_domains])
    raise ValueError(
        f"citation_url {url!r} is not a recognized government source "
        f"(accepted: {accepted})"
    )
