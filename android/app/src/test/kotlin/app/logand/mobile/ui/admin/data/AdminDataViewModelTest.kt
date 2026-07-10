package app.logand.mobile.ui.admin.data

import app.logand.core.ApiClient
import kotlin.test.assertEquals
import kotlin.test.assertFalse
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

// See MileageViewModelTest's doc comment for why real time + polling
// (awaitState), not a virtual-time TestDispatcher, is used here.
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class AdminDataViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: AdminDataViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = AdminDataViewModel({ client })
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    // 10s, not 2s: the two tests here that chain three sequential HTTP
    // round-trips (changedKeys, submitDelete) intermittently exceeded a 2s
    // budget on a cold JVM, showing up as a bare TimeoutCancellationException
    // with no hint of what was actually stuck. Generous timeouts cost nothing
    // on a passing run; a tight one buys a flaky suite. The `errorMessage`
    // assertions at the wait sites keep a genuine failure from hiding here as
    // a timeout.
    private suspend fun awaitState(predicate: (AdminDataUiState) -> Boolean) {
        withTimeout(10_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    // selectTable() fires loadSchema() and loadRows() as two CONCURRENT
    // coroutines, so their two requests reach MockWebServer in
    // nondeterministic order. The default QueueDispatcher hands out
    // enqueued bodies strictly in arrival order, so a plain enqueue(schema)
    // + enqueue(rows) pair silently gives the rows body to the schema call
    // about half the time -- this test class was failing 3 runs in 6 that
    // way. Route on the request itself instead of on arrival order; the
    // production concurrency is correct and is not what needs changing.
    private fun dispatchBy(handler: (RecordedRequest) -> MockResponse?) {
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse =
                handler(request) ?: MockResponse().setResponseCode(404).setBody("""{}""")
        }
    }

    private fun ok(body: String) = MockResponse().setResponseCode(200).setBody(body)

    // selectTable()'s two coroutines have not necessarily set isLoadingSchema
    // / isLoadingRows by the time the caller looks, so `awaitState { !loading }`
    // can return BEFORE either request is even in flight. Waiting until the
    // server has actually served both requests is the only condition that is
    // true strictly after the loads have happened.
    private suspend fun awaitRequests(count: Int) {
        withTimeout(10_000) {
            while (server.requestCount < count) {
                delay(5)
            }
        }
    }

    /** True for the row-collection endpoint (".../rows", ".../rows?limit="),
     * false for a single row (".../rows/m-1"). */
    private fun RecordedRequest.isRowCollection(): Boolean {
        val p = path.orEmpty().substringBefore('?')
        return p.endsWith("/rows")
    }

    @Test
    fun `loadTables populates the table list`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""["mileage_entries","receipts"]"""))

        viewModel.loadTables()
        awaitState { !it.isLoadingTables }

        assertEquals(listOf("mileage_entries", "receipts"), viewModel.uiState.value.tables)
    }

    @Test
    fun `selectTable loads schema and rows and resets prior row selection`() = runBlocking {
        dispatchBy { request ->
            when {
                request.path.orEmpty().contains("/schema") ->
                    ok("""[{"name":"id","type":"text"},{"name":"vehicle","type":"text"}]""")
                request.isRowCollection() -> ok("""[{"id":"m-1","vehicle":"Civic"}]""")
                else -> null
            }
        }

        viewModel.selectTable("mileage_entries")
        awaitRequests(2)
        awaitState { !it.isLoadingRows && !it.isLoadingSchema }

        assertEquals("mileage_entries", viewModel.uiState.value.selectedTable)
        assertEquals(2, viewModel.uiState.value.schema.size)
        assertEquals(1, viewModel.uiState.value.rows.size)
        assertEquals(null, viewModel.uiState.value.selectedRowId)
    }

    @Test
    fun `changedKeys only reports fields whose edit differs from the loaded row`() = runBlocking {
        // selectedRow must actually load: changedKeys short-circuits to
        // emptyList() while selectedRow is null, which would make the
        // "nothing changed yet" assertion below pass vacuously.
        dispatchBy { request ->
            when {
                request.path.orEmpty().contains("/schema") -> ok("[]")
                request.isRowCollection() -> ok("[]")
                else -> ok("""{"id":"m-1","vehicle":"Civic"}""")
            }
        }
        viewModel.selectTable("mileage_entries")
        awaitRequests(2)
        awaitState { !it.isLoadingRows && !it.isLoadingSchema }

        viewModel.selectRow("m-1")
        awaitState { it.selectedRow != null || it.errorMessage != null }
        assertEquals(null, viewModel.uiState.value.errorMessage)
        assertEquals("Civic", viewModel.uiState.value.selectedRow?.get("vehicle")?.toString()?.trim('"'))

        viewModel.updateEditField("vehicle", "Civic")
        assertTrue(viewModel.uiState.value.changedKeys.isEmpty())

        viewModel.updateEditField("vehicle", "Accord")
        assertEquals(listOf("vehicle"), viewModel.uiState.value.changedKeys)
    }

    @Test
    fun `requestConfirmUpdate is a no-op when nothing changed`() {
        viewModel.requestConfirmUpdate()
        assertFalse(viewModel.uiState.value.confirmingUpdate)
    }

    @Test
    fun `submitDelete requires an explicit confirm before any network call happens`() = runBlocking {
        dispatchBy { request ->
            when {
                request.path.orEmpty().contains("/schema") -> ok("[]")
                request.method == "DELETE" -> ok("""{"change_id":"c-1"}""")
                request.isRowCollection() -> ok("[]")
                else -> ok("""{"id":"m-1"}""")
            }
        }
        viewModel.selectTable("mileage_entries")
        awaitRequests(2)
        awaitState { !it.isLoadingRows && !it.isLoadingSchema }

        viewModel.selectRow("m-1")
        // Wait for the row to actually be present, not merely for
        // isLoadingRow to be false -- it is false BEFORE selectRow's
        // coroutine sets it, so the weaker predicate returns immediately,
        // leaves selectedRowId null, and submitDelete then early-returns on
        // its own null guard and never clears isSubmittingDelete.
        awaitState { it.selectedRow != null || it.errorMessage != null }
        assertEquals(null, viewModel.uiState.value.errorMessage)

        assertFalse(viewModel.uiState.value.confirmingDelete)

        // The guard under test: submitDelete() before any confirm must not
        // reach the network at all. (AdminDataViewModel.submitDelete had no
        // such guard -- a one-tap delete on a generic editor over every
        // real backend table.)
        val requestsBeforeConfirm = server.requestCount
        viewModel.submitDelete()
        assertEquals(requestsBeforeConfirm, server.requestCount)

        viewModel.requestConfirmDelete()
        assertTrue(viewModel.uiState.value.confirmingDelete)
        assertEquals(requestsBeforeConfirm, server.requestCount)

        viewModel.submitDelete()
        awaitState { !it.isSubmittingDelete }

        assertEquals(null, viewModel.uiState.value.selectedRowId)
    }

    @Test
    fun `requestRevert requires an explicit confirm before reverting`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody(
                    """[{"id":"log-1","admin_id":null,"action":"delete",""" +
                        """"target_table":"mileage_entries","target_id":"m-1",""" +
                        """"before_state":{"id":"m-1"},"after_state":null,""" +
                        """"created_at":"2026-07-01T00:00:00Z"}]""",
                ),
        )
        viewModel.toggleChangeLog()
        awaitState { !it.isLoadingChanges }

        viewModel.requestRevert("log-1")
        assertEquals("log-1", viewModel.uiState.value.confirmingRevertId)

        viewModel.cancelRevert()
        assertEquals(null, viewModel.uiState.value.confirmingRevertId)
    }

    @Test
    fun `loadTables surfaces a network error message`() = runBlocking {
        server.shutdown()

        viewModel.loadTables()
        awaitState { !it.isLoadingTables }

        assertEquals(
            "Could not reach the server. Check your connection.",
            viewModel.uiState.value.errorMessage,
        )
    }
}
