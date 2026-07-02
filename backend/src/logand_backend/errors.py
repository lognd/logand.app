from __future__ import annotations

from typani.error_set import ErrorSet


class AuthError(ErrorSet):
    InvalidCredentials = "email or password is incorrect"
    SessionExpired = "session has expired and must be re-authenticated"
    SessionNotFound = "session token does not match any known session"
    EmailAlreadyRegistered = "an account with this email already exists"


class DataError(ErrorSet):
    """Errors from the generic admin data browser/editor
    (domain/admin_data/service.py) -- deliberately its own error set,
    not reusing e.g. InventoryError.NotFound, since these are about the
    generic reflection-based CRUD layer itself, not any one domain."""

    TableNotFound = "no such table"
    RowNotFound = "row was not found"
    ColumnNotFound = "no such column on this table"
    ColumnNotEditable = "this column cannot be edited through this tool"
    ConstraintViolation = "this change would violate a database constraint"
    ChangeNotFound = "audit log entry was not found"
    ChangeNotRevertible = "this audit log entry has no before_state to revert to"


class UserError(ErrorSet):
    NotFound = "user was not found"
    CannotModifyAdmin = "admin accounts cannot be managed through this route"
    PasswordTooShort = "password must be at least 8 characters"


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
    WouldGoNegative = "adjustment would take quantity below zero"


class MileageError(ErrorSet):
    NotFound = "mileage entry was not found"
    # Covers both "neither distance nor start/end odometer given" and "the
    # supplied/derived distance is negative" -- one variant, since both are
    # the same class of caller mistake (bad input), not distinguishable in
    # a way a client needs to branch on separately.
    InvalidDistance = (
        "distance must be a positive value, directly or via odometer readings"
    )


class ReceiptError(ErrorSet):
    NotFound = "receipt was not found"
    BudgetEntryNotFound = "the budget entry to reconcile against was not found"


class DocumentError(ErrorSet):
    NotFound = "document was not found"
    InventoryItemNotFound = "the linked inventory item was not found"


class BomError(ErrorSet):
    NotFound = "bill of materials was not found"
    MaterialLineNotFound = "material line was not found on this bill of materials"
    ItemNotFound = "referenced inventory item was not found"
    DuplicateItem = "this item already has a material line on this bill of materials"
    # Surfaced, not silently treated as zero -- a cost breakdown that
    # quietly drops an item's real cost is worse than one that refuses to
    # compute at all until the admin fills in unit_cost.
    MissingUnitCost = "an item on this bill of materials has no unit_cost set"
    InsufficientStock = "not enough stock to consume this bill of materials"


class PaymentProviderError(ErrorSet):
    # A real, expected state (an admin hasn't hooked up real API credentials
    # yet), not a bug -- api/invoices_public.py surfaces this as a 503 with
    # guidance toward the manual payment methods that always work
    # regardless of whether any provider is configured.
    NotConfigured = "this payment provider is not configured"
    RequestFailed = "the payment provider rejected or failed to process the request"
