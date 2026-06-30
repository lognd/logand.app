from __future__ import annotations

from typani.error_set import ErrorSet


class AuthError(ErrorSet):
    InvalidCredentials = "email or password is incorrect"
    SessionExpired = "session has expired and must be re-authenticated"
    SessionNotFound = "session token does not match any known session"


class InvoiceError(ErrorSet):
    NotFound = "invoice was not found"
    NotOwned = "invoice does not belong to the requesting customer"
    InvalidState = "invoice is not in a state that allows this operation"
    AmountMismatch = "client-supplied amount does not match server-computed total"


class BudgetError(ErrorSet):
    NotFound = "budget entry was not found"
    EvidenceRequired = "direct edit is not allowed once evidence is attached; use a correction"


class InventoryError(ErrorSet):
    NotFound = "inventory item or location was not found"
    LocationInUse = "location cannot be deleted while items still reference it"
