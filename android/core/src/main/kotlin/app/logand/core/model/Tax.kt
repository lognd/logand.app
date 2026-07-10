package app.logand.core.model

import kotlinx.serialization.Serializable

// Every model in this file is copy-derived from a real backend admin route
// response/request shape (never guessed) -- see backend's api/tax.py
// (prefix /api/admin/tax) and api/invoices.py's tax-report route (on the
// invoices router, not the tax one). Money/rate fields travel as strings
// (Decimal -> JSON string), same convention as the rest of Admin.kt.

// -- item tax classifications ---------------------------------------------

// One do-as-we-go item tax classification row, matching
// api/tax.py::_serialize. `status` starts "pending" whenever the
// classifier engine has never seen this normalized item key before; an
// admin either confirms the model's guess as-is or overrides it with a
// corrected category/taxable/hts_code, both of which move it out of the
// pending review queue. `status` is left a plain String (not a Kotlin
// enum) so an unrecognized-by-this-client-version value from a future
// backend never fails to decode.
@Serializable
data class TaxClassification(
    val id: String,
    val normalized_key: String,
    val description: String,
    val category: String,
    val taxable: Boolean,
    val hts_code: String?,
    val status: String,
    val source: String,
    val model: String?,
    val rationale: String?,
    val confirmed_at: String?,
    val updated_at: String?,
)

// Body for POST /api/admin/tax/classifications/{key}/override -- matches
// api/tax.py::OverrideInput. Confirming/overriding a tax classification
// changes financial records, so callers must only send this after an
// explicit confirm step in the UI, never a one-tap action.
@Serializable
data class TaxClassificationOverrideRequest(
    val category: String,
    val taxable: Boolean,
    val hts_code: String? = null,
)

// -- Stripe tax reconciliation ---------------------------------------------

// Response of GET /api/admin/tax/stripe-reconcile -- Stripe's own recorded
// tax figures for a date range, for cross-checking against the
// deterministic tax report's own figures for the same period. Best-effort
// on the backend: an unconfigured Stripe account or any failure in the
// round trip returns zeros, never a 5xx (see stripe_reconcile.py).
@Serializable
data class StripeTaxReconcile(
    val total_tax_collected: String,
    val by_jurisdiction: Map<String, String>,
    val transaction_count: Int,
)

// -- tax rules knowledge base -----------------------------------------------

// One rate row in the tax_rules knowledge base, matching
// api/tax.py::_serialize_rule -- admin-entered and government-cited.
// Claude only ever classifies items into a category; it never sets or
// approves the rate itself, so every row here traces back to a real
// citation_url an admin typed in.
@Serializable
data class TaxRule(
    val id: String,
    val jurisdiction: String,
    val tax_type: String,
    val category: String,
    val rate: String,
    val source: String,
    val citation_url: String?,
    val effective_from: String,
)

// Body for POST /api/admin/tax/rules -- matches
// api/tax.py::TaxRuleCreateInput. citation_url is required by the
// backend (rejects anything else with a 400 -- see migration
// 0027_tax_rule_citation); the UI must validate this is non-blank
// before ever making the call, not rely on the network round trip to
// surface it.
@Serializable
data class TaxRuleCreateRequest(
    val jurisdiction: String,
    val tax_type: String,
    val category: String = "*",
    val rate: String,
    val source: String,
    val citation_url: String,
)

// -- tax filing report -------------------------------------------------------

// Matches domain/invoices/tax/report.py::TaxReport's jurisdiction rows, as
// serialized by api/invoices.py::get_tax_report.
@Serializable
data class TaxReportJurisdictionRow(
    val jurisdiction: String,
    val tax_type: String,
    val taxable_base: String,
    val tax_collected: String,
)

@Serializable
data class TaxReportCategoryRow(
    val category: String,
    val gross: String,
    val taxable_gross: String,
)

// Response of GET /api/admin/invoices/tax-report -- tax-filing breakdown
// over [from_date, to_date): sales by category, tax collected by
// jurisdiction + type, and which jurisdictions must be filed for. See
// docs/design/16-sales-tax.md.
@Serializable
data class TaxReport(
    val from_date: String,
    val to_date: String,
    val currency: String,
    val invoice_count: Int,
    val total_sales: String,
    val total_tax_collected: String,
    val filing_jurisdictions: List<String>,
    val by_jurisdiction: List<TaxReportJurisdictionRow>,
    val by_category: List<TaxReportCategoryRow>,
)
