package app.logand.mobile.data

import androidx.test.core.app.ApplicationProvider
import kotlin.test.assertEquals
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

// Robolectric -- DataStore needs a real (if simulated) Android Context to
// resolve its backing file, unlike :core's plain-JVM tests.
@RunWith(RobolectricTestRunner::class)
class ServerSettingsRepositoryTest {
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
}
