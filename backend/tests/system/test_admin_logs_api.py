from __future__ import annotations

from httpx import AsyncClient


async def test_logs_require_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/logs/files")
    assert resp.status_code == 401


async def test_list_files_includes_the_live_log(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/logs/files")

    assert resp.status_code == 200
    names = [f["name"] for f in resp.json()]
    assert "app.log" in names


async def test_tail_returns_recent_lines_as_valid_json_each(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")
    # Generate at least one more log line beyond login itself.
    await db_client.get("/api/health")

    resp = await db_client.get("/api/admin/logs/tail?lines=5")

    assert resp.status_code == 200
    lines = resp.json()
    assert len(lines) > 0
    import json

    for line in lines:
        parsed = json.loads(line)
        assert "timestamp" in parsed
        assert "level" in parsed


async def test_download_rejects_path_traversal(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/logs/files/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (400, 404)


async def test_download_rejects_unrelated_filename(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/logs/files/not-a-log-file.txt")
    assert resp.status_code == 404


async def test_download_the_live_log_file_succeeds(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/logs/files/app.log")
    assert resp.status_code == 200
