package app.logand.core

import app.logand.core.model.AddMaterialLineRequest
import app.logand.core.model.ConsumeBomRequest
import app.logand.core.model.CreateBomRequest
import app.logand.core.model.InvoiceLineItem
import app.logand.core.model.ManualPaymentRequest
import app.logand.core.model.RefundRequest
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test

// Same real-HTTP-double convention as ApiClientTest -- exercises
// AdminApi's actual request shaping/response decoding against a real
// MockWebServer, not a mocked OkHttpClient. Every fixture shape below
// mirrors the real backend route responses in api/invoices.py,
// api/admin_users.py, api/inventory.py, api/bom.py, api/budget.py,
// api/admin_data.py, api/admin_logs.py, api/admin_version.py.
class AdminApiTest {
    private lateinit var server: MockWebServer
    private lateinit var client: ApiClient
    private lateinit var admin: AdminApi

    @BeforeEach
    fun setUp() {
        server = MockWebServer()
        server.start()
        client = ApiClient(baseUrl = server.url("/").toString())
        admin = client.admin
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
    }

    // -- invoices ------------------------------------------------------------

    @Test
    fun `listInvoices applies status customer and date filters`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        admin.listInvoices(status = "sent", customerId = "c-1", dateFrom = "2026-01-01", dateTo = "2026-12-31")

        val path = server.takeRequest().path!!
        assertTrue(path.startsWith("/api/admin/invoices?"))
        assertTrue(path.contains("status=sent"))
        assertTrue(path.contains("customer_id=c-1"))
        assertTrue(path.contains("date_from=2026-01-01"))
        assertTrue(path.contains("date_to=2026-12-31"))
    }

    @Test
    fun `getInvoiceStats decodes the full stats shape`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"by_status":{"draft":{"count":1,"amount_total":"10.00"}},""" +
                    """"total_collected":"10.00","total_refunded":"0.00",""" +
                    """"net_collected":"10.00","outstanding":"0.00",""" +
                    """"by_payment_method":{"stripe":{"count":1,"amount":"10.00"}},""" +
                    """"open_disputes":0,""" +
                    """"disputes":{"needs_response":0,"under_review":0,"won":0,"lost":0}}"""
            )
        )

        val result = admin.getInvoiceStats()

        assertIs<ApiResult.Success<app.logand.core.model.InvoiceStats>>(result)
        assertEquals("10.00", result.data.total_collected)
        assertEquals(1, result.data.by_status["draft"]!!.count)
    }

    @Test
    fun `getInvoice decodes line items and payments`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"id":"i-1","customer_id":"c-1","status":"sent","amount_total":"20.00",""" +
                    """"currency":"usd","memo":null,"due_date":null,"is_recurring":false,""" +
                    """"paid_at":null,"line_items":[{"id":"li-1","description":"Widget",""" +
                    """"quantity":"1","unit_price":"20.00","unit":null}],"payments":[]}"""
            )
        )

        val result = admin.getInvoice("i-1")

        assertIs<ApiResult.Success<app.logand.core.model.InvoiceDetail>>(result)
        assertEquals(1, result.data.line_items.size)
        assertEquals("/api/admin/invoices/i-1", server.takeRequest().path)
    }

    @Test
    fun `createInvoice sends customer_id and memo as query params and line items as json body`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"i-1"}"""))

        val result = admin.createInvoice(
            customerId = "c-1",
            lineItems = listOf(InvoiceLineItem(description = "Widget", quantity = "1", unit_price = "20.00")),
            memo = "thanks",
        )

        assertIs<ApiResult.Success<app.logand.core.model.CreatedId>>(result)
        val recorded = server.takeRequest()
        assertEquals("POST", recorded.method)
        val path = recorded.path!!
        assertTrue(path.contains("customer_id=c-1"))
        assertTrue(path.contains("memo=thanks"))
        assertTrue(!path.contains("customer_email"))
        assertEquals(
            """[{"description":"Widget","quantity":"1","unit_price":"20.00"}]""",
            recorded.body.readUtf8(),
        )
    }

    @Test
    fun `createInvoice supports customer_email as an alternative to customer_id`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"i-1"}"""))

        admin.createInvoice(
            customerEmail = "contact@example.com",
            lineItems = listOf(InvoiceLineItem(description = "Widget", quantity = "1", unit_price = "20.00")),
        )

        val path = server.takeRequest().path!!
        assertTrue(path.contains("customer_email=contact%40example.com") || path.contains("customer_email=contact@example.com"))
        assertTrue(!path.contains("customer_id="))
    }

    @Test
    fun `sendInvoice and voidInvoice post to the right action paths`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"sent"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"void"}"""))

        assertIs<ApiResult.Success<Unit>>(admin.sendInvoice("i-1"))
        assertEquals("/api/admin/invoices/i-1/send", server.takeRequest().path)

        assertIs<ApiResult.Success<Unit>>(admin.voidInvoice("i-1"))
        assertEquals("/api/admin/invoices/i-1/void", server.takeRequest().path)
    }

    @Test
    fun `recordManualPayment sends method amount and note as a json body`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"p-1"}"""))

        val result = admin.recordManualPayment(
            "i-1",
            ManualPaymentRequest(method = "zelle", amount = "15.00", note = "paid at pickup"),
        )

        assertIs<ApiResult.Success<app.logand.core.model.CreatedId>>(result)
        val recorded = server.takeRequest()
        assertEquals("/api/admin/invoices/i-1/payments/manual", recorded.path)
        assertEquals(
            """{"method":"zelle","amount":"15.00","note":"paid at pickup"}""",
            recorded.body.readUtf8(),
        )
    }

    @Test
    fun `refundPayment sends the refund body to the payment refund path`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"r-1"}"""))

        val result = admin.refundPayment(
            "i-1",
            "p-1",
            RefundRequest(payment_id = "p-1", amount = "5.00", reason = "damaged", idempotency_key = "key-1"),
        )

        assertIs<ApiResult.Success<app.logand.core.model.CreatedId>>(result)
        assertEquals("/api/admin/invoices/i-1/payments/p-1/refund", server.takeRequest().path)
    }

    @Test
    fun `getInvoicePdf returns raw bytes without corrupting binary content`() = runTest {
        val pdfBytes = byteArrayOf(0x25, 0x50, 0x44, 0x46, 0x01, 0x02, 0xFF.toByte())
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                okio.Buffer().write(pdfBytes)
            ).setHeader("Content-Type", "application/pdf")
        )

        val result = admin.getInvoicePdf("i-1")

        assertIs<ApiResult.Success<ByteArray>>(result)
        assertTrue(pdfBytes.contentEquals(result.data))
    }

    @Test
    fun `listPaymentProofs and downloadPaymentProof hit the expected paths`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""[{"id":"pf-1","content_type":"image/png","created_at":"2026-01-01T00:00:00Z"}]""")
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody("binary-ish"))

        val list = admin.listPaymentProofs("i-1")
        assertIs<ApiResult.Success<List<app.logand.core.model.PaymentProofSummary>>>(list)
        assertEquals("/api/admin/invoices/i-1/payment-proof", server.takeRequest().path)

        val file = admin.downloadPaymentProof("i-1", "pf-1")
        assertIs<ApiResult.Success<ByteArray>>(file)
        assertEquals("/api/admin/invoices/i-1/payment-proof/pf-1/file", server.takeRequest().path)
    }

    // -- customers -------------------------------------------------------------

    @Test
    fun `listCustomers applies the q filter`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""[{"id":"c-1","email":"a@example.com"}]"""))

        val result = admin.listCustomers(q = "gmail")

        assertIs<ApiResult.Success<List<app.logand.core.model.CustomerListItem>>>(result)
        assertTrue(server.takeRequest().path!!.contains("q=gmail"))
    }

    @Test
    fun `getCustomer decodes the full customer detail`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"id":"c-1","email":"a@example.com","role":"customer","emails_opted_out":false,""" +
                    """"disabled_at":null,"created_at":"2026-01-01T00:00:00Z"}"""
            )
        )

        val result = admin.getCustomer("c-1")

        assertIs<ApiResult.Success<app.logand.core.model.CustomerDetail>>(result)
        assertEquals("a@example.com", result.data.email)
    }

    @Test
    fun `deactivateCustomer reactivateCustomer and resetCustomerPassword post to their action paths`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"deactivated"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"reactivated"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"reset"}"""))

        assertIs<ApiResult.Success<Unit>>(admin.deactivateCustomer("c-1"))
        assertEquals("/api/admin/customers/c-1/deactivate", server.takeRequest().path)

        assertIs<ApiResult.Success<Unit>>(admin.reactivateCustomer("c-1"))
        assertEquals("/api/admin/customers/c-1/reactivate", server.takeRequest().path)

        assertIs<ApiResult.Success<Unit>>(admin.resetCustomerPassword("c-1", "newpass123"))
        val recorded = server.takeRequest()
        assertEquals("/api/admin/customers/c-1/reset-password", recorded.path)
        assertEquals("""{"new_password":"newpass123"}""", recorded.body.readUtf8())
    }

    // -- inventory ---------------------------------------------------------------

    @Test
    fun `createInventoryLocation and listInventoryLocations round trip`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"loc-1"}"""))
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""[{"id":"loc-1","name":"Shelf A","description":null}]""")
        )

        val created = admin.createInventoryLocation("Shelf A")
        assertIs<ApiResult.Success<app.logand.core.model.CreatedId>>(created)

        val list = admin.listInventoryLocations()
        assertIs<ApiResult.Success<List<app.logand.core.model.InventoryLocation>>>(list)
        assertEquals("Shelf A", list.data[0].name)
    }

    @Test
    fun `createInventoryItem sends repeated tags query params`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"item-1"}"""))

        admin.createInventoryItem(
            name = "Bolt",
            locationId = "loc-1",
            quantity = 10,
            tags = listOf("hardware", "m3"),
        )

        val path = server.takeRequest().path!!
        assertTrue(path.contains("tags=hardware"))
        assertTrue(path.contains("tags=m3"))
    }

    @Test
    fun `updateInventoryItemUnitCost patches the unit-cost path`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"ok"}"""))

        val result = admin.updateInventoryItemUnitCost("item-1", "3.50")

        assertIs<ApiResult.Success<Unit>>(result)
        val recorded = server.takeRequest()
        assertEquals("PATCH", recorded.method)
        assertTrue(recorded.path!!.contains("/api/admin/inventory/items/item-1/unit-cost"))
    }

    @Test
    fun `adjustInventoryQuantity sends delta and reason as a json body`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"adj-1"}"""))

        val result = admin.adjustInventoryQuantity("item-1", delta = -3, reason = "used in build")

        assertIs<ApiResult.Success<app.logand.core.model.CreatedId>>(result)
        val recorded = server.takeRequest()
        assertEquals("""{"delta":-3,"reason":"used in build"}""", recorded.body.readUtf8())
    }

    @Test
    fun `listInventoryAdjustments and searchInventoryItems and deleteInventoryItem hit expected paths`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"deleted"}"""))

        admin.listInventoryAdjustments("item-1")
        assertEquals("/api/admin/inventory/items/item-1/adjustments", server.takeRequest().path)

        admin.searchInventoryItems(q = "bolt", tag = "hardware")
        assertTrue(server.takeRequest().path!!.contains("tag=hardware"))

        assertIs<ApiResult.Success<Unit>>(admin.deleteInventoryItem("item-1"))
        assertEquals("DELETE", server.takeRequest().method)
    }

    // -- bill of materials -------------------------------------------------------

    @Test
    fun `createBom sends its full request body`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"bom-1"}"""))

        val result = admin.createBom(CreateBomRequest(name = "Widget Assembly", labor_hours = "2"))

        assertIs<ApiResult.Success<app.logand.core.model.CreatedId>>(result)
        val recorded = server.takeRequest()
        assertEquals("/api/admin/boms", recorded.path)
        assertTrue(recorded.body.readUtf8().contains("\"name\":\"Widget Assembly\""))
    }

    @Test
    fun `getBomCostBreakdown decodes material lines and totals`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"material_lines":[{"item_id":"item-1","item_name":"Bolt","quantity":4,""" +
                    """"unit_cost":"0.10","line_cost":"0.40"}],"material_cost":"0.40",""" +
                    """"labor_hours":"2","labor_cost":"50.00","overhead_percent":"10",""" +
                    """"overhead_cost":"5.04","total_cost":"55.44"}"""
            )
        )

        val result = admin.getBomCostBreakdown("bom-1", buildQuantity = 1)

        assertIs<ApiResult.Success<app.logand.core.model.BomCostBreakdown>>(result)
        assertEquals(1, result.data.material_lines.size)
        assertEquals("55.44", result.data.total_cost)
    }

    @Test
    fun `consumeBom returns the created adjustment ids`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"adjustment_ids":["adj-1","adj-2"]}"""))

        val result = admin.consumeBom("bom-1", ConsumeBomRequest(build_quantity = 2, reason = "batch build"))

        assertIs<ApiResult.Success<app.logand.core.model.AdjustmentIds>>(result)
        assertEquals(listOf("adj-1", "adj-2"), result.data.adjustment_ids)
    }

    @Test
    fun `addBomMaterialLine and removeBomMaterialLine and deleteBom hit expected paths`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"line-1"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"removed"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"deleted"}"""))

        admin.addBomMaterialLine("bom-1", AddMaterialLineRequest(item_id = "item-1", quantity_per_unit = 2))
        assertEquals("/api/admin/boms/bom-1/lines", server.takeRequest().path)

        assertIs<ApiResult.Success<Unit>>(admin.removeBomMaterialLine("bom-1", "item-1"))
        assertEquals("/api/admin/boms/bom-1/lines/item-1", server.takeRequest().path)

        assertIs<ApiResult.Success<Unit>>(admin.deleteBom("bom-1"))
        assertEquals("DELETE", server.takeRequest().method)
    }

    // -- budget --------------------------------------------------------------

    @Test
    fun `createBudgetEntry sends fields as query params`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"be-1"}"""))

        admin.createBudgetEntry(amount = "25.00", category = "supplies", occurredOn = "2026-06-01", vendor = "Amazon")

        val path = server.takeRequest().path!!
        assertTrue(path.contains("amount=25.00"))
        assertTrue(path.contains("category=supplies"))
        assertTrue(path.contains("vendor=Amazon"))
    }

    @Test
    fun `uploadBudgetEvidence sends a real multipart body`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"be-1"}"""))

        val result = admin.uploadBudgetEvidence(
            entryId = "be-1",
            fileBytes = "fake-pdf-bytes".toByteArray(),
            filename = "receipt.pdf",
            mimeType = "application/pdf",
        )

        assertIs<ApiResult.Success<app.logand.core.model.CreatedId>>(result)
        val recorded = server.takeRequest()
        assertEquals("/api/admin/budget/be-1/evidence", recorded.path)
        assertTrue(recorded.getHeader("Content-Type")!!.startsWith("multipart/form-data"))
    }

    @Test
    fun `listBudgetEntries and exportBudgetCsv hit expected paths`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        server.enqueue(MockResponse().setResponseCode(200).setBody("id,amount\n"))

        admin.listBudgetEntries(category = "supplies")
        assertTrue(server.takeRequest().path!!.contains("category=supplies"))

        val csv = admin.exportBudgetCsv()
        assertIs<ApiResult.Success<ByteArray>>(csv)
        assertEquals("/api/admin/budget/export", server.takeRequest().path)
        assertEquals("id,amount\n", csv.data.decodeToString())
    }

    // -- admin data (raw table browser) ---------------------------------------

    @Test
    fun `listTables getTableSchema and listRows hit expected paths`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""["invoices","users"]"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("""[{"name":"id","type":"uuid"}]"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("""[{"id":"1","email":"a@example.com"}]"""))

        val tables = admin.listTables()
        assertIs<ApiResult.Success<List<String>>>(tables)
        assertEquals(listOf("invoices", "users"), tables.data)
        server.takeRequest()

        admin.getTableSchema("users")
        assertEquals("/api/admin/data/tables/users/schema", server.takeRequest().path)

        val rows = admin.listRows("users", limit = 10, offset = 5)
        assertIs<ApiResult.Success<List<JsonObject>>>(rows)
        assertEquals(JsonPrimitive("a@example.com"), rows.data[0]["email"])
        val path = server.takeRequest().path!!
        assertTrue(path.contains("limit=10"))
        assertTrue(path.contains("offset=5"))
    }

    @Test
    fun `insertRow updateRow deleteRow and revertChange all round trip a change_id`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"change_id":"chg-1"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"change_id":"chg-2"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"change_id":"chg-3"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"change_id":"chg-4"}"""))

        val values = JsonObject(mapOf("email" to JsonPrimitive("new@example.com")))

        val inserted = admin.insertRow("users", values)
        assertIs<ApiResult.Success<app.logand.core.model.ChangeId>>(inserted)
        assertEquals("chg-1", inserted.data.change_id)
        val insertRecorded = server.takeRequest()
        assertEquals("POST", insertRecorded.method)
        assertTrue(insertRecorded.body.readUtf8().contains("new@example.com"))

        val updated = admin.updateRow("users", "1", values)
        assertIs<ApiResult.Success<app.logand.core.model.ChangeId>>(updated)
        assertEquals("PATCH", server.takeRequest().method)

        val deleted = admin.deleteRow("users", "1")
        assertIs<ApiResult.Success<app.logand.core.model.ChangeId>>(deleted)
        assertEquals("DELETE", server.takeRequest().method)

        val reverted = admin.revertChange("chg-1")
        assertIs<ApiResult.Success<app.logand.core.model.ChangeId>>(reverted)
        assertEquals("/api/admin/data/changes/chg-1/revert", server.takeRequest().path)
    }

    @Test
    fun `listChanges applies limit and offset`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        admin.listChanges(limit = 25, offset = 10)

        val path = server.takeRequest().path!!
        assertTrue(path.contains("limit=25"))
        assertTrue(path.contains("offset=10"))
    }

    // -- logs ------------------------------------------------------------------

    @Test
    fun `listLogFiles tailLiveLog and downloadLogFile hit expected paths`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""[{"name":"app.log","size_bytes":100,"modified_at":1700000000.0}]""")
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody("""["line one","line two"]"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("raw-log-bytes"))

        val files = admin.listLogFiles()
        assertIs<ApiResult.Success<List<app.logand.core.model.LogFileInfo>>>(files)
        assertEquals("app.log", files.data[0].name)
        assertEquals("/api/admin/logs/files", server.takeRequest().path)

        val tail = admin.tailLiveLog(lines = 50)
        assertIs<ApiResult.Success<List<String>>>(tail)
        assertEquals(listOf("line one", "line two"), tail.data)
        assertTrue(server.takeRequest().path!!.contains("lines=50"))

        val file = admin.downloadLogFile("app.log")
        assertIs<ApiResult.Success<ByteArray>>(file)
        assertEquals("raw-log-bytes", file.data.decodeToString())
        assertEquals("/api/admin/logs/files/app.log", server.takeRequest().path)
    }

    // -- version -----------------------------------------------------------------

    @Test
    fun `getVersionInfo decodes app and dependency versions`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"app_version":"1.2.3","git_commit":"abc123","python_version":"3.12.0",""" +
                    """"platform":"Linux","dependencies":{"fastapi":"0.110.0"}}"""
            )
        )

        val result = admin.getVersionInfo()

        assertIs<ApiResult.Success<app.logand.core.model.VersionInfo>>(result)
        assertEquals("1.2.3", result.data.app_version)
        assertEquals("0.110.0", result.data.dependencies["fastapi"])
    }

    // -- 401 handling ------------------------------------------------------------

    @Test
    fun `a 401 from an admin endpoint fires onUnauthorized like every other call`() = runTest {
        var fired = false
        val serverForThisTest = MockWebServer().apply { start() }
        val clientWithHook = ApiClient(
            baseUrl = serverForThisTest.url("/").toString(),
            onUnauthorized = { fired = true },
        )
        serverForThisTest.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"session expired"}"""))

        val result = clientWithHook.admin.listInvoices()

        assertIs<ApiResult.HttpError>(result)
        assertTrue(fired)
        serverForThisTest.shutdown()
    }
}
