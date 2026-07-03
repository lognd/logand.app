package app.logand.mobile.data

import androidx.test.core.app.ApplicationProvider
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

// Robolectric -- DataStore needs a real (if simulated) Android Context to
// resolve its backing file, unlike :core's plain-JVM tests.
@RunWith(RobolectricTestRunner::class)
class ServerSettingsRepositoryTest {
    // ApplicationProvider.getApplicationContext() returns the SAME
    // Application/Context instance across every @Test method in this
    // class run, and DataStore's delegate caches one in-memory instance
    // per Context identity -- without this, a URL persisted by one test
    // (e.g. "setBaseUrl persists...") was still cached in memory when a
    // LATER test (e.g. "defaults to the production base URL...") ran,
    // making that test's outcome depend on method execution order
    // instead of being self-contained. repo.clear() (not deleting the
    // backing file on disk) is the real fix -- DataStore doesn't re-read
    // an externally-modified file into its in-memory cache, so deleting
    // the file underneath it has no effect on a session that's already
    // read it.
    @Before
    fun clearPersistedState() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        ServerSettingsRepository(context).clear()
    }

    @Test
    fun `defaults to the production base URL when nothing has been saved`() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val repo = ServerSettingsRepository(context)

        assertEquals(ServerSettingsRepository.DEFAULT_BASE_URL, repo.baseUrlFlow.first())
    }

    @Test
    fun `setBaseUrl persists and is reflected by baseUrlFlow`() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val repo = ServerSettingsRepository(context)

        repo.setBaseUrl("http://10.0.2.2:8000")

        assertEquals("http://10.0.2.2:8000", repo.baseUrlFlow.first())
    }

    @Test
    fun `setBaseUrl accepts a real https URL`() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val repo = ServerSettingsRepository(context)

        repo.setBaseUrl("https://logand.app")

        assertEquals("https://logand.app", repo.baseUrlFlow.first())
    }

    @Test
    fun `setBaseUrl accepts cleartext http to localhost`() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val repo = ServerSettingsRepository(context)

        repo.setBaseUrl("http://localhost:8000")

        assertEquals("http://localhost:8000", repo.baseUrlFlow.first())
    }

    @Test
    fun `setBaseUrl accepts cleartext http to a mixed-case localhost`() = runBlocking {
        // Regression test for FINDINGS.md L3: URI("http://LOCALHOST:8000").host
        // is "LOCALHOST" verbatim (URI doesn't normalize casing), which used
        // to fail the raw `host in CLEARTEXT_ALLOWED_HOSTS` check even though
        // network_security_config.xml's own case-insensitive domain match
        // allows it.
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val repo = ServerSettingsRepository(context)

        repo.setBaseUrl("http://LOCALHOST:8000")

        assertEquals("http://LOCALHOST:8000", repo.baseUrlFlow.first())
    }

    @Test
    fun `setBaseUrl rejects cleartext http to an arbitrary host`() = runBlocking {
        // Regression test for AND3: SessionCookieJar sends its cookies to
        // whatever host this app is pointed at, with no per-host scoping
        // (see that class's own doc comment) -- an unvalidated base URL
        // would let the live session cookie be sent, in the clear, to any
        // host a user (or something else with access to this setting)
        // configured.
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val repo = ServerSettingsRepository(context)

        assertFailsWith<InvalidServerUrlException> {
            repo.setBaseUrl("http://evil.example.com")
        }
        // The previously-saved (default) value must still be in effect --
        // a rejected setBaseUrl call must not partially apply.
        assertEquals(ServerSettingsRepository.DEFAULT_BASE_URL, repo.baseUrlFlow.first())
    }

    @Test
    fun `setBaseUrl rejects a malformed URL`() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val repo = ServerSettingsRepository(context)

        assertFailsWith<InvalidServerUrlException> {
            repo.setBaseUrl("not a url")
        }
        Unit
    }
}
