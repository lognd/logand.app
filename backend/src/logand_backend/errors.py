from __future__ import annotations

from typani.error_set import ErrorSet


class AuthError(ErrorSet):
    InvalidCredentials = "email or password is incorrect"
    SessionExpired = "session has expired and must be re-authenticated"
    SessionNotFound = "session token does not match any known session"
    EmailAlreadyRegistered = "an account with this email already exists"


class InvoiceError(ErrorSet):
    NotFound = "invoice was not found"
    NotOwned = "invoice does not belong to the requesting customer"
    InvalidState = "invoice is not in a state that allows this operation"
    AmountMismatch = "client-supplied amount does not match server-computed total"


class BudgetError(ErrorSet):
    NotFound = "budget entry was not found"
    EvidenceRequired = (
        "direct edit is not allowed once evidence is attached; use a correction"
    )


class InventoryError(ErrorSet):
    NotFound = "inventory item or location was not found"
    LocationInUse = "location cannot be deleted while items still reference it"


class PaymentProviderError(ErrorSet):
    # A real, expected state (an admin hasn't hooked up real API credentials
    # yet), not a bug -- api/invoices_public.py surfaces this as a 503 with
    # guidance toward the manual payment methods that always work
    # regardless of whether any provider is configured.
    NotConfigured = "this payment provider is not configured"
    RequestFailed = "the payment provider rejected or failed to process the request"
