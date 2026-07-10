package app.logand.core

import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody

private const val CSRF_COOKIE_NAME = "csrf_token"
private const val CSRF_HEADER_NAME = "X-CSRF-Token"
private val BODY_REQUIRED_METHODS = setOf("POST", "PUT", "PATCH")
private val EMPTY_BODY = "".toRequestBody(null)

// The request/CSRF/error-decoding plumbing shared by every ApiClient
// surface (auth/mileage/receipts on ApiClient itself, the admin surface
// on AdminApi) -- pulled out so growing the admin surface never means a
// second copy of "attach the CSRF header," "fire onUnauthorized on 401,"
// or "unwrap the backend's {"detail": ...} error shape" living somewhere
// else and silently drifting out of sync with this one (see the
// project's NO DUPLICATION rule). ApiClient owns the one instance of this
// and hands the SAME instance to AdminApi -- one cookie jar, one OkHttp
// client, one onUnauthorized hook, for every call this process makes.
internal class HttpPlumbing(
    baseUrl: String,
    private val cookieJar: SessionCookieJar,
    private val httpClient: OkHttpClient,
    private val onUnauthorized: (() -> Unit)?,
) {
    private val baseUrl = baseUrl.trimEnd('/')
    val json = Json { ignoreUnknownKeys = true }

    fun urlBuilder(path: String) = "$baseUrl$path".toHttpUrl().newBuilder()

    suspend fun request(
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
                RawResponse(response.code, response.body?.bytes() ?: ByteArray(0))
            }
        } catch (e: IOException) {
            RawResponse(statusCode = -1, bodyBytes = ByteArray(0), networkError = e)
        }
    }

    data class RawResponse(
        val statusCode: Int,
        val bodyBytes: ByteArray,
        val networkError: IOException? = null,
    ) {
        val bodyText: String get() = bodyBytes.decodeToString()
    }

    fun <T> RawResponse.decode(
        serializer: KSerializer<T>,
        notifyOn401: Boolean = true,
    ): ApiResult<T> {
        networkError?.let { return ApiResult.NetworkError(it) }
        if (statusCode == 401 && notifyOn401) onUnauthorized?.invoke()
        if (statusCode !in 200..299) return ApiResult.HttpError(statusCode, errorDetail(bodyText))
        return try {
            ApiResult.Success(json.decodeFromString(serializer, bodyText))
        } catch (e: SerializationException) {
            ApiResult.HttpError(statusCode, "malformed response body: ${e.message}")
        }
    }

    fun RawResponse.decodeUnit(notifyOn401: Boolean = true): ApiResult<Unit> {
        networkError?.let { return ApiResult.NetworkError(it) }
        if (statusCode == 401 && notifyOn401) onUnauthorized?.invoke()
        if (statusCode !in 200..299) return ApiResult.HttpError(statusCode, errorDetail(bodyText))
        return ApiResult.Success(Unit)
    }

    // Raw-bytes decode for binary downloads (invoice PDFs, log files) --
    // unlike decode()/decodeUnit(), never routes the body through
    // Json/UTF-8 text decoding, which would corrupt non-UTF8 binary
    // content (a PDF's bytes are not text at all).
    fun RawResponse.decodeBytes(notifyOn401: Boolean = true): ApiResult<ByteArray> {
        networkError?.let { return ApiResult.NetworkError(it) }
        if (statusCode == 401 && notifyOn401) onUnauthorized?.invoke()
        if (statusCode !in 200..299) return ApiResult.HttpError(statusCode, errorDetail(bodyText))
        return ApiResult.Success(bodyBytes)
    }

    // Backend's HTTPException serializes as either {"detail": "..."} (flat,
    // e.g. 401 from auth deps, bare-string HTTPExceptions) or, since commit
    // 77bae7e (see api/errors.py::to_http_exception), a nested
    // {"detail": {"detail": "...", "code": "..."}} for domain errors. Falls
    // back to the raw body if neither shape is there (a 5xx from something
    // upstream of FastAPI, say), rather than silently swallowing it.
    fun errorDetail(bodyText: String): String =
        try {
            val obj = json.decodeFromString(JsonObject.serializer(), bodyText)
            when (val detail = obj["detail"]) {
                is JsonPrimitive -> detail.content
                is JsonObject -> (detail["detail"] as? JsonPrimitive)?.content ?: bodyText
                else -> bodyText
            }
        } catch (e: SerializationException) {
            bodyText
        }
}
