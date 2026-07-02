package app.logand.core

import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test

// Real HTTP server double (MockWebServer), not a mocked OkHttpClient --
// same "real infra over mocks" convention as the backend's fake_stripe.py
// /fake_paypal.py/fake_smtp.py: ApiClient's actual OkHttp client makes
// real HTTP requests against a real local server, over a real socket,
// exercising the real request-shaping and response-parsing code, not
// just "was the right method called."
class ApiClientTest {
    private lateinit var server: MockWebServer
    private lateinit var client: ApiClient

    @BeforeEach
    fun setUp() {
        server = MockWebServer()
        server.start()
        client = ApiClient(baseUrl = server.url("/").toString())
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `login sends email and password as a JSON body`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"ok"}"""))

        val result = client.login("a@example.com", "hunter2")

        assertIs<ApiResult.Success<Unit>>(result)
        val recorded = server.takeRequest()
        assertEquals("POST", recorded.method)
        assertEquals("/api/auth/login", recorded.path)
        assertEquals(
            """{"email":"a@example.com","password":"hunter2"}""",
            recorded.body.readUtf8(),
        )
    }

    @Test
    fun `login surfaces the backend's error detail on 401`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(401).setBody("""{"detail":"email or password is incorrect"}""")
        )

        val result = client.login("a@example.com", "wrong")

        assertIs<ApiResult.HttpError>(result)
        assertEquals(401, result.statusCode)
        assertEquals("email or password is incorrect", result.message)
    }

    @Test
    fun `me decodes user_id and role`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"user_id":"11111111-1111-1111-1111-111111111111","role":"admin"}""")
        )

        val result = client.me()

        assertIs<ApiResult.Success<app.logand.core.model.Me>>(result)
        assertEquals("admin", result.data.role)
    }

    @Test
    fun `mutating requests attach the csrf header from the cookie jar`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .addHeader("Set-Cookie", "csrf_token=real-csrf-value; Path=/")
                .setBody("""{"status":"ok"}""")
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"abc"}"""))

        // First call (login) captures the csrf_token cookie from the
        // response; the SECOND call (a mutating mileage create) must send
        // it back as X-CSRF-Token -- this is exactly the double-submit
        // pattern backend's auth/csrf.py enforces, and the one thing this
        // client cannot get wrong without every mutating request 403ing.
        client.login("a@example.com", "hunter2")
        server.takeRequest()

        val result = client.createMileageEntry(
            vehicle = "Civic",
            occurredOn = "2026-06-01",
            distance = "12.4",
        )

        assertIs<ApiResult.Success<app.logand.core.model.CreatedId>>(result)
        val recorded: RecordedRequest = server.takeRequest()
        assertEquals("real-csrf-value", recorded.getHeader("X-CSRF-Token"))
    }

    @Test
    fun `GET requests never attach a csrf header`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .addHeader("Set-Cookie", "csrf_token=real-csrf-value; Path=/")
                .setBody("""{"status":"ok"}""")
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        client.login("a@example.com", "hunter2")
        server.takeRequest()
        client.listMileage()

        val recorded = server.takeRequest()
        assertEquals(null, recorded.getHeader("X-CSRF-Token"))
    }

    @Test
    fun `createMileageEntry sends distance and business as query params, no body`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"m-1"}"""))

        client.createMileageEntry(
            vehicle = "Civic",
            occurredOn = "2026-06-01",
            distance = "12.4",
            purpose = "client visit",
        )

        val recorded = server.takeRequest()
        assertEquals("POST", recorded.method)
        val path = recorded.path!!
        assertTrue(path.startsWith("/api/admin/mileage?"))
        assertTrue(path.contains("vehicle=Civic"))
        assertTrue(path.contains("distance=12.4"))
        assertTrue(path.contains("business=true"))
        assertEquals("", recorded.body.readUtf8())
    }

    @Test
    fun `createMileageEntry omits start_end odometer params when not supplied`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"m-1"}"""))

        client.createMileageEntry(vehicle = "Civic", occurredOn = "2026-06-01", distance = "1.0")

        val path = server.takeRequest().path!!
        assertTrue(!path.contains("start_odometer"))
        assertTrue(!path.contains("end_odometer"))
    }

    @Test
    fun `create mileage returns HttpError on 422 invalid distance`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(422)
                .setBody("""{"detail":"distance must be a positive value, directly or via odometer readings"}""")
        )

        val result = client.createMileageEntry(vehicle = "Civic", occurredOn = "2026-06-01")

        assertIs<ApiResult.HttpError>(result)
        assertEquals(422, result.statusCode)
    }

    @Test
    fun `deleteMileageEntry issues DELETE to the entry path`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"deleted"}"""))

        val result = client.deleteMileageEntry("m-1")

        assertIs<ApiResult.Success<Unit>>(result)
        val recorded = server.takeRequest()
        assertEquals("DELETE", recorded.method)
        assertEquals("/api/admin/mileage/m-1", recorded.path)
    }

    @Test
    fun `listMileage applies vehicle business and date filters as query params`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        client.listMileage(
            vehicle = "Civic",
            business = false,
            dateFrom = "2026-01-01",
            dateTo = "2026-12-31",
        )

        val path = server.takeRequest().path!!
        assertTrue(path.contains("vehicle=Civic"))
        assertTrue(path.contains("business=false"))
        assertTrue(path.contains("date_from=2026-01-01"))
        assertTrue(path.contains("date_to=2026-12-31"))
    }

    @Test
    fun `listMileage decodes a real response list`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """[{"id":"m-1","vehicle":"Civic","occurred_on":"2026-06-01",""" +
                    """"start_odometer":null,"end_odometer":null,"distance":"12.4",""" +
                    """"purpose":null,"business":true,"memo":null}]"""
            )
        )

        val result = client.listMileage()

        assertIs<ApiResult.Success<List<app.logand.core.model.MileageEntry>>>(result)
        assertEquals(1, result.data.size)
        assertEquals("12.4", result.data[0].distance)
    }

    @Test
    fun `captureReceipt sends a real multipart body with the file`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"id":"r-1"}"""))

        val result = client.captureReceipt(
            fileBytes = "fake-jpeg-bytes".toByteArray(),
            filename = "receipt.jpg",
            mimeType = "image/jpeg",
            vendor = "Home Depot",
        )

        assertIs<ApiResult.Success<app.logand.core.model.CreatedId>>(result)
        val recorded = server.takeRequest()
        assertTrue(recorded.getHeader("Content-Type")!!.startsWith("multipart/form-data"))
        val bodyText = recorded.body.readUtf8()
        assertTrue(bodyText.contains("fake-jpeg-bytes"))
        assertTrue(bodyText.contains("filename=\"receipt.jpg\""))
        assertTrue(recorded.path!!.contains("vendor=Home+Depot") || recorded.path!!.contains("vendor=Home%20Depot"))
    }

    @Test
    fun `listReceipts applies reconciled and category filters`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        client.listReceipts(reconciled = true, category = "supplies")

        val path = server.takeRequest().path!!
        assertTrue(path.contains("reconciled=true"))
        assertTrue(path.contains("category=supplies"))
    }

    @Test
    fun `reconcileReceipt sends budget_entry_id as a query param`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"reconciled"}"""))

        val result = client.reconcileReceipt("r-1", "b-1")

        assertIs<ApiResult.Success<Unit>>(result)
        val recorded = server.takeRequest()
        assertEquals("/api/admin/receipts/r-1/reconcile?budget_entry_id=b-1", recorded.path)
    }

    @Test
    fun `deleteReceipt issues DELETE to the receipt path`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"deleted"}"""))

        val result = client.deleteReceipt("r-1")

        assertIs<ApiResult.Success<Unit>>(result)
        assertEquals("DELETE", server.takeRequest().method)
    }

    @Test
    fun `logout clears local cookies even though the call itself is real`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200)
                .addHeader("Set-Cookie", "csrf_token=real-csrf-value; Path=/")
                .setBody("""{"status":"ok"}""")
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"ok"}"""))
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        client.login("a@example.com", "hunter2")
        server.takeRequest()
        client.logout()
        server.takeRequest()

        // A subsequent mutating call must NOT carry the old csrf cookie --
        // logout() clears the whole cookie jar, not just the session
        // cookie, so a stale csrf token can't leak into a later request.
        client.createMileageEntry(vehicle = "Civic", occurredOn = "2026-06-01", distance = "1.0")
        val recorded = server.takeRequest()
        assertEquals(null, recorded.getHeader("X-CSRF-Token"))
    }

    @Test
    fun `network error (server unreachable) surfaces as NetworkError`() = runTest {
        server.shutdown()

        val result = client.me()

        assertIs<ApiResult.NetworkError>(result)
    }

    @Test
    fun `malformed response body surfaces as HttpError, not a crash`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("not json at all"))

        val result = client.me()

        assertIs<ApiResult.HttpError>(result)
    }
}
