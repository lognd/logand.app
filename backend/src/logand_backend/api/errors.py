from __future__ import annotations

from fastapi import HTTPException
from typani.error_set import ErrorSet

from logand_backend.errors import (
    AuthError,
    BudgetError,
    DocumentError,
    InventoryError,
    InvoiceError,
    MileageError,
    PaymentProviderError,
    ReceiptError,
)

# Every ErrorSet variant that can ever reach an API boundary must be mapped
# here. Per docs/design/01: an unmapped variant raises NotImplementedError
# at import time (fail fast at startup), not a 500 at request time.
_STATUS_MAP: dict[ErrorSet, int] = {
    AuthError.InvalidCredentials: 401,
    AuthError.SessionExpired: 401,
    AuthError.SessionNotFound: 401,
    AuthError.EmailAlreadyRegistered: 409,
    InvoiceError.NotFound: 404,
    InvoiceError.NotOwned: 404,  # NOTE: 404 not 403, never confirm another
    # customer's invoice exists, see docs/design/04
    InvoiceError.InvalidState: 409,
    InvoiceError.AmountMismatch: 422,
    BudgetError.NotFound: 404,
    BudgetError.EvidenceRequired: 409,
    InventoryError.NotFound: 404,
    InventoryError.LocationInUse: 409,
    MileageError.NotFound: 404,
    MileageError.InvalidDistance: 422,
    ReceiptError.NotFound: 404,
    ReceiptError.BudgetEntryNotFound: 404,
    DocumentError.NotFound: 404,
    DocumentError.InventoryItemNotFound: 404,
    # 503 (not 500) -- "not configured yet" is an expected, temporary
    # deployment state, not a server error; the frontend uses this to show
    # "try Zelle/in-person instead" rather than a generic error banner.
    PaymentProviderError.NotConfigured: 503,
    # 502 -- the provider itself is the thing that failed, not this server.
    PaymentProviderError.RequestFailed: 502,
}


# NOTE: assumes ErrorSet subclasses are iterable (`for variant in Cls`) and
# instances are hashable for dict-key use -- this matches enum.Enum-like
# usage shown in ~/.claude/refs/typani.md but isn't spelled out there
# explicitly. Verify against the installed typani version once `uv sync`
# actually pulls it in; if iteration isn't supported, replace with an
# explicit tuple-of-variants per ErrorSet class.
def _verify_complete_mapping() -> None:
    for error_set_cls in (
        AuthError,
        BudgetError,
        DocumentError,
        InventoryError,
        InvoiceError,
        MileageError,
        PaymentProviderError,
        ReceiptError,
    ):
        for variant in error_set_cls:
            if variant not in _STATUS_MAP:
                raise NotImplementedError(
                    f"{error_set_cls.__name__}.{variant.name} has no HTTP "
                    "status mapping in api/errors.py"
                )


_verify_complete_mapping()


def to_http_exception(err: ErrorSet) -> HTTPException:
    return HTTPException(status_code=_STATUS_MAP[err], detail=err.value)
