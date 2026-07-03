package app.logand.mobile.data

import android.content.Context
import app.logand.core.ApiClient
import app.logand.core.logging.FileLogger
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first

// Minimal manual DI container -- one ApiClient instance for the app's
// lifetime, rebuilt only when the server URL setting changes (see
// ServerSettingsRepository). No DI framework (Hilt/Koin) pulled in for
// an app this size; this single container is simpler to read end to end.
class AppContainer(context: Context) {
    val serverSettings = ServerSettingsRepository(context)

    // filesDir (not cacheDir) -- see file_paths.xml's app_logs entry doc
    // comment on why the log directory itself needs to survive across
    // restarts, unlike ShareLogsAction's own temp export file.
    val logger = FileLogger(logDir = context.filesDir.resolve("logs"))

    // The app-wide "a call just came back 401" signal -- every ApiClient
    // built here wires its onUnauthorized callback to emit here, so a
    // session that expires (idle timeout) or is revoked (a deactivated
    // account, an admin's "kill all sessions") mid-use gets caught the
    // moment ANY call returns a real 401, not just at login/me() time.
    // Previously nothing observed 401s app-wide at all: an expired
    // session surfaced as a generic per-call HttpError on whatever screen
    // happened to be active, and the app kept believing it was logged in
    // until the user manually logged out and back in.
    //
    // This is a SharedFlow of *events*, not a StateFlow of state: a
    // StateFlow holding SessionState was tried first, but it started (and
    // stayed) at LoggedOut in production -- nothing here ever sets it to
    // LoggedIn, since login updates LoginViewModel's own session state
    // directly. Assigning LoggedOut again on a 401 was then a no-op:
    // MutableStateFlow suppresses emission of a value structurally equal
    // to the current one, so collectors were never notified. An event
    // flow has no such equality-dedup -- every 401 reaches collectors,
    // regardless of what (if anything) they think the session currently
    // is. A screen wanting to react to this (e.g. route back to login)
    // should collect this flow and force its own session state to
    // LoggedOut on every emission.
    private val _logoutEvents = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    val logoutEvents: SharedFlow<Unit> = _logoutEvents

    private val _apiClient = MutableStateFlow(buildClient(ServerSettingsRepository.DEFAULT_BASE_URL))
    val apiClient: StateFlow<ApiClient> = _apiClient

    suspend fun initialize() {
        val savedUrl = serverSettings.baseUrlFlow.first()
        _apiClient.value = buildClient(savedUrl)
    }

    suspend fun updateServerUrl(url: String) {
        serverSettings.setBaseUrl(url)
        _apiClient.value = buildClient(url)
    }

    private fun buildClient(baseUrl: String) = ApiClient(
        baseUrl = baseUrl,
        onUnauthorized = { _logoutEvents.tryEmit(Unit) },
    )
}
