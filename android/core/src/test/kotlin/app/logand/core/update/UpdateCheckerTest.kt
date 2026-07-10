package app.logand.core.update

import app.logand.core.ApiResult
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test

// Real MockWebServer, not a mocked OkHttpClient -- same convention as
// ApiClientTest: exercises UpdateChecker's actual request/parsing code
// against a real local HTTP server, standing in for the real GitHub
// Releases API (checkForUpdate/downloadApk both take an injectable
// baseUrl/downloadUrl for exactly this reason).
class UpdateCheckerTest {
    private lateinit var server: MockWebServer
    private lateinit var checker: UpdateChecker

    @BeforeEach
    fun setUp() {
        server = MockWebServer()
        server.start()
        checker = UpdateChecker(baseUrl = server.url("/").toString())
    }

    @AfterEach
    fun tearDown() {
        server.shutdown()
    }

    private fun releaseBody(tag: String, assetName: String = "app-release.apk") = """
        {
          "tag_name": "$tag",
          "assets": [
            {"name": "$assetName", "browser_download_url": "https://example.com/$assetName"}
          ]
        }
    """.trimIndent()

    @Test
    fun `reports an update when the latest tag is newer than the running version`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody(releaseBody("v1.2.0")))

        val result = checker.checkForUpdate("1.1.0")

        assertIs<ApiResult.Success<UpdateInfo?>>(result)
        assertEquals("v1.2.0", result.data?.version)
        assertEquals("https://example.com/app-release.apk", result.data?.downloadUrl)
        val recorded = server.takeRequest()
        assertEquals("/releases/latest", recorded.path)
    }

    @Test
    fun `reports no update when the running version is already current`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody(releaseBody("v1.1.0")))

        val result = checker.checkForUpdate("1.1.0")

        assertIs<ApiResult.Success<UpdateInfo?>>(result)
        assertNull(result.data)
    }

    @Test
    fun `reports no update when the running version is newer (v1_10_0 beats v1_9_0)`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody(releaseBody("v1.9.0")))

        val result = checker.checkForUpdate("1.10.0")

        assertIs<ApiResult.Success<UpdateInfo?>>(result)
        assertNull(result.data)
    }

    @Test
    fun `reports no update when the release has no apk asset`() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"tag_name": "v9.0.0", "assets": [{"name": "notes.txt", "browser_download_url": "https://example.com/notes.txt"}]}"""
            )
        )

        val result = checker.checkForUpdate("1.0.0")

        assertIs<ApiResult.Success<UpdateInfo?>>(result)
        assertNull(result.data)
    }

    @Test
    fun `reports no update when the release tag is malformed`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody(releaseBody("not-a-real-tag")))

        val result = checker.checkForUpdate("1.0.0")

        assertIs<ApiResult.Success<UpdateInfo?>>(result)
        assertNull(result.data)
    }

    @Test
    fun `reports no update when the running version string is malformed`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody(releaseBody("v2.0.0")))

        val result = checker.checkForUpdate("not-a-version")

        assertIs<ApiResult.Success<UpdateInfo?>>(result)
        assertNull(result.data)
    }

    @Test
    fun `surfaces a non-2xx response as HttpError`() = runTest {
        server.enqueue(MockResponse().setResponseCode(404).setBody("""{"message":"Not Found"}"""))

        val result = checker.checkForUpdate("1.0.0")

        assertIs<ApiResult.HttpError>(result)
        assertEquals(404, result.statusCode)
    }

    @Test
    fun `surfaces a malformed JSON body as HttpError, not a crash`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("not json at all"))

        val result = checker.checkForUpdate("1.0.0")

        assertIs<ApiResult.HttpError>(result)
    }

    @Test
    fun `network error (server unreachable) surfaces as NetworkError`() = runTest {
        server.shutdown()

        val result = checker.checkForUpdate("1.0.0")

        assertIs<ApiResult.NetworkError>(result)
    }

    @Test
    fun `downloadApk returns the raw response bytes on success`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("fake-apk-bytes"))

        val result = checker.downloadApk(server.url("/app-release.apk").toString())

        assertIs<ApiResult.Success<ByteArray>>(result)
        assertEquals("fake-apk-bytes", result.data.toString(Charsets.UTF_8))
    }

    @Test
    fun `downloadApk surfaces a non-2xx response as HttpError`() = runTest {
        server.enqueue(MockResponse().setResponseCode(500).setBody("server error"))

        val result = checker.downloadApk(server.url("/app-release.apk").toString())

        assertIs<ApiResult.HttpError>(result)
        assertEquals(500, result.statusCode)
    }

    @Test
    fun `downloadApk surfaces a network error`() = runTest {
        server.shutdown()

        val result = checker.downloadApk("http://127.0.0.1:1/app-release.apk")

        assertIs<ApiResult.NetworkError>(result)
    }
}
