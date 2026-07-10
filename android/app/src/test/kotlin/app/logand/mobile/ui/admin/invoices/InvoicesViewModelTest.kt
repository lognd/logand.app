package app.logand.mobile.ui.admin.invoices

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

// Same real-time-plus-polling convention as MileageViewModelTest -- see
// that test's own doc comment for why no virtual-time TestDispatcher.
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class InvoicesViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var viewModel: InvoicesViewModel

    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        val client = ApiClient(baseUrl = server.url("/").toString())
        viewModel = InvoicesViewModel { client }
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private suspend fun awaitState(predicate: (InvoicesUiState) -> Boolean) {
        withTimeout(2_000) {
            while (!predicate(viewModel.uiState.value)) {
                delay(5)
            }
        }
    }

    @Test
    fun `load populates invoices from a real response`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"inv-1","customer_id":"cust-1","status":"draft",""" +
                    """"amount_total":"100.00","currency":"usd","memo":null,""" +
                    """"due_date":null,"is_recurring":false,"paid_at":null}]"""
            )
        )

        viewModel.load()
        awaitState { !it.isLoading }

        assertEquals(1, viewModel.uiState.value.invoices.size)
        assertEquals("inv-1", viewModel.uiState.value.invoices[0].id)
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
    fun `createInvoice without recipient or line items is rejected before any network call`() =
        runBlocking {
            viewModel.createInvoice()

            assertEquals(
                "Pick a customer (or enter an email) and at least one line item.",
                viewModel.uiState.value.errorMessage,
            )
            assertEquals(0, server.requestCount)
        }

    @Test
    fun `createInvoice via existing customer sends customer_id not customer_email`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"inv-1"}"""))
            server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

            viewModel.updateCreateForm {
                it.copy(recipientMode = InvoiceRecipientMode.EXISTING_CUSTOMER, customerId = "cust-1")
            }
            viewModel.updateLineItem(0) {
                it.copy(description = "Widget", unitPrice = "9.99")
            }
            viewModel.createInvoice()
            awaitState { !it.isSubmitting }

            val recorded = server.takeRequest()
            assertTrue(recorded.path!!.contains("customer_id=cust-1"))
            assertTrue(!recorded.path!!.contains("customer_email"))
        }

    @Test
    fun `createInvoice via bare email sends customer_email not customer_id`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"inv-1"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.updateCreateForm {
            it.copy(recipientMode = InvoiceRecipientMode.BARE_EMAIL, customerEmail = "new@example.com")
        }
        viewModel.updateLineItem(0) {
            it.copy(description = "Widget", unitPrice = "9.99")
        }
        viewModel.createInvoice()
        awaitState { !it.isSubmitting }

        val recorded = server.takeRequest()
        assertTrue(recorded.path!!.contains("customer_email=new"))
        assertTrue(!recorded.path!!.contains("customer_id="))
    }

    @Test
    fun `sendInvoice reloads the list on success`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"ok"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.sendInvoice("inv-1")

        val first = server.takeRequest(2, java.util.concurrent.TimeUnit.SECONDS)
        val second = server.takeRequest(2, java.util.concurrent.TimeUnit.SECONDS)
        assertEquals("POST", first?.method)
        assertEquals("GET", second?.method)
    }

    @Test
    fun `recordManualPayment surfaces a backend validation error`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(422).setBody("""{"detail":"amount must be positive"}"""),
        )

        viewModel.recordManualPayment("inv-1", "zelle", "-5", null)
        awaitState { !it.isSubmitting }

        assertEquals("amount must be positive", viewModel.uiState.value.errorMessage)
    }

    @Test
    fun `downloadInvoicePdf delivers bytes to the callback on success`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("pdf bytes")
                .setHeader("Content-Type", "application/pdf"),
        )

        var received: ByteArray? = null
        viewModel.downloadInvoicePdf("inv-1") { received = it }
        awaitState { it.downloadingPdfInvoiceId == null }

        assertEquals("pdf bytes", received?.toString(Charsets.UTF_8))
    }

    @Test
    fun `downloadInvoicePdf surfaces an http error and calls back with null`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(404).setBody("""{"detail":"not found"}"""))

        var received: ByteArray? = "sentinel".toByteArray()
        viewModel.downloadInvoicePdf("missing-inv") { received = it }
        awaitState { it.downloadingPdfInvoiceId == null }

        assertEquals(null, received)
        assertEquals("not found", viewModel.uiState.value.errorMessage)
    }

    @Test
    fun `downloadPaymentProof delivers bytes to the callback on success`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("proof bytes")
                .setHeader("Content-Type", "image/png"),
        )

        var received: ByteArray? = null
        viewModel.downloadPaymentProof("inv-1", "proof-1") { received = it }
        awaitState { it.downloadingProofId == null }

        assertEquals("proof bytes", received?.toString(Charsets.UTF_8))
    }

    @Test
    fun `downloadPaymentProof surfaces a network error and calls back with null`() = runBlocking {
        server.shutdown()

        var received: ByteArray? = "sentinel".toByteArray()
        viewModel.downloadPaymentProof("inv-1", "proof-1") { received = it }
        awaitState { it.downloadingProofId == null }

        assertEquals(null, received)
        assertEquals(
            "Could not reach the server. Check your connection.",
            viewModel.uiState.value.errorMessage,
        )
    }

    @Test
    fun `loadBoms populates boms from a real response`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"bom-1","name":"Widget kit","description":null,""" +
                    """"labor_hours":"2","labor_rate":"50.00","overhead_percent":"10"}]""",
            ),
        )

        viewModel.loadBoms()
        awaitState { !it.isBomsLoading }

        assertEquals(1, viewModel.uiState.value.boms.size)
        assertEquals("bom-1", viewModel.uiState.value.boms[0].id)
    }

    @Test
    fun `loadBoms does not re-fetch once boms are already loaded`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        viewModel.loadBoms()
        awaitState { !it.isBomsLoading }
        viewModel.loadBoms()

        assertEquals(1, server.requestCount)
    }

    @Test
    fun `importBomAsLineItems maps material, labor, and overhead lines exactly like the web form`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """[{"id":"bom-1","name":"Widget kit","description":null,""" +
                        """"labor_hours":"2","labor_rate":"50.00","overhead_percent":"10"}]""",
                ),
            )
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """{"material_lines":[{"item_id":"item-1","item_name":"Resistor",""" +
                        """"quantity":12,"unit_cost":"0.10","line_cost":"1.20"}],""" +
                        """"material_cost":"1.20","labor_hours":"2","labor_cost":"100.00",""" +
                        """"overhead_percent":"10","overhead_cost":"10.12","total_cost":"111.32"}""",
                ),
            )

            viewModel.loadBoms()
            awaitState { !it.isBomsLoading }
            viewModel.updateCreateForm { it.copy(importBomId = "bom-1", importBuildQuantity = "1") }
            viewModel.importBomAsLineItems()
            awaitState { !it.isImportingBom }

            val lineItems = viewModel.uiState.value.createForm.lineItems
            assertEquals(3, lineItems.size)
            assertEquals("Resistor", lineItems[0].description)
            assertEquals("12", lineItems[0].quantity)
            assertEquals("0.10", lineItems[0].unitPrice)
            assertEquals("ea", lineItems[0].unit)
            assertEquals("Labor (Widget kit)", lineItems[1].description)
            assertEquals("2", lineItems[1].quantity)
            assertEquals("50.00", lineItems[1].unitPrice)
            assertEquals("hr", lineItems[1].unit)
            assertEquals("Overhead (10%)", lineItems[2].description)
            assertEquals("1", lineItems[2].quantity)
            assertEquals("10.12", lineItems[2].unitPrice)
        }

    @Test
    fun `importBomAsLineItems surfaces a bom-specific import error on http failure`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(422).setBody("""{"detail":"bad request"}"""))

        viewModel.updateCreateForm { it.copy(importBomId = "bom-1") }
        viewModel.importBomAsLineItems()
        awaitState { !it.isImportingBom }

        assertTrue(
            viewModel.uiState.value.bomImportError!!.contains("every material line needs"),
        )
    }
}
