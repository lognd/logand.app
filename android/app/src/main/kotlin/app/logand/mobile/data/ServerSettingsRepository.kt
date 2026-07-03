package app.logand.mobile.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import java.net.URI
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "server_settings")
private val BASE_URL_KEY = stringPreferencesKey("base_url")

// Hosts network_security_config.xml allows real cleartext HTTP for --
// emulator host-loopback and physical-device localhost testing only,
// never a real domain. Kept in sync with that file by hand (both are
// small, hand-edited allowlists of exactly the same two dev hosts).
private val CLEARTEXT_ALLOWED_HOSTS = setOf("10.0.2.2", "localhost")

class InvalidServerUrlException(message: String) : IllegalArgumentException(message)

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

    // Validates before ever persisting -- SessionCookieJar sends whatever
    // cookies it's holding to ANY host this app's ApiClient is pointed
    // at (see that class's own doc comment: it deliberately does no
    // per-host cookie scoping, since a real mobile client only ever
    // talks to one configured backend). That makes THIS validation the
    // actual backstop against the session cookie ending up sent to an
    // arbitrary/malicious host: reject anything that isn't either a real
    // https:// URL, or plain http:// to one of the small, fixed set of
    // local dev hosts network_security_config.xml itself allows
    // cleartext traffic to.
    suspend fun setBaseUrl(url: String) {
        val parsed = try {
            URI(url)
        } catch (e: java.net.URISyntaxException) {
            throw InvalidServerUrlException("not a valid URL: $url")
        }
        val scheme = parsed.scheme
        val host = parsed.host
        if (host.isNullOrBlank()) {
            throw InvalidServerUrlException("URL has no host: $url")
        }
        val isValid = when (scheme) {
            "https" -> true
            // Lowercased before the membership check -- URI("http://LOCALHOST:8000").host
            // is "LOCALHOST" verbatim (URI doesn't normalize host casing), which
            // network_security_config.xml's own (case-insensitive) domain match
            // would allow but this set-membership check would wrongly reject.
            "http" -> host.lowercase() in CLEARTEXT_ALLOWED_HOSTS
            else -> false
        }
        if (!isValid) {
            throw InvalidServerUrlException(
                "server URL must be https, or http to a local dev host " +
                    "(${CLEARTEXT_ALLOWED_HOSTS.joinToString()}): $url",
            )
        }
        context.dataStore.edit { prefs -> prefs[BASE_URL_KEY] = url }
    }

    // Reverts to DEFAULT_BASE_URL by removing the stored override rather
    // than writing DEFAULT_BASE_URL as a literal value -- makes
    // baseUrlFlow's fallback the one and only source of truth for what
    // "unconfigured" means, so a future change to DEFAULT_BASE_URL is
    // automatically picked up by anyone who has reset rather than
    // needing this to be re-called.
    suspend fun clear() {
        context.dataStore.edit { prefs -> prefs.remove(BASE_URL_KEY) }
    }
}
