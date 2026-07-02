package app.logand.core

import app.logand.core.model.CreatedId
import app.logand.core.model.LoginRequest
import app.logand.core.model.Me
import app.logand.core.model.MileageEntry
import app.logand.core.model.Receipt
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody

private const val CSRF_COOKIE_NAME = "csrf_token"
private const val CSRF_HEADER_NAME = "X-CSRF-Token"
private val JSON_MEDIA_TYPE = "application/json".toMediaType()
private val BODY_REQUIRED_METHODS = setOf("POST", "PUT", "PATCH")
private val EMPTY_BODY = "".toRequestBody(null)

// One client, talking to one stable REST API contract (see
// docs/design/14-mileage-receipts-documents.md's "API stability" section
// -- this class IS the abstraction layer a future automated tool would
// also hook into). Every request/response shape here is deliberately
// copy-derived from the real backend route signatures, not guessed --
// see api/mileage.py and api/receipts.py.
class ApiClient(
    baseUrl: String,
    private val cookieJar: SessionCookieJar = SessionCookieJar(),
    private val httpClient: OkHttpClient = OkHttpClient.Builder()
        .cookieJar(cookieJar)
        .build(),
) {
    private val baseUrl = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true }

    // -- auth ----------------------------------------------------------

    suspend fun login(email: String, password: String): ApiResult<Unit> =
        request(
            method = "POST",
            path = "/api/auth/login",
            body = json.encodeToString(LoginRequest.serializer(), LoginRequest(email, password))
                .toRequestBody(JSON_MEDIA_TYPE),
        ).decodeUnit()

    suspend fun logout(): ApiResult<Unit> {
        val result = request(method = "POST", path = "/api/auth/logout").decodeUnit()
        // Clear local cookies regardless of the server call's outcome --
        // even if the network drops mid-logout, the app should not go on
        // acting as if it's still authenticated.
        cookieJar.clear()
        return result
    }

    suspend fun me(): ApiResult<Me> =
        request(method = "GET", path = "/api/me").decode(Me.serializer())

    // -- mileage ---------------------------------------------------------

    suspend fun listMileage(
        vehicle: String? = null,
        business: Boolean? = null,
        dateFrom: String? = null,
        dateTo: String? = null,
    ): ApiResult<List<MileageEntry>> {
        val url = urlBuilder("/api/admin/mileage").apply {
            vehicle?.let { addQueryParameter("vehicle", it) }
            business?.let { addQueryParameter("business", it.toString()) }
            dateFrom?.let { addQueryParameter("date_from", it) }
            dateTo?.let { addQueryParameter("date_to", it) }
        }.build()
        return request(method = "GET", url = url).decode(
            ListSerializer(MileageEntry.serializer())
        )
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
    ): ApiResult<CreatedId> {
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
        return request(method = "POST", url = url).decode(CreatedId.serializer())
    }

    suspend fun deleteMileageEntry(id: String): ApiResult<Unit> =
        request(method = "DELETE", path = "/api/admin/mileage/$id").decodeUnit()

    // -- receipts --------------------------------------------------------

    suspend fun listReceipts(
        reconciled: Boolean? = null,
        category: String? = null,
        dateFrom: String? = null,
        dateTo: String? = null,
    ): ApiResult<List<Receipt>> {
        val url = urlBuilder("/api/admin/receipts").apply {
            reconciled?.let { addQueryParameter("reconciled", it.toString()) }
            category?.let { addQueryParameter("category", it) }
            dateFrom?.let { addQueryParameter("date_from", it) }
            dateTo?.let { addQueryParameter("date_to", it) }
        }.build()
        return request(method = "GET", url = url).decode(
            ListSerializer(Receipt.serializer())
        )
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
    ): ApiResult<CreatedId> {
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
        return request(method = "POST", url = url, body = body).decode(CreatedId.serializer())
    }

    suspend fun reconcileReceipt(receiptId: String, budgetEntryId: String): ApiResult<Unit> {
        val url = urlBuilder("/api/admin/receipts/$receiptId/reconcile")
            .addQueryParameter("budget_entry_id", budgetEntryId)
            .build()
        return request(method = "POST", url = url).decodeUnit()
    }

    suspend fun deleteReceipt(id: String): ApiResult<Unit> =
        request(method = "DELETE", path = "/api/admin/receipts/$id").decodeUnit()

    // -- plumbing ----------------------------------------------------------

    private fun urlBuilder(path: String) = "$baseUrl$path".toHttpUrl().newBuilder()

    private suspend fun request(
        method: String,
        path: String? = null,
        url: HttpUrl? = null,
        body: RequestBody? = null,
    ): RawResponse = withContext(Dispatchers.IO) {
        val resolvedUrl = url ?: "$baseUrl$path".toHttpUrl()
        // OkHttp requires a non-null body for POST/PUT/PATCH -- routes
        // like /api/auth/logout and /send/void-style POSTs (see
        // api/invoices.py's own `@router.post` bodyless actions) are
        // real, valid, bodyless POSTs on the backend, so this can't just
        // require every caller to remember to pass an empty body.
        val effectiveBody = body ?: if (method in BODY_REQUIRED_METHODS) EMPTY_BODY else null
        val builder = Request.Builder().url(resolvedUrl).method(method, effectiveBody)
        // CSRF header only matters for mutating methods -- api/app.py's
        // verify_csrf skips GET/HEAD/OPTIONS entirely, same as this.
        if (method != "GET" && method != "HEAD") {
            cookieJar.value(CSRF_COOKIE_NAME)?.let { builder.header(CSRF_HEADER_NAME, it) }
        }
        val request = builder.build()
        try {
            httpClient.newCall(request).execute().use { response ->
                RawResponse(response.code, response.body?.string().orEmpty())
            }
        } catch (e: IOException) {
            RawResponse(statusCode = -1, bodyText = "", networkError = e)
        }
    }

    private data class RawResponse(
        val statusCode: Int,
        val bodyText: String,
        val networkError: IOException? = null,
    )

    private fun <T> RawResponse.decode(serializer: KSerializer<T>): ApiResult<T> {
        networkError?.let { return ApiResult.NetworkError(it) }
        if (statusCode !in 200..299) return ApiResult.HttpError(statusCode, errorDetail(bodyText))
        return try {
            ApiResult.Success(json.decodeFromString(serializer, bodyText))
        } catch (e: SerializationException) {
            ApiResult.HttpError(statusCode, "malformed response body: ${e.message}")
        }
    }

    private fun RawResponse.decodeUnit(): ApiResult<Unit> {
        networkError?.let { return ApiResult.NetworkError(it) }
        if (statusCode !in 200..299) return ApiResult.HttpError(statusCode, errorDetail(bodyText))
        return ApiResult.Success(Unit)
    }

    // Backend's HTTPException always serializes as {"detail": "..."}
    // (see api/errors.py::to_http_exception) -- falls back to the raw
    // body if that shape isn't there (a 5xx from something upstream of
    // FastAPI, say), rather than silently swallowing it.
    private fun errorDetail(bodyText: String): String =
        try {
            val obj = json.decodeFromString(JsonObject.serializer(), bodyText)
            (obj["detail"] as? JsonPrimitive)?.content ?: bodyText
        } catch (e: SerializationException) {
            bodyText
        }
}
