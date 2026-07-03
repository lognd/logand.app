from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from logand_backend.app.config import AppConfig
from logand_backend.scripts.health_check import (
    check_database,
    check_smtp,
    check_storage,
)
from logand_backend.testing.fake_gmail import app as fake_gmail_app
from logand_backend.testing.fake_gmail_key import fake_service_account_json


async def test_check_database_succeeds_against_a_real_postgres(
    postgres_url: str,
) -> None:
    cfg = AppConfig(database_url=postgres_url)
    assert await check_database(cfg) is True


async def test_check_database_fails_against_an_unreachable_host() -> None:
    cfg = AppConfig(
        database_url="postgresql+asyncpg://nobody:nothing@127.0.0.1:1/nowhere"
    )
    assert await check_database(cfg) is False


async def test_check_storage_round_trips_against_the_local_backend(tmp_path) -> None:
    cfg = AppConfig(storage_backend="local", storage_local_dir=str(tmp_path))
    assert await check_storage(cfg) is True


# -- check_smtp: Gmail OAuth2 branch, against a real running fake-Gmail ----
# server -- same real-socket convention as fake_paypal_server/
# fake_smtp_server, since check_smtp's Gmail branch makes real httpx
# requests via mailer._get_gmail_access_token.


@pytest.fixture(scope="module")
def fake_gmail_server() -> Iterator[str]:
    config = uvicorn.Config(
        fake_gmail_app, host="127.0.0.1", port=0, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "fake_gmail server did not start in time"
    port = server.servers[0].sockets[0].getsockname()[1]

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


async def test_check_smtp_passes_with_valid_gmail_oauth2_credentials(
    fake_gmail_server: str,
) -> None:
    cfg = AppConfig(
        gmail_service_account_json=fake_service_account_json(),
        gmail_sender_email="billing@example.com",
        gmail_token_api_base=fake_gmail_server,
        gmail_api_base=fake_gmail_server,
        mailing_address="123 Main St, Springfield",
    )
    assert await check_smtp(cfg) is True


async def test_check_smtp_fails_when_gmail_oauth2_token_exchange_rejected(
    fake_gmail_server: str,
) -> None:
    """Points gmail_token_api_base at a host with nothing listening -- the
    token exchange fails outright, same shape as a real "domain-wide
    delegation not authorized" rejection from Google.
    """
    cfg = AppConfig(
        gmail_service_account_json=fake_service_account_json(),
        gmail_sender_email="billing@example.com",
        gmail_token_api_base="http://127.0.0.1:1",
        gmail_api_base=fake_gmail_server,
        mailing_address="123 Main St, Springfield",
    )
    assert await check_smtp(cfg) is False


async def test_check_smtp_fails_when_mailing_address_empty_in_gmail_mode(
    fake_gmail_server: str,
) -> None:
    cfg = AppConfig(
        gmail_service_account_json=fake_service_account_json(),
        gmail_sender_email="billing@example.com",
        gmail_token_api_base=fake_gmail_server,
        gmail_api_base=fake_gmail_server,
        mailing_address="",
    )
    assert await check_smtp(cfg) is False
