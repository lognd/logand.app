from __future__ import annotations

from httpx import AsyncClient


async def test_version_requires_admin_role(
    db_client: AsyncClient, make_user, login_as
) -> None:
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, customer.email, "pw")

    resp = await db_client.get("/api/admin/version")
    assert resp.status_code == 401


async def test_version_reports_python_and_dependency_versions(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    await login_as(db_client, admin.email, "pw")

    resp = await db_client.get("/api/admin/version")

    assert resp.status_code == 200
    body = resp.json()
    assert "app_version" in body
    assert "git_commit" in body
    assert body["python_version"]
    assert isinstance(body["dependencies"], dict)
    # A real, always-installed dependency of this project -- confirms the
    # dependency list is genuinely populated, not an empty stub.
    assert "fastapi" in {name.lower() for name in body["dependencies"]}
