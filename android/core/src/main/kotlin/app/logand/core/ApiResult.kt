package app.logand.core

// Mirrors typani's Result/ErrorSet philosophy from the backend (see
// ~/.claude/refs/typani.md) in plain Kotlin -- every ApiClient call
// returns one of these instead of throwing, so a caller (a ViewModel)
// is forced to handle the failure path at the call site rather than an
// uncaught exception crashing the app on a flaky mobile connection,
// which is the normal case for this app's actual usage (logging mileage
// from a moving car, spotty signal).
sealed class ApiResult<out T> {
    data class Success<T>(val data: T) : ApiResult<T>()

    // HTTP response received, but a non-2xx status -- statusCode/message
    // come straight from the backend's {"detail": "..."} error body (see
    // backend's api/errors.py::to_http_exception), so a UI layer can show
    // the real reason (e.g. "distance must be a positive value...") not a
    // generic "something went wrong."
    data class HttpError(val statusCode: Int, val message: String) : ApiResult<Nothing>()

    // Never got a response at all -- no connectivity, DNS failure, TLS
    // error, timeout. Distinct from HttpError specifically so the UI can
    // show "check your connection" instead of a server-provided message
    // that doesn't exist for this case.
    data class NetworkError(val cause: Throwable) : ApiResult<Nothing>()
}

inline fun <T, R> ApiResult<T>.map(transform: (T) -> R): ApiResult<R> =
    when (this) {
        is ApiResult.Success -> ApiResult.Success(transform(data))
        is ApiResult.HttpError -> this
        is ApiResult.NetworkError -> this
    }
