package app.logand.mobile.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "server_settings")
private val BASE_URL_KEY = stringPreferencesKey("base_url")

// Persists only the server address -- deliberately NOT the session
// cookie/credentials. Session state lives purely in the in-memory
// SessionCookieJar inside ApiClient for this app's process lifetime; a
// killed app requires logging in again, a documented tradeoff (see
// docs/design/15-android-app.md) rather than adding encrypted-at-rest
// credential storage to what's meant to be a small, low-risk personal
// data-entry tool.
class ServerSettingsRepository(private val context: Context) {
    companion object {
        const val DEFAULT_BASE_URL = "https://logand.app"
    }

    val baseUrlFlow: Flow<String> =
        context.dataStore.data.map { prefs -> prefs[BASE_URL_KEY] ?: DEFAULT_BASE_URL }

    suspend fun setBaseUrl(url: String) {
        context.dataStore.edit { prefs -> prefs[BASE_URL_KEY] = url }
    }
}
