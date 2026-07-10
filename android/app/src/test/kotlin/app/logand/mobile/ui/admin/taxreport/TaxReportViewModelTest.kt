package app.logand.mobile.ui.admin.taxreport

import app.logand.core.ApiClient
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test

private const val TAX_REPORT_BODY =
    """{"from_date":"2026-01-01","to_date":"2026-12-31","currency":"usd",""" +
        """"invoice_count":2,"total_sales":"200.00","total_tax_collected":"14.00",""" +
        """"filing_jurisdictions":["US-TN"],""" +
        """"by_jurisdiction":[{"jurisdiction":"US-TN","tax_type":"sales",""" +
        """"taxable_base":"200.00","tax_collected":"14.00"}],""" +
        """"by_category":[{"category":"tangible_goods","gross":"200.00",""" +
        """"taxable_gross":"200.00"}]}"""

private const val STRIPE_RECONCILE_BODY =
    """{"total_tax_collected":"14.00","by_jurisdiction":{"US-TN":"14.00"},""" +
        """"transaction_count":2}"""

// getTaxReport and getStripeReconcile run as two independent concurrent
// coroutines (see TaxReportViewModel.load's own doc comment), so which
// one physically reaches MockWebServer first is not deterministic --
// MockWebServer's default QueueDispatcher hands out enqueued responses
// strictly in arrival order, which would occasionally cross-wire the two
// responses and make this suite flaky. Routing by request path instead
// makes each test's outcome independent of that race.
private fun pathRoutedDispatcher(
    reportResponse: MockResponse,
    stripeResponse: MockResponse,
): Dispatcher = object : Dispatcher() {
    override fun dispatch(request: RecordedRequest): MockResponse {
        val path = request.path.orEmpty()
        return if (path.startsWith("/api/admin/invoices/tax-report")) reportResponse else stripeResponse
    }
}

// See BudgetViewModelTest's doc comment for why real time + polling
// (awaitState), not a virtual-time TestDispatcher, is used here.
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class TaxReportViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: TaxReportViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = TaxReportViewModel({ client })
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (TaxReportUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `load fetches both the tax report and the stripe reconcile independently`() = runBlocking {
        server.dispatcher = pathRoutedDispatcher(
            reportResponse = MockResponse().setResponseCode(200).setBody(TAX_REPORT_BODY),
            stripeResponse = MockResponse().setResponseCode(200).setBody(STRIPE_RECONCILE_BODY),
        )

        viewModel.load()
        awaitState { !it.isLoadingReport && !it.isLoadingStripeReconcile }

        assertEquals(2, viewModel.uiState.value.report?.invoice_count)
        assertEquals("14.00", viewModel.uiState.value.stripeReconcile?.total_tax_collected)
        assertEquals(2, server.requestCount)
    }

    @Test
    fun `a report failure does not block the stripe reconcile from loading`() = runBlocking {
        server.dispatcher = pathRoutedDispatcher(
            reportResponse = MockResponse().setResponseCode(500).setBody("""{"detail":"boom"}"""),
            stripeResponse = MockResponse().setResponseCode(200).setBody(STRIPE_RECONCILE_BODY),
        )

        viewModel.load()
        awaitState { !it.isLoadingReport && !it.isLoadingStripeReconcile }

        assertEquals(null, viewModel.uiState.value.report)
        assertTrue(viewModel.uiState.value.errorMessage != null)
        assertEquals("14.00", viewModel.uiState.value.stripeReconcile?.total_tax_collected)
    }

    @Test
    fun `setRange re-fetches both requests with the new dates`() = runBlocking {
        server.dispatcher = pathRoutedDispatcher(
            reportResponse = MockResponse().setResponseCode(200).setBody(TAX_REPORT_BODY),
            stripeResponse = MockResponse().setResponseCode(200).setBody(STRIPE_RECONCILE_BODY),
        )
        viewModel.load()
        awaitState { !it.isLoadingReport && !it.isLoadingStripeReconcile }
        server.takeRequest()
        server.takeRequest()

        viewModel.setRange(TaxDateRange(from = "2025-01-01", to = "2025-12-31"))
        awaitState { !it.isLoadingReport && !it.isLoadingStripeReconcile }

        val paths = listOf(server.takeRequest().path!!, server.takeRequest().path!!)
        assertTrue(paths.all { it.contains("from_date=2025-01-01") })
        assertTrue(paths.all { it.contains("to_date=2025-12-31") })
    }
}
