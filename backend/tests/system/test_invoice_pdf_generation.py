from __future__ import annotations

import shutil
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from logand_backend.domain.invoices.pdf.renderer import (
    PdfRenderError,
    build_invoice_pdf_data,
    render_invoice_pdf,
)

# Actually compiling requires a real LaTeX toolchain (latexmk + the
# texlive-* packages logandinvoice.cls's \RequirePackage list needs, see
# backend/Dockerfile) -- present in the real deployed image and in CI once
# that image is built, but not necessarily on every machine running
# `uv run pytest` directly (this is a genuinely large, ~1GB install, not
# something to require just to run the unit/integration suite). Skips
# cleanly here rather than failing, same convention as the postgres
# testcontainers fixture skipping when Docker isn't available.
pytestmark = pytest.mark.skipif(
    shutil.which("latexmk") is None,
    reason="latexmk not installed -- see backend/Dockerfile texlive packages",
)


def _csrf_headers(db_client: AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": db_client.cookies["csrf_token"]}


def test_render_invoice_pdf_produces_a_real_pdf() -> None:
    data = build_invoice_pdf_data(
        invoice_id="11111111-1111-1111-1111-111111111111",
        status="sent",
        currency="usd",
        amount_total=Decimal("299.00"),
        due_date="2026-08-01",
        created_at="2026-07-01",
        memo="Thanks! 50% off applied & a $5 fee_note.",
        customer_email="customer@example.com",
        line_items=[
            (
                "Consulting (10 hrs)",
                Decimal("10"),
                Decimal("25.00"),
                Decimal("250.00"),
                "hr",
            ),
            (
                "Rush fee & handling",
                Decimal("1"),
                Decimal("49.00"),
                Decimal("49.00"),
                None,
            ),
        ],
        business_name="logand.app",
        business_details="123 Example St, Some City, ST 00000",
        contact_email="billing@logand.app",
        pay_url="https://logand.app/invoices/11111111-1111-1111-1111-111111111111/pay",
    )

    pdf_bytes = render_invoice_pdf(data)

    # The real, minimal signal that this is an actual PDF (not an error
    # page, not empty output) -- every PDF file starts with this magic
    # byte sequence.
    assert pdf_bytes.startswith(b"%PDF-")
    # A real compiled invoice is comfortably more than a few KB; a
    # near-empty file would indicate the compile silently produced a
    # near-blank page rather than genuinely failing (which would have
    # raised PdfRenderError instead).
    assert len(pdf_bytes) > 5_000


def test_render_invoice_pdf_raises_on_genuinely_broken_input() -> None:
    # A raw (unescaped) `$` reaching the template is exactly the bug this
    # module's own latex_escape exists to prevent -- constructing
    # InvoicePdfData by hand (bypassing build_invoice_pdf_data's escaping)
    # to confirm render_invoice_pdf surfaces a real compile failure as
    # PdfRenderError rather than silently producing a broken/truncated PDF.
    from logand_backend.domain.invoices.pdf.renderer import InvoicePdfData

    data = InvoicePdfData(
        invoice_number="x",
        invoice_date="2026-07-01",
        due_date="Upon receipt",
        status="Sent",
        bill_to="customer@example.com",
        business_name="logand.app",
        business_details="",
        currency_upper="USD",
        currency_symbol="$",  # deliberately unescaped
        amount_total="10.00",
        line_items=[],
        contact_email="billing@logand.app",
    )

    with pytest.raises(PdfRenderError):
        render_invoice_pdf(data)


async def test_customer_can_download_own_invoice_pdf(
    db_client: AsyncClient, make_user, login_as, db_session: AsyncSession
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "25.00"}],
        headers=admin_headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=admin_headers
    )
    await db_client.post("/api/auth/logout", headers=admin_headers)

    await login_as(db_client, customer.email, "pw")
    resp = await db_client.get(f"/api/invoices/{invoice_id}/pdf")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")


async def test_customer_cannot_download_another_customers_invoice_pdf(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    owner = await make_user(role="customer", password="pw")
    other = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(owner.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "25.00"}],
        headers=admin_headers,
    )
    invoice_id = create_resp.json()["id"]
    await db_client.post(
        f"/api/admin/invoices/{invoice_id}/send", headers=admin_headers
    )
    await db_client.post("/api/auth/logout", headers=admin_headers)

    await login_as(db_client, other.email, "pw")
    resp = await db_client.get(f"/api/invoices/{invoice_id}/pdf")
    assert resp.status_code == 404


async def test_admin_can_download_any_invoice_pdf(
    db_client: AsyncClient, make_user, login_as
) -> None:
    admin = await make_user(role="admin", password="pw")
    customer = await make_user(role="customer", password="pw")
    await login_as(db_client, admin.email, "pw")
    admin_headers = _csrf_headers(db_client)

    create_resp = await db_client.post(
        "/api/admin/invoices",
        params={"customer_id": str(customer.id)},
        json=[{"description": "widget", "quantity": "1", "unit_price": "25.00"}],
        headers=admin_headers,
    )
    invoice_id = create_resp.json()["id"]

    # Deliberately still a draft (no /send call) -- admins can generate a
    # PDF preview of a draft invoice too, unlike the customer route which
    # can only ever reach a sent/overdue invoice through ownership checks
    # that gate on it existing at all in their own invoice list.
    resp = await db_client.get(
        f"/api/admin/invoices/{invoice_id}/pdf", headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF-")
