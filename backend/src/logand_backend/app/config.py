from __future__ import annotations

import argparse
import os
from typing import Self

from dotenv import load_dotenv
from pydantic import BaseModel


class AppConfig(BaseModel):
    model_config = {}

    database_url: str = "postgresql+asyncpg://logand:changeme@localhost:5432/logand"
    redis_url: str = "redis://localhost:6379/0"
    session_secret: str = "dev-only-insecure-secret"
    payment_processor_secret: str = "sk_test_fake"
    stripe_webhook_secret: str = "whsec_fake"
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
        return cls(**merged)

    @staticmethod
    def _env_overrides() -> dict[str, object]:
        env_map = {
            "DATABASE_URL": "database_url",
            "REDIS_URL": "redis_url",
            "SESSION_SECRET": "session_secret",
            "PAYMENT_PROCESSOR_SECRET": "payment_processor_secret",
            "STRIPE_WEBHOOK_SECRET": "stripe_webhook_secret",
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
