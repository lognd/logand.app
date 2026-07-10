package app.logand.mobile.ui.admin.bom

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
class BomViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: BomViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = BomViewModel({ client })
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (BomUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `load populates boms from a real response`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"b-1","name":"Widget","description":null,"labor_hours":"1",""" +
                    """"labor_rate":"20","overhead_percent":"10"}]"""
            )
        )

        viewModel.load()
        awaitState { !it.isLoading }

        assertEquals(1, viewModel.uiState.value.boms.size)
        assertEquals("Widget", viewModel.uiState.value.boms[0].name)
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
    fun `createBom without a name is rejected before any network call`() = runBlocking {
        viewModel.updateCreateForm { it.copy(name = "") }

        viewModel.createBom()

        assertEquals("Name is required.", viewModel.uiState.value.errorMessage)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `successful createBom resets the form and reloads`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"b-1"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.updateCreateForm { it.copy(name = "Widget") }
        viewModel.createBom()
        awaitState { !it.isSubmitting }

        assertEquals("", viewModel.uiState.value.createForm.name)
        assertEquals(null, viewModel.uiState.value.errorMessage)
    }

    @Test
    fun `loadCostBreakdown clamps build quantity below one to one`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"material_lines":[],"material_cost":"0","labor_hours":"0",""" +
                    """"labor_cost":"0","overhead_percent":"0","overhead_cost":"0","total_cost":"0"}"""
            )
        )

        viewModel.loadCostBreakdown("b-1", 0)
        awaitState { it.costBreakdownsByBomId.containsKey("b-1") }

        val recorded = server.takeRequest()
        assertTrue(recorded.path!!.contains("build_quantity=1"))
    }

    @Test
    fun `consumeBom surfaces a backend error and does not clear submitting incorrectly`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(422)
                    .setBody("""{"detail":"not enough stock for item Bolt"}""")
            )

            viewModel.consumeBom("b-1", 2, "build run")
            awaitState { !it.isSubmitting }

            assertEquals("not enough stock for item Bolt", viewModel.uiState.value.errorMessage)
        }

    @Test
    fun `successful consumeBom reloads the cost breakdown for the same bom`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"adjustment_ids":["a-1"]}"""))
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"material_lines":[],"material_cost":"0","labor_hours":"0",""" +
                    """"labor_cost":"0","overhead_percent":"0","overhead_cost":"0","total_cost":"0"}"""
            )
        )

        var done: Boolean? = null
        viewModel.consumeBom("b-1", 2, null) { done = it }
        // isSubmitting flips back to false as soon as the consume call
        // itself succeeds, before the follow-up loadCostBreakdown() call
        // (launched separately, on Dispatchers.IO) has necessarily
        // completed -- so wait on the breakdown map directly rather than
        // racing it against isSubmitting.
        awaitState { it.costBreakdownsByBomId.containsKey("b-1") }

        assertEquals(true, done)
        assertTrue(viewModel.uiState.value.costBreakdownsByBomId.containsKey("b-1"))
    }
}
