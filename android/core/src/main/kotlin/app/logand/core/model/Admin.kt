package app.logand.core.model

import kotlinx.serialization.Serializable

// Every model in this file is copy-derived from a real backend admin route
// response/request shape (never guessed) -- see backend's
// api/invoices.py, api/admin_users.py, api/inventory.py, api/bom.py,
// api/budget.py, api/admin_data.py, api/admin_logs.py, api/admin_version.py.
// Money fields travel as strings (Decimal -> JSON string), same
// convention as MileageEntry/Receipt, to avoid float precision loss.

// -- invoices ----------------------------------------------------------

// Wire shape for one line item, both when creating an invoice (request
// body) and when reading one back as part of InvoiceDetail (response).
@Serializable
data class InvoiceLineItem(
    val id: String? = null,
    val description: String,
    val quantity: String,
    val unit_price: String,
    val unit: String? = null,
)

@Serializable
data class InvoiceRefund(
    val id: String,
    val amount: String,
    val reason: String?,
    val status: String,
    val stripe_refund_id: String?,
    val paypal_refund_id: String?,
    val recorded_by: String,
    val created_at: String,
)

@Serializable
data class InvoicePayment(
    val id: String,
    val method: String,
    val amount: String,
    val status: String,
    val transaction_id: String?,
    val note: String?,
    val recorded_by: String?,
    val dispute_status: String?,
    val refunds: List<InvoiceRefund> = emptyList(),
)

// Matches api/invoices.py::_invoice_summary -- the shape shared by both
// the list and (embedded in) the detail response.
@Serializable
data class InvoiceSummary(
    val id: String,
    val customer_id: String,
    val status: String,
    val amount_total: String,
    val currency: String,
    val memo: String?,
    val due_date: String?,
    val is_recurring: Boolean,
    val paid_at: String?,
)

// GET /api/admin/invoices/{id} -- summary fields plus line_items/payments.
@Serializable
data class InvoiceDetail(
    val id: String,
    val customer_id: String,
    val status: String,
    val amount_total: String,
    val currency: String,
    val memo: String?,
    val due_date: String?,
    val is_recurring: Boolean,
    val paid_at: String?,
    val line_items: List<InvoiceLineItem>,
    val payments: List<InvoicePayment>,
)

@Serializable
data class PaymentProofSummary(
    val id: String,
    val content_type: String,
    val created_at: String,
)

// Matches domain/invoices/stats.py's InvoiceStats exactly.
@Serializable
data class InvoiceStatusBreakdown(
    val count: Int,
    val amount_total: String,
)

@Serializable
data class PaymentMethodBreakdown(
    val count: Int,
    val amount: String,
)

@Serializable
data class DisputeBreakdown(
    val needs_response: Int,
    val under_review: Int,
    val won: Int,
    val lost: Int,
)

@Serializable
data class InvoiceStats(
    val by_status: Map<String, InvoiceStatusBreakdown>,
    val total_collected: String,
    val total_refunded: String,
    val net_collected: String,
    val outstanding: String,
    val by_payment_method: Map<String, PaymentMethodBreakdown>,
    val open_disputes: Int,
    val disputes: DisputeBreakdown,
)

// Body for POST /api/admin/invoices/{id}/payments/manual -- matches
// domain/invoices/service.py::ManualPaymentInput. `method` is one of
// "paypal", "zelle", "in_person", "other" (backend's ManualPaymentMethod
// Literal), left as a plain String here rather than a Kotlin enum so an
// unrecognized-by-this-client-version value from a future backend never
// fails to serialize -- this client only ever WRITES one of the four
// known values, an enforcement left to callers/UI.
@Serializable
data class ManualPaymentRequest(
    val method: String,
    val amount: String,
    val note: String? = null,
)

// Body for POST /api/admin/invoices/{id}/payments/{payment_id}/refund --
// matches domain/invoices/refunds.py::RefundInput. `idempotency_key` is
// caller-generated, one per logical refund action (not regenerated on a
// retry of the same action) -- see RefundInput's own doc comment.
@Serializable
data class RefundRequest(
    val payment_id: String,
    val amount: String? = null,
    val reason: String? = null,
    val idempotency_key: String,
)

// -- customers -----------------------------------------------------------

// Matches api/admin_users.py::list_customers -- deliberately id+email
// only, plus account_state (docs/design/17-contact-users-and-email-
// verification.md) so an admin picking who to bill can see at a glance
// whether the person has ever claimed an invoice. One of "contact",
// "unverified", "active" -- left as a plain String rather than a Kotlin
// enum so an unrecognized-by-this-client-version value from a future
// backend never fails to deserialize.
@Serializable
data class CustomerListItem(
    val id: String,
    val email: String,
    val account_state: String,
)

// Matches api/admin_users.py::_customer_detail.
// Body for POST /api/admin/customers/{id}/reset-password.
@Serializable
data class ResetPasswordRequest(
    val new_password: String,
)

// address_* fields are the customer's destination address
// (docs/design/16-sales-tax.md Phase 6) -- feeds the tax engine's
// destination-jurisdiction lookup; any/all may be null if never set.
// account_state/email_verified_at are docs/design/17's derived,
// read-only account state -- never password_hash itself, which the
// backend never serializes at all.
@Serializable
data class CustomerDetail(
    val id: String,
    val email: String,
    val role: String,
    val emails_opted_out: Boolean,
    val disabled_at: String?,
    val created_at: String,
    val account_state: String,
    val email_verified_at: String? = null,
    val address_line1: String? = null,
    val address_city: String? = null,
    val address_state: String? = null,
    val address_postal_code: String? = null,
    val address_country: String? = null,
)

// Body for PUT /api/admin/customers/{id}/address -- matches
// api/admin_users.py::AddressInput. Replaces the whole address; a null
// field clears it rather than leaving it as-is.
@Serializable
data class CustomerAddressRequest(
    val address_line1: String? = null,
    val address_city: String? = null,
    val address_state: String? = null,
    val address_postal_code: String? = null,
    val address_country: String? = null,
)

// -- inventory -----------------------------------------------------------

// Matches api/inventory.py::_item_summary.
@Serializable
data class InventoryItem(
    val id: String,
    val name: String,
    val description: String?,
    val quantity: Int,
    val location_id: String,
    val tags: List<String>,
    val unit_cost: String?,
)

@Serializable
data class InventoryLocation(
    val id: String,
    val name: String,
    val description: String?,
)

// Matches api/inventory.py::_adjustment_summary.
@Serializable
data class InventoryAdjustment(
    val id: String,
    val delta: Int,
    val quantity_before: Int,
    val quantity_after: Int,
    val reason: String,
    val adjusted_by: String?,
    val created_at: String,
)

// Body for POST /api/admin/inventory/items/{id}/adjust.
@Serializable
data class AdjustQuantityRequest(
    val delta: Int,
    val reason: String,
)

// -- bill of materials -----------------------------------------------------

// Matches api/bom.py::_bom_summary.
@Serializable
data class BomSummary(
    val id: String,
    val name: String,
    val description: String?,
    val labor_hours: String,
    val labor_rate: String,
    val overhead_percent: String,
)

// Body for POST /api/admin/boms.
@Serializable
data class CreateBomRequest(
    val name: String,
    val labor_hours: String = "0",
    val labor_rate: String = "0",
    val overhead_percent: String = "0",
    val description: String? = null,
)

// Body for POST /api/admin/boms/{id}/lines.
@Serializable
data class AddMaterialLineRequest(
    val item_id: String,
    val quantity_per_unit: Int,
)

// Body for POST /api/admin/boms/{id}/consume.
@Serializable
data class ConsumeBomRequest(
    val build_quantity: Int,
    val reason: String? = null,
)

// Matches domain/bom/service.py::BomCostBreakdown via api/bom.py's
// _breakdown_summary.
@Serializable
data class BomMaterialLineCost(
    val item_id: String,
    val item_name: String,
    val quantity: Int,
    val unit_cost: String,
    val line_cost: String,
)

@Serializable
data class BomCostBreakdown(
    val material_lines: List<BomMaterialLineCost>,
    val material_cost: String,
    val labor_hours: String,
    val labor_cost: String,
    val overhead_percent: String,
    val overhead_cost: String,
    val total_cost: String,
)

// -- budget --------------------------------------------------------------

// Matches api/budget.py::list_entries's row shape.
@Serializable
data class BudgetEntry(
    val id: String,
    val amount: String,
    val category: String,
    val vendor: String?,
    val memo: String?,
    val occurred_on: String,
    val corrects_entry_id: String?,
)

// -- admin data (raw table browser) --------------------------------------

// Every /api/admin/data/tables/{table}/rows/{row} value is a raw,
// column-shaped JSON object whose keys depend on the table -- there is no
// fixed Kotlin shape to bind it to, so this client passes it through as a
// JsonObject rather than guessing (or duplicating) a schema per table.
// See kotlinx.serialization.json.JsonObject.
typealias AdminTableRow = kotlinx.serialization.json.JsonObject

@Serializable
data class TableColumn(
    val name: String,
    val type: String,
)

// Body for PATCH /api/admin/data/tables/{table}/rows/{row}.
@Serializable
data class UpdateRowRequest(
    val changes: AdminTableRow,
)

// Body for POST /api/admin/data/tables/{table}/rows.
@Serializable
data class InsertRowRequest(
    val values: AdminTableRow,
)

@Serializable
data class ChangeId(
    val change_id: String,
)

// Matches api/admin_data.py::_log_summary.
@Serializable
data class AdminAuditLogEntry(
    val id: String,
    val admin_id: String?,
    val action: String,
    val target_table: String,
    val target_id: String,
    val before_state: AdminTableRow?,
    val after_state: AdminTableRow?,
    val created_at: String,
)

// -- logs ------------------------------------------------------------------

// Matches api/admin_logs.py::list_log_files.
@Serializable
data class LogFileInfo(
    val name: String,
    val size_bytes: Long,
    val modified_at: Double,
)

// Response of POST /api/admin/boms/{id}/consume.
@Serializable
data class AdjustmentIds(
    val adjustment_ids: List<String>,
)

// -- version ---------------------------------------------------------------

// Matches api/admin_version.py::get_version_info.
@Serializable
data class VersionInfo(
    val app_version: String,
    val git_commit: String,
    val python_version: String,
    val platform: String,
    val dependencies: Map<String, String>,
)
