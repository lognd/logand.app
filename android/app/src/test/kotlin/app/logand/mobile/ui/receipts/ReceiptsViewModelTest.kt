package app.logand.mobile.ui.receipts

import app.logand.core.ApiClient
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test

// See LoginViewModelTest's doc comment for why real time + polling
// (awaitState), not a virtual-time TestDispatcher, is used here.
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class ReceiptsViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: ReceiptsViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = ReceiptsViewModel { client }
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (ReceiptsUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `load populates receipts from a real response`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"r-1","vendor":"Home Depot","amount":"42.17",""" +
                    """"category":"supplies","occurred_on":null,"note":null,""" +
                    """"reconciled_budget_entry_id":null,"captured_at":"2026-06-01T00:00:00Z"}]"""
            )
        )

        viewModel.load()
        awaitState { !it.isLoading }

        assertEquals(1, viewModel.uiState.value.receipts.size)
        assertEquals("Home Depot", viewModel.uiState.value.receipts[0].vendor)
    }

    @Test
    fun `capture with only the photo succeeds and reloads`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"r-1"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        var callbackResult: Boolean? = null
        viewModel.capture(
            fileBytes = "fake-jpeg-bytes".toByteArray(),
            filename = "receipt.jpg",
            mimeType = "image/jpeg",
        ) { callbackResult = it }
        awaitState { !it.isUploading }

        assertEquals(true, callbackResult)
        val recorded = server.takeRequest()
        assertTrue(recorded.getHeader("Content-Type")!!.startsWith("multipart/form-data"))
        assertEquals(null, viewModel.uiState.value.errorMessage)
    }

    @Test
    fun `capture failure surfaces the backend error and calls onDone(false)`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(415).setBody("""{"detail":"receipt must be a PDF or image"}""")
        )

        var callbackResult: Boolean? = null
        viewModel.capture(
            fileBytes = "bytes".toByteArray(),
            filename = "receipt.txt",
            mimeType = "text/plain",
        ) { callbackResult = it }
        awaitState { !it.isUploading }

        assertEquals(false, callbackResult)
        assertEquals("receipt must be a PDF or image", viewModel.uiState.value.errorMessage)
    }

    @Test
    fun `delete reloads the list on success`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"deleted"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.delete("r-1")

        // See MileageViewModelTest's identical case for why this waits on
        // the requests themselves rather than `it.receipts.isEmpty()`
        // (already true in the initial state).
        val first = server.takeRequest(2, java.util.concurrent.TimeUnit.SECONDS)
        val second = server.takeRequest(2, java.util.concurrent.TimeUnit.SECONDS)

        assertEquals("DELETE", first?.method)
        assertEquals("GET", second?.method)
    }

    @Test
    fun `delete surfaces an error message on failure`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(404).setBody("""{"detail":"receipt was not found"}""")
        )

        viewModel.delete("nonexistent")
        awaitState { it.errorMessage != null }

        assertEquals("receipt was not found", viewModel.uiState.value.errorMessage)
    }
}
