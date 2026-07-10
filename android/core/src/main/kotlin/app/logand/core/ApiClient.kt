package app.logand.core

import app.logand.core.model.CreatedId
import app.logand.core.model.LoginRequest
import app.logand.core.model.Me
import app.logand.core.model.MileageEntry
import app.logand.core.model.Receipt
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.RequestBody.Companion.toRequestBody

private val JSON_MEDIA_TYPE = "application/json".toMediaType()

// One client, talking to one stable REST API contract (see
// docs/design/14-mileage-receipts-documents.md's "API stability" section
// -- this class IS the abstraction layer a future automated tool would
// also hook into). Every request/response shape here is deliberately
// copy-derived from the real backend route signatures, not guessed --
// see api/mileage.py and api/receipts.py. The admin surface (invoices,
// customers, inventory, BOM, budget, raw-data browser, logs, version --
// see api/invoices.py, api/admin_users.py, api/inventory.py, api/bom.py,
// api/budget.py, api/admin_data.py, api/admin_logs.py,
// api/admin_version.py) lives on AdminApi instead of growing this class
// unboundedly; both share the SAME HttpPlumbing instance (one cookie jar,
// one OkHttp client, one onUnauthorized hook) via the `admin` property.
class ApiClient(
    baseUrl: String,
    private val cookieJar: SessionCookieJar = SessionCookieJar(),
    private val httpClient: OkHttpClient = OkHttpClient.Builder()
        .cookieJar(cookieJar)
        .build(),
    // Fired on EVERY 401 response from EVERY call this client makes, not
    // just login()/me() -- an idle-timeout session expiry mid-session
    // (see backend auth/sessions.py's _CUSTOMER_IDLE_TIMEOUT/
    // _ADMIN_IDLE_TIMEOUT) previously surfaced as a generic
    // ApiResult.HttpError on whatever call happened to hit it, with
    // nothing anywhere transitioning the app's own session state back to
    // logged-out -- every subsequent action kept failing with the same
    // confusing error while the UI still believed it was authenticated.
    // A single callback here, invoked before the 401 is also returned
    // as a normal ApiResult.HttpError (so existing per-call error
    // handling/messaging is unaffected), is the one place a caller (the
    // app's session-owning layer) can hook "clear local session state and
    // route back to login" without every single ApiClient method having
    // to know about that policy individually.
    private val onUnauthorized: (() -> Unit)? = null,
) {
    private val plumbing = HttpPlumbing(baseUrl, cookieJar, httpClient, onUnauthorized)
    private val json: Json get() = plumbing.json

    // The full admin API surface -- see AdminApi's own doc comment.
    val admin: AdminApi = AdminApi(plumbing)

    // -- auth ----------------------------------------------------------

    suspend fun login(email: String, password: String): ApiResult<Unit> =
        with(plumbing) {
            request(
                method = "POST",
                path = "/api/auth/login",
                body = json.encodeToString(LoginRequest.serializer(), LoginRequest(email, password))
                    .toRequestBody(JSON_MEDIA_TYPE),
                // login()'s own 401 means "wrong credentials," not "an
                // existing session expired" -- firing onUnauthorized here
                // would couple a bad-password attempt to global session
                // teardown (see L2). Every other call's 401 still fires it.
            ).decodeUnit(notifyOn401 = false)
        }

    suspend fun logout(): ApiResult<Unit> {
        // Same rationale as login(): logout()'s own 401 means the
        // session was already expired/invalid by the time this call
        // reached the server, not a NEW unauthorized event to react to
        // -- logout() below unconditionally clears the cookie jar
        // itself. Without this, an already-expired session's logout
        // would double-fire onUnauthorized teardown (L3).
        val result = with(plumbing) {
            request(method = "POST", path = "/api/auth/logout").decodeUnit(notifyOn401 = false)
        }
        // Clear local cookies regardless of the server call's outcome --
        // even if the network drops mid-logout, the app should not go on
        // acting as if it's still authenticated.
        cookieJar.clear()
        return result
    }

    suspend fun me(): ApiResult<Me> =
        with(plumbing) { request(method = "GET", path = "/api/me").decode(Me.serializer()) }

    // -- mileage ---------------------------------------------------------

    suspend fun listMileage(
        vehicle: String? = null,
        business: Boolean? = null,
        dateFrom: String? = null,
        dateTo: String? = null,
    ): ApiResult<List<MileageEntry>> = with(plumbing) {
        val url = urlBuilder("/api/admin/mileage").apply {
            vehicle?.let { addQueryParameter("vehicle", it) }
            business?.let { addQueryParameter("business", it.toString()) }
            dateFrom?.let { addQueryParameter("date_from", it) }
            dateTo?.let { addQueryParameter("date_to", it) }
        }.build()
        request(method = "GET", url = url).decode(ListSerializer(MileageEntry.serializer()))
    }

    // start/end odometer are the pair; `distance` is the raw-value form.
    // See domain/mileage/service.py::_resolve_distance -- exactly one of
    // "distance" or "start_odometer+end_odometer" must be usable, never
    // both required, matching this minimal-input-from-a-phone feature's
    // whole point.
    suspend fun createMileageEntry(
        vehicle: String,
        occurredOn: String,
        distance: String? = null,
        startOdometer: String? = null,
        endOdometer: String? = null,
        purpose: String? = null,
        business: Boolean = true,
        memo: String? = null,
    ): ApiResult<CreatedId> = with(plumbing) {
        val url = urlBuilder("/api/admin/mileage").apply {
            addQueryParameter("vehicle", vehicle)
            addQueryParameter("occurred_on", occurredOn)
            distance?.let { addQueryParameter("distance", it) }
            startOdometer?.let { addQueryParameter("start_odometer", it) }
            endOdometer?.let { addQueryParameter("end_odometer", it) }
            purpose?.let { addQueryParameter("purpose", it) }
            addQueryParameter("business", business.toString())
            memo?.let { addQueryParameter("memo", it) }
        }.build()
        request(method = "POST", url = url).decode(CreatedId.serializer())
    }

    suspend fun deleteMileageEntry(id: String): ApiResult<Unit> =
        with(plumbing) { request(method = "DELETE", path = "/api/admin/mileage/$id").decodeUnit() }

    // -- receipts --------------------------------------------------------

    suspend fun listReceipts(
        reconciled: Boolean? = null,
        category: String? = null,
        dateFrom: String? = null,
        dateTo: String? = null,
    ): ApiResult<List<Receipt>> = with(plumbing) {
        val url = urlBuilder("/api/admin/receipts").apply {
            reconciled?.let { addQueryParameter("reconciled", it.toString()) }
            category?.let { addQueryParameter("category", it) }
            dateFrom?.let { addQueryParameter("date_from", it) }
            dateTo?.let { addQueryParameter("date_to", it) }
        }.build()
        request(method = "GET", url = url).decode(ListSerializer(Receipt.serializer()))
    }

    // The ONLY required argument here is the photo itself -- matches
    // api/receipts.py's create route exactly ("snap a photo, done").
    suspend fun captureReceipt(
        fileBytes: ByteArray,
        filename: String,
        mimeType: String,
        vendor: String? = null,
        amount: String? = null,
        category: String? = null,
        occurredOn: String? = null,
        note: String? = null,
    ): ApiResult<CreatedId> = with(plumbing) {
        val url = urlBuilder("/api/admin/receipts").apply {
            vendor?.let { addQueryParameter("vendor", it) }
            amount?.let { addQueryParameter("amount", it) }
            category?.let { addQueryParameter("category", it) }
            occurredOn?.let { addQueryParameter("occurred_on", it) }
            note?.let { addQueryParameter("note", it) }
        }.build()
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file",
                filename,
                fileBytes.toRequestBody(mimeType.toMediaType()),
            )
            .build()
        request(method = "POST", url = url, body = body).decode(CreatedId.serializer())
    }

    suspend fun reconcileReceipt(receiptId: String, budgetEntryId: String): ApiResult<Unit> =
        with(plumbing) {
            val url = urlBuilder("/api/admin/receipts/$receiptId/reconcile")
                .addQueryParameter("budget_entry_id", budgetEntryId)
                .build()
            request(method = "POST", url = url).decodeUnit()
        }

    suspend fun deleteReceipt(id: String): ApiResult<Unit> =
        with(plumbing) { request(method = "DELETE", path = "/api/admin/receipts/$id").decodeUnit() }
}
