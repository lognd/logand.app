package app.logand.mobile.ui.admin.version

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
class AdminVersionViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: AdminVersionViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = AdminVersionViewModel({ client })
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (AdminVersionUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `load populates version info from a real response`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"app_version":"1.2.3","git_commit":"abc123",""" +
                    """"python_version":"3.12.4","platform":"Linux-x86_64",""" +
                    """"dependencies":{"fastapi":"0.111.0","pydantic":"2.7.1"}}""",
            ),
        )

        viewModel.load()
        awaitState { !it.isLoading }

        val info = viewModel.uiState.value.versionInfo
        assertEquals("1.2.3", info?.app_version)
        assertEquals(2, info?.dependencies?.size)
    }

    @Test
    fun `filteredDependencies narrows by a case-insensitive name search`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"app_version":"1.2.3","git_commit":"abc123",""" +
                    """"python_version":"3.12.4","platform":"Linux-x86_64",""" +
                    """"dependencies":{"FastAPI":"0.111.0","pydantic":"2.7.1","typani":"0.3.0"}}""",
            ),
        )

        viewModel.load()
        awaitState { !it.isLoading }

        viewModel.updateDependencySearch("fast")
        assertEquals(listOf("FastAPI" to "0.111.0"), viewModel.uiState.value.filteredDependencies)

        viewModel.updateDependencySearch("")
        assertEquals(3, viewModel.uiState.value.filteredDependencies.size)
    }

    @Test
    fun `load surfaces a network error message`() = runBlocking {
        server.shutdown()

        viewModel.load()
        awaitState { !it.isLoading }

        assertEquals(
            "Could not reach the server. Check your connection.",
            viewModel.uiState.value.errorMessage,
        )
    }
}
