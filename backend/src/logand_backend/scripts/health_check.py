from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import uuid
from urllib.parse import urlsplit, urlunsplit

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from logand_backend.app.config import AppConfig
from logand_backend.domain.notifications import mailer
from logand_backend.domain.payments.providers import paypal
from logand_backend.domain.storage.base import StorageObjectNotFound
from logand_backend.domain.storage.factory import get_storage_backend
from logand_backend.scripts._health_logging import get_health_logger

log = get_health_logger()

# Values AppConfig ships as its own defaults -- real, but only ever
# meant for local dev/tests. A deployment still running with one of
# these is a real, loud problem (weak/shared secrets, talking to no
# real payment processor), not a "gracefully unconfigured" state like
# PayPal/SMTP being unset.
_DEV_DEFAULTS = {
    "session_secret": "dev-only-insecure-secret",
    "payment_processor_secret": "sk_test_fake",
    "stripe_webhook_secret": "whsec_fake",
}


def _redact_url(url: str) -> str:
    """host/db only -- never logs a password, even a fake one."""
    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


async def check_database(cfg: AppConfig) -> bool:
    engine = create_async_engine(cfg.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        log.ok(f"database: connected ({_redact_url(cfg.database_url)})")
        return True
    except Exception as exc:
        log.fail(
            f"database: could not connect to {_redact_url(cfg.database_url)} -- {exc}"
        )
        return False
    finally:
        await engine.dispose()


async def check_redis(cfg: AppConfig) -> bool:
    if cfg.redis_url is None:
        log.warn(
            "redis: not configured -- rate limiting falls back to an "
            "in-process counter (auth/rate_limit.py). Fine for a single "
            "backend instance; NOT shared across multiple replicas if you "
            "ever scale horizontally."
        )
        return True
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(cfg.redis_url, socket_connect_timeout=5)
        try:
            await client.ping()
        finally:
            await client.aclose()
        log.ok(f"redis: connected ({_redact_url(cfg.redis_url)})")
        return True
    except Exception as exc:
        log.fail(
            f"redis: configured ({_redact_url(cfg.redis_url)}) but unreachable -- {exc}"
        )
        return False


def check_dev_defaults(cfg: AppConfig) -> bool:
    ok = True
    for field, default_value in _DEV_DEFAULTS.items():
        if getattr(cfg, field) == default_value:
            log.fail(
                f"{field}: still set to the dev-only default value -- this "
                "MUST be a real, unique secret before this is a real "
                "deployment. See docs/secrets.md."
            )
            ok = False
    return ok


async def check_stripe(cfg: AppConfig) -> bool:
    if cfg.payment_processor_secret == _DEV_DEFAULTS["payment_processor_secret"]:
        return True  # already reported loudly by check_dev_defaults
    import stripe

    stripe.api_key = cfg.payment_processor_secret
    if cfg.stripe_api_base:
        stripe.api_base = cfg.stripe_api_base
        log.warn(
            f"stripe: STRIPE_API_BASE is set ({cfg.stripe_api_base}) -- "
            "talking to a local double, not the real Stripe API. Expected "
            "in test/CI only; unset in production."
        )
    try:
        await asyncio.to_thread(stripe.Balance.retrieve)
        mode = "live" if cfg.payment_processor_secret.startswith("sk_live_") else "test"
        log.ok(f"stripe: credentials valid ({mode} mode)")
        return True
    except Exception as exc:
        log.fail(f"stripe: credentials rejected -- {exc}")
        return False


async def check_paypal(cfg: AppConfig) -> bool:
    if not paypal.is_configured(cfg):
        log.warn(
            "paypal: not configured -- customers fall back to Zelle/"
            "in-person/PayPal-sent-directly, recorded manually by an "
            "admin. This is a real, fully supported path, not a broken "
            "one -- expected if you haven't set up PayPal yet."
        )
        return True
    async with httpx.AsyncClient() as client:
        result = await paypal._get_access_token(client, cfg)  # noqa: SLF001
    if result.is_err:
        log.fail(
            f"paypal: configured but credentials rejected -- {result.danger_err.value}"
        )
        return False
    log.ok(f"paypal: credentials valid ({cfg.paypal_mode} mode)")
    return True


def check_smtp(cfg: AppConfig) -> bool:
    if not mailer.is_configured(cfg):
        log.warn(
            "smtp: not configured -- invoice-sent/payment-received email "
            "notifications are a silent no-op. Expected if you haven't set "
            "up email yet; nothing else depends on it."
        )
        return True
    ok = True
    if not cfg.mailing_address:
        log.fail(
            "smtp: configured but MAILING_ADDRESS is empty -- CAN-SPAM "
            "requires a real physical postal address in every commercial "
            "email's footer. Set MAILING_ADDRESS before sending real email."
        )
        ok = False
    import socket

    try:
        with socket.create_connection((cfg.smtp_host, cfg.smtp_port), timeout=5):
            pass
        log.ok(f"smtp: {cfg.smtp_host}:{cfg.smtp_port} reachable")
    except OSError as exc:
        log.fail(f"smtp: {cfg.smtp_host}:{cfg.smtp_port} unreachable -- {exc}")
        ok = False
    return ok


async def check_storage(cfg: AppConfig) -> bool:
    try:
        backend = get_storage_backend(cfg)
    except RuntimeError as exc:
        log.fail(f"storage: {exc}")
        return False

    key = f"health-check/{uuid.uuid4()}.txt"
    payload = b"logand.app health check"
    try:
        await backend.put(key, payload, "text/plain")
        read_back = await backend.get(key)
        if read_back != payload:
            log.fail(f"storage ({cfg.storage_backend}): round-trip data mismatch")
            return False
        await backend.delete(key)
        if await backend.exists(key):
            log.fail(
                f"storage ({cfg.storage_backend}): delete did not remove the object"
            )
            return False
        log.ok(f"storage: {cfg.storage_backend} read/write/delete round-trip succeeded")
        return True
    except StorageObjectNotFound as exc:
        log.fail(f"storage ({cfg.storage_backend}): wrote {key}, unreadable -- {exc}")
        return False
    except Exception as exc:
        log.fail(f"storage ({cfg.storage_backend}): round-trip failed -- {exc}")
        return False


def check_latex() -> bool:
    if shutil.which("latexmk") is None:
        log.warn(
            "latexmk: not found on PATH -- invoice PDF generation will "
            "fail. Expected on a local dev machine; the real Docker image "
            "(backend/Dockerfile) installs the full texlive toolchain, so "
            "this should always be OK inside a deployed container."
        )
        return True
    log.ok("latexmk: found on PATH")
    return True


def check_backup_config() -> bool:
    # BACKUP_R2_* are read directly by ops/backup.sh, not by AppConfig --
    # checked here via raw env vars for the same reason.
    required = [
        "BACKUP_R2_BUCKET",
        "BACKUP_R2_ENDPOINT_URL",
        "BACKUP_R2_ACCESS_KEY_ID",
        "BACKUP_R2_SECRET_ACCESS_KEY",
    ]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        log.warn(
            "backups: BACKUP_R2_* not fully configured "
            f"(missing: {', '.join(missing)}) -- ops/backup.sh stages "
            "backups locally only. A VPS-level failure would lose them "
            "along with everything else. See docs/secrets.md."
        )
        return True
    log.ok("backups: BACKUP_R2_* fully configured")
    return True


async def check_public_url(cfg: AppConfig) -> bool:
    if cfg.public_base_url in ("https://logand.app", ""):
        log.warn(
            f"public_base_url: still the default ({cfg.public_base_url!r}) "
            "-- invoice PDF links and PayPal redirects will point at the "
            "wrong host unless this really is your domain."
        )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{cfg.public_base_url}/api/me")
        if resp.status_code == 401:
            log.ok(f"public_base_url: {cfg.public_base_url} is reachable and answering")
            return True
        log.warn(
            f"public_base_url: {cfg.public_base_url}/api/me returned "
            f"{resp.status_code}, expected 401 (unauthenticated) -- "
            "something answered, but not obviously this backend."
        )
        return True
    except Exception as exc:
        log.warn(
            f"public_base_url: {cfg.public_base_url} not reachable from "
            f"here -- {exc}. Expected if running this from your own "
            "machine before DNS/deploy is live; a real problem if run "
            "from the VPS itself after deploying."
        )
        return True


async def run(cfg: AppConfig, *, skip_http: bool) -> int:
    log.section("Core infrastructure")
    results = [
        await check_database(cfg),
        await check_redis(cfg),
    ]

    log.section("Secrets sanity")
    results.append(check_dev_defaults(cfg))

    log.section("Payment providers")
    results.append(await check_stripe(cfg))
    results.append(await check_paypal(cfg))

    log.section("Notifications")
    results.append(check_smtp(cfg))

    log.section("File storage")
    results.append(await check_storage(cfg))

    log.section("Invoice PDF generation")
    results.append(check_latex())

    log.section("Backups")
    results.append(check_backup_config())

    if not skip_http:
        log.section("Public reachability")
        results.append(await check_public_url(cfg))

    log.summary(all(results))
    return 0 if all(results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check every logand.app backend subsystem/dependency and "
        "report which are OK, degraded-but-expected (WARN), or actually "
        "broken (FAIL)."
    )
    parser.add_argument(
        "--skip-http",
        action="store_true",
        help="skip the public_base_url reachability check (before DNS/deploy is live)",
    )
    args = parser.parse_args()

    cfg = AppConfig.from_external(argparse.Namespace())
    exit_code = asyncio.run(run(cfg, skip_http=args.skip_http))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
