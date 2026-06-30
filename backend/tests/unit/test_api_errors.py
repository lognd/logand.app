from __future__ import annotations

from logand_backend.api.errors import to_http_exception
from logand_backend.errors import AuthError, BudgetError, InventoryError, InvoiceError


def test_auth_invalid_credentials_maps_to_401() -> None:
    exc = to_http_exception(AuthError.InvalidCredentials)
    assert exc.status_code == 401


def test_invoice_not_owned_maps_to_404_not_403() -> None:
    # Explicit invariant from docs/design/04: never let the response
    # distinguish "doesn't exist" from "exists but isn't yours".
    exc = to_http_exception(InvoiceError.NotOwned)
    assert exc.status_code == 404


def test_invoice_amount_mismatch_maps_to_422() -> None:
    exc = to_http_exception(InvoiceError.AmountMismatch)
    assert exc.status_code == 422


def test_budget_evidence_required_maps_to_409() -> None:
    exc = to_http_exception(BudgetError.EvidenceRequired)
    assert exc.status_code == 409


def test_inventory_location_in_use_maps_to_409() -> None:
    exc = to_http_exception(InventoryError.LocationInUse)
    assert exc.status_code == 409


def test_inventory_not_found_maps_to_404() -> None:
    exc = to_http_exception(InventoryError.NotFound)
    assert exc.status_code == 404
