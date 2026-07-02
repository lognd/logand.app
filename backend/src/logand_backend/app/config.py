from __future__ import annotations

import argparse
import os
from typing import Self

from dotenv import load_dotenv
from pydantic import BaseModel


class AppConfig(BaseModel):
    model_config = {}

    database_url: str = "postgresql+asyncpg://logand:changeme@localhost:5432/logand"
    # None (not a hardcoded "redis://localhost:6379/0"-looking default) --
    # rate_limit.py's RateLimiter treats redis_url=None as "use the
    # in-process fallback," and a plausible-looking default URL here made
    # that decision silently wrong: every environment without a real Redis
    # reachable at that exact address (plain `uv run pytest`, local `uv run
    # uvicorn` without docker-compose) would have looked "configured" while
    # actually being unreachable. None only becomes a real URL when
    # REDIS_URL is actually set in the environment (docker-compose.yml/
    # docker-compose.test.yml both do, via backend/.env or inline env).
    redis_url: str | None = None
    session_secret: str = "dev-only-insecure-secret"
    payment_processor_secret: str = "sk_test_fake"
    stripe_webhook_secret: str = "whsec_fake"
    # None means "talk to the real api.stripe.com" (stripe-python's own
    # default) -- only ever set to something else in a test/CI environment
    # pointing at testing/fake_stripe.py's local HTTP double, so system
    # tests exercise the real HTTP call stripe-python makes (real
    # serialization, real response parsing) without needing a real Stripe
    # test-mode account/API key just to run the test suite.
    stripe_api_base: str | None = None
    # PayPal is optional -- None (not a fake-looking default, same
    # convention as redis_url above) means "not configured," which the
    # PayPal provider (domain/payments/providers/paypal.py) treats as a
    # real, expected state (gracefully unavailable), not a misconfiguration.
    paypal_client_id: str | None = None
    paypal_client_secret: str | None = None
    # "sandbox" (PayPal's own test environment name), not "test" -- matches
    # the literal API base URL host name switch in the PayPal provider.
    paypal_mode: str = "sandbox"
    # None means "use the real sandbox/live PayPal host derived from
    # paypal_mode" -- only ever overridden in test/CI, pointing at
    # testing/fake_paypal.py's local HTTP double, same convention as
    # stripe_api_base above.
    paypal_api_base: str | None = None
    # Both must be explicitly set for the admin seed to run at all (see
    # app/app.py's lifespan and domain/auth/service.py's
    # ensure_admin_seeded docstring for why this is opt-in, not automatic).
    seed_admin_email: str | None = None
    seed_admin_password: str | None = None
    # Used to build absolute links in generated invoice PDFs (see
    # domain/invoices/pdf/renderer.py) -- a downloaded PDF has no browser
    # origin of its own to resolve a relative "/invoices/x/pay" against,
    # unlike the frontend's own api/client.ts calls (see that module's doc
    # comment on why THOSE stay relative).
    public_base_url: str = "https://logand.app"
    invoice_business_name: str = "logand.app"
    # Free-form -- address/tax ID/phone, whatever the invoice's letterhead
    # should show under the business name. Empty by default (not every
    # deployment needs one), never templated with fake placeholder-looking
    # content that could be mistaken for real business info.
    invoice_business_details: str = ""
    invoice_contact_email: str = "billing@logand.app"
    # None (not "") -- same "not configured yet" convention as
    # paypal_client_id below: a customer's Pay page only shows Zelle as an
    # option once this is actually set, rather than always showing a
    # blank/placeholder handle. A phone number or email, whatever the
    # admin's real Zelle account is registered under -- free-form, not
    # validated as either shape.
    zelle_handle: str | None = None
    # SMTP is optional -- None (same "not configured" convention as
    # paypal_client_id above) means domain/notifications/mailer.py's
    # is_configured() is False, and every notification call becomes a
    # silent no-op rather than a crash. Nothing in the payment/invoice
    # flow depends on email actually being deliverable.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from_address: str = "noreply@logand.app"
    # CAN-SPAM requires a valid physical postal address in every commercial
    # email's footer -- deliberately empty by default (never a fake-looking
    # placeholder address that could ship to production by accident), set
    # via env var per deployment.
    mailing_address: str = ""
    # "local" (default, zero-config, zero-cost) or "r2" -- see
    # domain/storage/factory.py. Deliberately not "s3"/"gcs" as separate
    # options yet: R2's S3-compatible API covers the one cloud target this
    # app actually needs today (see docs/design/13-storage-abstraction.md
    # for why R2 was picked over GCS/S3/B2), and adding a real NAS backend
    # later is a new StorageBackend implementation, not a new enum value
    # cascading through every caller.
    storage_backend: str = "local"
    storage_local_dir: str = "./data/storage"
    r2_bucket: str | None = None
    r2_endpoint_url: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    # None means "no public URL" -- files are only ever fetched by
    # proxying through this backend's own authenticated API routes, never
    # a bare public bucket URL, unless a deployment explicitly opts a
    # custom domain into public read access and sets this.
    r2_public_base_url: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_external(cls, args: argparse.Namespace) -> Self:
        # NOTE: load_dotenv() reads .env into os.environ for us -- we never
        # open or print .env ourselves, only read already-loaded env vars.
        load_dotenv()
        merged: dict[str, object] = {}
        merged.update(cls._env_overrides())
        merged.update(cls._args_to_dict(args))
        # model_validate (not cls(**merged)) because merged is a dynamically
        # built dict[str, object] -- the field-by-field kwarg unpacking a
        # type checker wants for cls(**merged) doesn't apply here.
        return cls.model_validate(merged)

    @staticmethod
    def _env_overrides() -> dict[str, object]:
        env_map = {
            "DATABASE_URL": "database_url",
            "REDIS_URL": "redis_url",
            "SESSION_SECRET": "session_secret",
            "PAYMENT_PROCESSOR_SECRET": "payment_processor_secret",
            "STRIPE_WEBHOOK_SECRET": "stripe_webhook_secret",
            "STRIPE_API_BASE": "stripe_api_base",
            "PAYPAL_CLIENT_ID": "paypal_client_id",
            "PAYPAL_CLIENT_SECRET": "paypal_client_secret",
            "PAYPAL_MODE": "paypal_mode",
            "PAYPAL_API_BASE": "paypal_api_base",
            "SEED_ADMIN_EMAIL": "seed_admin_email",
            "SEED_ADMIN_PASSWORD": "seed_admin_password",
            "PUBLIC_BASE_URL": "public_base_url",
            "INVOICE_BUSINESS_NAME": "invoice_business_name",
            "INVOICE_BUSINESS_DETAILS": "invoice_business_details",
            "INVOICE_CONTACT_EMAIL": "invoice_contact_email",
            "ZELLE_HANDLE": "zelle_handle",
            "SMTP_HOST": "smtp_host",
            "SMTP_PORT": "smtp_port",
            "SMTP_USERNAME": "smtp_username",
            "SMTP_PASSWORD": "smtp_password",
            "SMTP_USE_TLS": "smtp_use_tls",
            "SMTP_FROM_ADDRESS": "smtp_from_address",
            "MAILING_ADDRESS": "mailing_address",
            "STORAGE_BACKEND": "storage_backend",
            "STORAGE_LOCAL_DIR": "storage_local_dir",
            "R2_BUCKET": "r2_bucket",
            "R2_ENDPOINT_URL": "r2_endpoint_url",
            "R2_ACCESS_KEY_ID": "r2_access_key_id",
            "R2_SECRET_ACCESS_KEY": "r2_secret_access_key",
            "R2_PUBLIC_BASE_URL": "r2_public_base_url",
            "HOST": "host",
            "PORT": "port",
        }
        out: dict[str, object] = {}
        for env_key, field in env_map.items():
            value = os.environ.get(env_key)
            if value is not None:
                out[field] = value
        return out

    @staticmethod
    def _args_to_dict(args: argparse.Namespace) -> dict[str, object]:
        return {k: v for k, v in vars(args).items() if v is not None}
