package app.logand.mobile.ui.admin.budget

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

// See MileageViewModelTest's doc comment for why real time + polling
// (awaitState), not a virtual-time TestDispatcher, is used here.
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class BudgetViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: BudgetViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = BudgetViewModel({ client })
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (BudgetUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `load populates entries from a real response`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"e-1","amount":"12.50","category":"supplies","vendor":"Acme",""" +
                    """"memo":null,"occurred_on":"2026-07-01","corrects_entry_id":null}]"""
            )
        )

        viewModel.load()
        awaitState { !it.isLoading }

        assertEquals(1, viewModel.uiState.value.entries.size)
        assertEquals("supplies", viewModel.uiState.value.entries[0].category)
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
    fun `createEntry without required fields is rejected before any network call`() = runBlocking {
        viewModel.updateCreateForm { it.copy(amount = "", category = "", occurredOn = "") }

        viewModel.createEntry()

        assertEquals(
            "Amount, category, and date are required.",
            viewModel.uiState.value.errorMessage,
        )
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `successful createEntry resets the form and reloads`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"e-1"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.updateCreateForm {
            it.copy(amount = "12.50", category = "supplies", occurredOn = "2026-07-01")
        }
        viewModel.createEntry()
        awaitState { !it.isSubmitting }

        assertEquals("", viewModel.uiState.value.createForm.amount)
        assertEquals(null, viewModel.uiState.value.errorMessage)
    }

    @Test
    fun `uploadEvidence tracks the uploading entry id and reloads on success`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"proof-1"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.uploadEvidence("e-1", byteArrayOf(1, 2, 3), "receipt.pdf", "application/pdf")
        awaitState { it.uploadingEntryId == null }

        assertEquals(null, viewModel.uiState.value.errorMessage)
    }

    @Test
    fun `uploadEvidence surfaces a backend error and clears the uploading flag`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(422)
                .setBody("""{"detail":"unsupported evidence content type"}""")
        )

        viewModel.uploadEvidence("e-1", byteArrayOf(1), "x.txt", "text/plain")
        awaitState { it.uploadingEntryId == null }

        assertEquals(
            "unsupported evidence content type",
            viewModel.uiState.value.errorMessage,
        )
    }

    @Test
    fun `exportCsv hands the raw bytes to the callback`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("date,category,amount\n2026-07-01,supplies,12.50\n")
        )

        var exported: ByteArray? = null
        viewModel.exportCsv { exported = it }
        awaitState { !it.isExporting }

        assertTrue(exported != null && String(exported!!).contains("supplies"))
    }
}
