package app.logand.mobile.ui.admin.taxrates

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

// See BudgetViewModelTest's doc comment for why real time + polling
// (awaitState), not a virtual-time TestDispatcher, is used here.
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class TaxRatesViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: TaxRatesViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = TaxRatesViewModel({ client })
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (TaxRatesUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `load populates rules from a real response`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"tr-1","jurisdiction":"US-TN","tax_type":"sales",""" +
                    """"category":"*","rate":"0.07","source":"TN DOR 2026",""" +
                    """"citation_url":"https://www.tn.gov/revenue.html",""" +
                    """"effective_from":"2026-01-01"}]"""
            )
        )

        viewModel.load()
        awaitState { !it.isLoading }

        assertEquals(1, viewModel.uiState.value.rules.size)
        assertEquals("US-TN", viewModel.uiState.value.rules[0].jurisdiction)
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

    @Test
    fun `addRule without a citation_url is rejected before any network call`() = runBlocking {
        viewModel.updateForm {
            it.copy(
                jurisdiction = "US-TN",
                percent = "7",
                source = "TN DOR 2026",
                citationUrl = "",
            )
        }

        viewModel.addRule()

        assertTrue(viewModel.uiState.value.errorMessage!!.contains("citation"))
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `addRule without a valid rate is rejected before any network call`() = runBlocking {
        viewModel.updateForm {
            it.copy(
                jurisdiction = "US-TN",
                percent = "not-a-number",
                source = "TN DOR 2026",
                citationUrl = "https://www.tn.gov/revenue.html",
            )
        }

        viewModel.addRule()

        assertEquals(0, server.requestCount)
    }

    @Test
    fun `successful addRule converts percent to a decimal fraction, resets the form, and reloads`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """{"id":"tr-2","jurisdiction":"US-TN","tax_type":"sales",""" +
                        """"category":"*","rate":"0.07","source":"TN DOR 2026",""" +
                        """"citation_url":"https://www.tn.gov/revenue.html",""" +
                        """"effective_from":"2026-07-09"}"""
                )
            )
            server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

            viewModel.updateForm {
                it.copy(
                    jurisdiction = "US-TN",
                    taxType = "sales",
                    percent = "7",
                    source = "TN DOR 2026",
                    citationUrl = "https://www.tn.gov/revenue.html",
                )
            }
            viewModel.addRule()
            awaitState { !it.isSubmitting }

            val recorded = server.takeRequest()
            assertTrue(recorded.body.readUtf8().contains("\"rate\":\"0.07\""))
            assertEquals("", viewModel.uiState.value.form.jurisdiction)
        }
}
