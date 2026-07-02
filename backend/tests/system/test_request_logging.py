from __future__ import annotations

import json
from pathlib import Path

from httpx import AsyncClient


async def test_every_request_gets_a_correlated_request_id_header(
    db_client: AsyncClient,
) -> None:
    resp = await db_client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["x-request-id"]


async def test_unhandled_exception_is_logged_with_traceback_and_request_id(
    db_client: AsyncClient, monkeypatch: object, tmp_path: Path
) -> None:
    import logand_backend.api.health as health_module

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("a genuinely unexpected bug")

    monkeypatch.setattr(health_module, "HealthResponse", _boom)  # type: ignore[attr-defined]

    resp = await db_client.get("/health")

    assert resp.status_code == 500
    assert resp.json() == {"detail": "internal server error"}
    request_id = resp.headers["x-request-id"]

    from logand_backend.logging.logger import log_dir

    log_file = log_dir() / "app.log"
    lines = log_file.read_text().strip().splitlines()
    matching = [json.loads(line) for line in lines if request_id in line]
    exception_entries = [e for e in matching if e["message"] == "unhandled exception"]
    assert exception_entries, "expected an 'unhandled exception' log entry"
    entry = exception_entries[-1]
    assert entry["level"] == "ERROR"
    assert "RuntimeError" in entry["exception"]
    assert "a genuinely unexpected bug" in entry["exception"]
