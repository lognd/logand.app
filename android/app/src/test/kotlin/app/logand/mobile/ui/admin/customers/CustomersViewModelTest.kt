package app.logand.mobile.ui.admin.customers

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
class CustomersViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: CustomersViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = CustomersViewModel { client }
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (CustomersUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `search populates customers from a real response`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""[{"id":"cust-1","email":"alice@example.com"}]"""),
        )

        viewModel.search("alice")
        awaitState { !it.isLoading }

        assertEquals(1, viewModel.uiState.value.customers.size)
        assertEquals("alice@example.com", viewModel.uiState.value.customers[0].email)
    }

    @Test
    fun `search surfaces a network error message`() = runBlocking {
        server.shutdown()

        viewModel.search("")
        awaitState { !it.isLoading }

        assertEquals(
            "Could not reach the server. Check your connection.",
            viewModel.uiState.value.errorMessage,
        )
    }

    @Test
    fun `toggleDetail loads then collapses on a second call`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"id":"cust-1","email":"alice@example.com","role":"customer",""" +
                    """"emails_opted_out":false,"disabled_at":null,"created_at":"2026-01-01"}"""
            )
        )

        viewModel.toggleDetail("cust-1")
        awaitState { !it.isDetailLoading }
        assertEquals("cust-1", viewModel.uiState.value.selectedId)
        assertEquals("alice@example.com", viewModel.uiState.value.selectedDetail?.email)

        viewModel.toggleDetail("cust-1")
        assertEquals(null, viewModel.uiState.value.selectedId)
        assertEquals(null, viewModel.uiState.value.selectedDetail)
    }

    @Test
    fun `resetPassword rejects a short password before any network call`() = runBlocking {
        viewModel.resetPassword("cust-1", "short")

        assertEquals(
            "New password must be at least 8 characters.",
            viewModel.uiState.value.errorMessage,
        )
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `deactivate reloads the customer detail on success`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"ok"}"""))
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"id":"cust-1","email":"alice@example.com","role":"customer",""" +
                    """"emails_opted_out":false,"disabled_at":"2026-07-09T00:00:00","created_at":"2026-01-01"}"""
            )
        )

        viewModel.deactivate("cust-1")
        awaitState { it.selectedDetail?.disabled_at != null }

        assertEquals("2026-07-09T00:00:00", viewModel.uiState.value.selectedDetail?.disabled_at)
    }
}
