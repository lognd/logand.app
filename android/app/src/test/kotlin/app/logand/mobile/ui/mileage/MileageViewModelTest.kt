package app.logand.mobile.ui.mileage

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

// See LoginViewModelTest's doc comment for why real time + polling
// (awaitState), not a virtual-time TestDispatcher, is used here.
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class MileageViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: MileageViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = MileageViewModel { client }
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (MileageUiState) -> Boolean) {
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
                """[{"id":"m-1","vehicle":"Civic","occurred_on":"2026-06-01",""" +
                    """"start_odometer":null,"end_odometer":null,"distance":"12.4",""" +
                    """"purpose":null,"business":true,"memo":null}]"""
            )
        )

        viewModel.load()
        awaitState { !it.isLoading }

        assertEquals(1, viewModel.uiState.value.entries.size)
        assertEquals("12.4", viewModel.uiState.value.entries[0].distance)
    }

    @Test
    fun `load surfaces a network error message`() = runBlocking {
        server.shutdown() // nothing listening

        viewModel.load()
        awaitState { !it.isLoading }

        assertEquals(
            "Could not reach the server. Check your connection.",
            viewModel.uiState.value.errorMessage,
        )
    }

    @Test
    fun `submit without vehicle or date is rejected before any network call`() = runBlocking {
        viewModel.updateForm { it.copy(vehicle = "", occurredOn = "") }

        viewModel.submit()

        assertEquals("Vehicle and date are required.", viewModel.uiState.value.errorMessage)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `successful submit resets the form and reloads the list`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"m-1"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.updateForm {
            it.copy(vehicle = "Civic", occurredOn = "2026-06-01", distance = "12.4")
        }
        viewModel.submit()
        awaitState { !it.isSubmitting }

        assertEquals("", viewModel.uiState.value.form.vehicle)
        assertEquals(null, viewModel.uiState.value.errorMessage)
    }

    @Test
    fun `submit in odometer mode omits the distance param and sends odometer readings`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"m-1"}"""))
            server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

            viewModel.updateForm {
                it.copy(
                    vehicle = "Civic",
                    occurredOn = "2026-06-01",
                    inputMode = DistanceInputMode.ODOMETER_READINGS,
                    startOdometer = "100.0",
                    endOdometer = "142.5",
                )
            }
            viewModel.submit()
            awaitState { !it.isSubmitting }

            val recorded = server.takeRequest()
            val path = recorded.path!!
            assertTrue(path.contains("start_odometer=100.0"))
            assertTrue(path.contains("end_odometer=142.5"))
            assertTrue(!path.contains("distance="))
        }

    @Test
    fun `submit surfaces a 422 backend validation error`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(422)
                .setBody(
                    """{"detail":"distance must be a positive value, directly or via """ +
                        """odometer readings"}"""
                )
        )

        viewModel.updateForm { it.copy(vehicle = "Civic", occurredOn = "2026-06-01") }
        viewModel.submit()
        awaitState { !it.isSubmitting }

        assertEquals(
            "distance must be a positive value, directly or via odometer readings",
            viewModel.uiState.value.errorMessage,
        )
    }

    @Test
    fun `delete reloads the list on success`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"deleted"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.delete("m-1")

        // Not awaitState { it.entries.isEmpty() } -- MileageUiState's
        // initial entries value IS already emptyList(), so that predicate
        // would be satisfied instantly without ever actually waiting for
        // delete()'s two real HTTP requests to complete, defeating the
        // point of the assertion below. Waiting on the requests
        // themselves (with a real timeout) is what actually proves both
        // calls happened.
        val first = server.takeRequest(2, java.util.concurrent.TimeUnit.SECONDS)
        val second = server.takeRequest(2, java.util.concurrent.TimeUnit.SECONDS)

        assertEquals("DELETE", first?.method)
        assertEquals("GET", second?.method)
    }
}
