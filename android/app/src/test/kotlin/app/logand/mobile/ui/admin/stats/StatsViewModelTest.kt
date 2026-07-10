package app.logand.mobile.ui.admin.stats

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
class StatsViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: StatsViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = StatsViewModel { client }
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (StatsUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `load populates stats from a real response`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"by_status":{"paid":{"count":2,"amount_total":"200.00"}},""" +
                    """"total_collected":"200.00","total_refunded":"0.00",""" +
                    """"net_collected":"200.00","outstanding":"0.00",""" +
                    """"by_payment_method":{"stripe":{"count":2,"amount":"200.00"}},""" +
                    """"open_disputes":0,""" +
                    """"disputes":{"needs_response":0,"under_review":0,"won":0,"lost":0}}"""
            )
        )

        viewModel.load()
        awaitState { !it.isLoading }

        assertEquals("200.00", viewModel.uiState.value.stats?.total_collected)
        assertEquals(2, viewModel.uiState.value.stats?.by_status?.get("paid")?.count)
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
