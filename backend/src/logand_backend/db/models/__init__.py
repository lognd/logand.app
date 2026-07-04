from __future__ import annotations

# NOTE: alembic env.py autogenerate only sees tables whose model module has
# been imported somewhere -- importing them all here is what makes that work.
# ALSO load-bearing for tests/conftest.py's db_engine fixture: under
# pytest-xdist, each worker is a separate Python process with its own
# Base.metadata -- a model class only imported transitively by SOME test
# files (not this central list) means Base.metadata.drop_all()/create_all()
# disagree about which tables/FKs exist depending on which tests a given
# worker happened to import first, which showed up as a real "cannot drop
# table X because Y depends on it" failure the first time BillOfMaterials/
# BomMaterialLine/InventoryAdjustment were added without being listed here.
from logand_backend.db.models.audit import AdminAuditLog
from logand_backend.db.models.bom import BillOfMaterials, BomMaterialLine
from logand_backend.db.models.budget import BudgetEntry, BudgetEntryEvidence
from logand_backend.db.models.documents import Document
from logand_backend.db.models.inventory import (
    InventoryAdjustment,
    InventoryItem,
    InventoryLocation,
)
from logand_backend.db.models.invoices import (
    Invoice,
    InvoiceLineItem,
    Payment,
    PaymentProof,
)
from logand_backend.db.models.mileage import MileageEntry
from logand_backend.db.models.password_reset_tokens import PasswordResetToken
from logand_backend.db.models.receipts import Receipt
from logand_backend.db.models.sessions import Session
from logand_backend.db.models.users import User

__all__ = [
    "AdminAuditLog",
    "BillOfMaterials",
    "BomMaterialLine",
    "BudgetEntry",
    "BudgetEntryEvidence",
    "Document",
    "InventoryAdjustment",
    "InventoryItem",
    "InventoryLocation",
    "Invoice",
    "InvoiceLineItem",
    "MileageEntry",
    "PasswordResetToken",
    "Payment",
    "PaymentProof",
    "Receipt",
    "Session",
    "User",
]
