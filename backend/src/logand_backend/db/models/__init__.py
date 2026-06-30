from __future__ import annotations

# NOTE: alembic env.py autogenerate only sees tables whose model module has
# been imported somewhere -- importing them all here is what makes that work.
from logand_backend.db.models.budget import BudgetEntry, BudgetEntryEvidence
from logand_backend.db.models.inventory import InventoryItem, InventoryLocation
from logand_backend.db.models.invoices import Invoice, InvoiceLineItem, Payment
from logand_backend.db.models.sessions import Session
from logand_backend.db.models.users import User

__all__ = [
    "BudgetEntry",
    "BudgetEntryEvidence",
    "InventoryItem",
    "InventoryLocation",
    "Invoice",
    "InvoiceLineItem",
    "Payment",
    "Session",
    "User",
]
