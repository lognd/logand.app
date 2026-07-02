package app.logand.core.model

import kotlinx.serialization.Serializable

// Field names/shape match api/receipts.py's _receipt_summary exactly.
@Serializable
data class Receipt(
    val id: String,
    val vendor: String?,
    val amount: String?,
    val category: String?,
    val occurred_on: String?,
    val note: String?,
    val reconciled_budget_entry_id: String?,
    val captured_at: String,
)
