package app.logand.mobile.data

import android.content.Context
import app.logand.core.ApiClient
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first

// Minimal manual DI container -- one ApiClient instance for the app's
// lifetime, rebuilt only when the server URL setting changes (see
// ServerSettingsRepository). No DI framework (Hilt/Koin) pulled in for
// an app this size; this single container is simpler to read end to end.
class AppContainer(context: Context) {
    val serverSettings = ServerSettingsRepository(context)

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

    private fun buildClient(baseUrl: String) = ApiClient(baseUrl = baseUrl)
}
