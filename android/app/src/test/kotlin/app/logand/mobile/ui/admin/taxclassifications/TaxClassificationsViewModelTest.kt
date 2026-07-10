package app.logand.mobile.ui.admin.taxclassifications

import app.logand.core.ApiClient
import kotlin.test.assertEquals
import kotlin.test.assertNull
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

private const val PENDING_CLASSIFICATION_BODY =
    """[{"id":"tc-1","normalized_key":"widget","description":"Widget",""" +
        """"category":"tangible_goods","taxable":true,"hts_code":null,""" +
        """"status":"pending","source":"claude","model":"claude-sonnet",""" +
        """"rationale":"generic hardware item","confirmed_at":null,""" +
        """"updated_at":"2026-07-01T00:00:00Z"}]"""

// See BudgetViewModelTest's doc comment for why real time + polling
// (awaitState), not a virtual-time TestDispatcher, is used here.
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class TaxClassificationsViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: TaxClassificationsViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = TaxClassificationsViewModel({ client })
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (TaxClassificationsUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `load with default pending filter passes status=pending`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(PENDING_CLASSIFICATION_BODY))

        viewModel.load()
        awaitState { !it.isLoading }

        val path = server.takeRequest().path!!
        assertTrue(path.contains("status=pending"))
        assertEquals(1, viewModel.uiState.value.classifications.size)
    }

    @Test
    fun `setStatusFilter to all omits the status query param and reloads`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        viewModel.load()
        awaitState { !it.isLoading }
        server.takeRequest()

        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        viewModel.setStatusFilter("all")
        awaitState { !it.isLoading }

        val path = server.takeRequest().path!!
        assertEquals("/api/admin/tax/classifications", path)
    }

    @Test
    fun `confirming a classification requires requestConfirm before submitConfirm fires`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(PENDING_CLASSIFICATION_BODY))
        viewModel.load()
        awaitState { !it.isLoading }
        server.takeRequest()
        val countBeforeUnarmedAttempt = server.requestCount

        // No confirmingKey armed yet -- must not hit the network.
        viewModel.submitConfirm("widget")
        assertEquals(countBeforeUnarmedAttempt, server.requestCount)

        viewModel.requestConfirm("widget")
        assertEquals("widget", viewModel.uiState.value.confirmingKey)

        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"id":"tc-1","normalized_key":"widget","description":"Widget",""" +
                    """"category":"tangible_goods","taxable":true,"hts_code":null,""" +
                    """"status":"confirmed","source":"claude","model":null,"rationale":null,""" +
                    """"confirmed_at":"2026-07-09T00:00:00Z","updated_at":"2026-07-09T00:00:00Z"}"""
            )
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.submitConfirm("widget")
        awaitState { !it.isSubmittingConfirm }

        assertEquals("/api/admin/tax/classifications/widget/confirm", server.takeRequest().path)
        assertNull(viewModel.uiState.value.confirmingKey)
    }

    @Test
    fun `overriding requires requestConfirmOverride before submitOverride fires`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(PENDING_CLASSIFICATION_BODY))
        viewModel.load()
        awaitState { !it.isLoading }
        server.takeRequest()

        val classification = viewModel.uiState.value.classifications[0]
        viewModel.openOverrideForm(classification)
        viewModel.updateOverrideForm { it.copy(category = "electronics", taxable = false) }
        val countBeforeUnarmedAttempt = server.requestCount

        // Not yet confirmed -- must not hit the network.
        viewModel.submitOverride()
        assertEquals(countBeforeUnarmedAttempt, server.requestCount)

        viewModel.requestConfirmOverride()
        assertTrue(viewModel.uiState.value.confirmingOverride)

        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"id":"tc-1","normalized_key":"widget","description":"Widget",""" +
                    """"category":"electronics","taxable":false,"hts_code":null,""" +
                    """"status":"overridden","source":"admin","model":null,"rationale":null,""" +
                    """"confirmed_at":"2026-07-09T00:00:00Z","updated_at":"2026-07-09T00:00:00Z"}"""
            )
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.submitOverride()
        awaitState { !it.isSubmittingOverride }

        val recorded = server.takeRequest()
        assertEquals("/api/admin/tax/classifications/widget/override", recorded.path)
        assertTrue(recorded.body.readUtf8().contains("\"category\":\"electronics\""))
        assertNull(viewModel.uiState.value.overridingKey)
    }

    @Test
    fun `requestConfirmOverride with a blank category is rejected before arming confirmation`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(PENDING_CLASSIFICATION_BODY))
            viewModel.load()
            awaitState { !it.isLoading }
            server.takeRequest()

            val classification = viewModel.uiState.value.classifications[0]
            viewModel.openOverrideForm(classification)
            viewModel.updateOverrideForm { it.copy(category = "") }

            viewModel.requestConfirmOverride()

            assertEquals(false, viewModel.uiState.value.confirmingOverride)
            assertEquals("Category is required.", viewModel.uiState.value.errorMessage)
        }
}
