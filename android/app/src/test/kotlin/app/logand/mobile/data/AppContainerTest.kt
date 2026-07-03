package app.logand.mobile.data

import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

// Robolectric -- AppContainer needs a real (if simulated) Android Context
// for its FileLogger/ServerSettingsRepository, same reasoning as
// ServerSettingsRepositoryTest.
@RunWith(RobolectricTestRunner::class)
class AppContainerTest {
    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `logoutEvents emits when the wired ApiClient sees a 401`() = runBlocking {
        // Regression test for AND2/M1: AppContainer wires every ApiClient it
        // builds to emit on its app-wide logoutEvents on any 401 --
        // previously nothing app-wide observed a mid-session 401 at all.
        //
        // This used to assert against a `sessionState: StateFlow` that
        // AppContainer set to LoggedOut on 401 -- but that flow started
        // (and, in production, stayed) at LoggedOut, so assigning
        // LoggedOut again was a no-op under MutableStateFlow's
        // equality-dedup, and the collector in LoginViewModel was never
        // notified (see FINDINGS.md M1). logoutEvents is a SharedFlow of
        // events instead, so every 401 reaches collectors regardless of
        // prior state -- this test now awaits an actual emission rather
        // than seeding a distinct-looking prior value to dodge the dedup.
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val container = AppContainer(context)
        container.updateServerUrl(server.url("/").toString())

        val emission = async { container.logoutEvents.first() }

        server.enqueue(
            MockResponse().setResponseCode(401)
                .setBody("""{"detail":"session expired"}""")
        )

        container.apiClient.value.deleteMileageEntry("m-1")

        emission.await()
        Unit
    }
}
