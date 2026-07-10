package app.logand.mobile.ui.admin.logs

import app.logand.core.ApiClient
import kotlin.test.assertEquals
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

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class AdminLogsViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: AdminLogsViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = AdminLogsViewModel({ client })
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (AdminLogsUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `loadFiles populates the file list from a real response`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""[{"name":"app.log","size_bytes":1024,"modified_at":1751328000.0}]"""),
        )

        viewModel.loadFiles()
        awaitState { !it.isLoadingFiles }

        assertEquals(1, viewModel.uiState.value.files.size)
        assertEquals("app.log", viewModel.uiState.value.files[0].name)
    }

    @Test
    fun `loadTail populates tail lines`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""["line one","line two"]"""))

        viewModel.loadTail()
        awaitState { !it.isLoadingTail }

        assertEquals(listOf("line one", "line two"), viewModel.uiState.value.tailLines)
    }

    @Test
    fun `downloadFile delivers bytes to the callback on success`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("log contents")
                .setHeader("Content-Type", "application/octet-stream"),
        )

        var received: ByteArray? = null
        viewModel.downloadFile("app.log") { received = it }
        awaitState { !it.isDownloading }

        assertEquals("log contents", received?.toString(Charsets.UTF_8))
    }

    @Test
    fun `downloadFile surfaces an http error and calls back with null`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(404).setBody("""{"detail":"not found"}"""))

        var received: ByteArray? = "sentinel".toByteArray()
        viewModel.downloadFile("missing.log") { received = it }
        awaitState { !it.isDownloading }

        assertEquals(null, received)
        assertEquals("not found", viewModel.uiState.value.errorMessage)
    }

    @Test
    fun `loadFiles surfaces a network error message`() = runBlocking {
        server.shutdown()

        viewModel.loadFiles()
        awaitState { !it.isLoadingFiles }

        assertEquals(
            "Could not reach the server. Check your connection.",
            viewModel.uiState.value.errorMessage,
        )
    }
}
