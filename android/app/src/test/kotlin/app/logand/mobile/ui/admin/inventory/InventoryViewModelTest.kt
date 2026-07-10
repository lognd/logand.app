package app.logand.mobile.ui.admin.inventory

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
class InventoryViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: InventoryViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = InventoryViewModel({ client })
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (InventoryUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `load populates items and locations from real responses`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"i-1","name":"Bolt","description":null,"quantity":10,""" +
                    """"location_id":"l-1","tags":["hardware"],"unit_cost":"0.25"}]"""
            )
        )
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"l-1","name":"Shelf A","description":null}]"""
            )
        )

        viewModel.load()
        awaitState { !it.isLoading }

        assertEquals(1, viewModel.uiState.value.items.size)
        assertEquals("Bolt", viewModel.uiState.value.items[0].name)
        assertEquals(1, viewModel.uiState.value.locations.size)
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
    fun `createItem without name, location, or valid quantity is rejected before any network call`() =
        runBlocking {
            viewModel.updateCreateForm { it.copy(name = "", locationId = "", quantity = "x") }

            viewModel.createItem()

            assertEquals(
                "Name, location, and a valid quantity are required.",
                viewModel.uiState.value.errorMessage,
            )
            assertEquals(0, server.requestCount)
        }

    @Test
    fun `successful createItem resets the form and reloads`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"i-1"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.updateCreateForm {
            it.copy(name = "Bolt", locationId = "l-1", quantity = "5")
        }
        viewModel.createItem()
        awaitState { !it.isSubmitting }

        assertEquals("", viewModel.uiState.value.createForm.name)
        assertEquals(null, viewModel.uiState.value.errorMessage)
    }

    @Test
    fun `adjustQuantity sends delta and reason then reloads and refetches history`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"adj-1"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.adjustQuantity("i-1", -3, "sold")
        awaitState { !it.isSubmitting }

        val recorded = server.takeRequest()
        val body = recorded.body.readUtf8()
        assertTrue(body.contains("\"delta\":-3"))
        assertTrue(body.contains("\"reason\":\"sold\""))
    }

    @Test
    fun `adjustQuantity surfaces a backend validation error`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(422)
                .setBody("""{"detail":"quantity cannot go below zero"}""")
        )

        viewModel.adjustQuantity("i-1", -100, "oops")
        awaitState { !it.isSubmitting }

        assertEquals("quantity cannot go below zero", viewModel.uiState.value.errorMessage)
    }

    @Test
    fun `loadAdjustments populates history for the requested item`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"a-1","delta":-3,"quantity_before":10,"quantity_after":7,""" +
                    """"reason":"sold","adjusted_by":null,"created_at":"2026-07-01T00:00:00Z"}]"""
            )
        )

        viewModel.loadAdjustments("i-1")
        awaitState { it.adjustmentsByItemId.containsKey("i-1") }

        assertEquals(1, viewModel.uiState.value.adjustmentsByItemId["i-1"]?.size)
    }

    @Test
    fun `deleteItem reloads the list on success`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"deleted"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.deleteItem("i-1")

        val first = server.takeRequest(2, java.util.concurrent.TimeUnit.SECONDS)
        assertEquals("DELETE", first?.method)
    }
}
