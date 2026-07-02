package app.logand.core.model

import kotlinx.serialization.Serializable

// Field names/shape match api/mileage.py's _entry_summary exactly --
// numeric fields (distance/odometer readings) travel as strings, same
// convention as the web frontend's Invoice.amount_total (Decimal ->
// JSON string, never a float, to avoid floating-point precision loss).
@Serializable
data class MileageEntry(
    val id: String,
    val vehicle: String,
    val occurred_on: String,
    val start_odometer: String?,
    val end_odometer: String?,
    val distance: String,
    val purpose: String?,
    val business: Boolean,
    val memo: String?,
)

@Serializable
data class CreatedId(
    val id: String,
)
