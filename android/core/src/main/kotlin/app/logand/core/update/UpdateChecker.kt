package app.logand.core.update

import app.logand.core.ApiResult
import app.logand.core.logging.FileLogger
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request

private const val APK_ASSET_SUFFIX = ".apk"
private const val LOG_TAG = "UpdateChecker"

// Queries the PUBLIC GitHub Releases API for this repo's latest tagged
// release -- deliberately NOT the backend's /api/admin/version, which
// is admin-session-gated (see api/admin.py) and therefore useless for
// an unauthenticated pre-login update check. Lives in :core, same as
// ApiClient, so it's pure networking/parsing and testable against a
// real local HTTP server (MockWebServer) rather than a mocked
// OkHttpClient -- matches ApiClientTest's own "real infra over mocks"
// convention. baseUrl is injectable for exactly that reason: tests
// point it at a MockWebServer instance instead of the real GitHub host.
class UpdateChecker(
    baseUrl: String = DEFAULT_BASE_URL,
    private val httpClient: OkHttpClient = OkHttpClient(),
    private val logger: FileLogger? = null,
) {
    companion object {
        const val DEFAULT_BASE_URL = "https://api.github.com/repos/lognd/logand.app"
    }

    private val baseUrl = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true }

    // Compares the latest GitHub release's tag against [currentVersion]
    // (the running app's own BuildConfig.VERSION_NAME). Returns
    // Success(null) -- not an error -- for every case where there's
    // nothing safe to offer: no release found, no .apk asset attached,
    // a malformed tag on either side, or the running version is already
    // current/newer. Only a real transport/HTTP failure surfaces as
    // HttpError/NetworkError.
    suspend fun checkForUpdate(currentVersion: String): ApiResult<UpdateInfo?> =
        withContext(Dispatchers.IO) {
            logger?.debug(LOG_TAG, "checking for update, running version=$currentVersion")
            val request = Request.Builder().url("$baseUrl/releases/latest").build()
            try {
                httpClient.newCall(request).execute().use { response ->
                    val bodyText = response.body?.string().orEmpty()
                    if (response.code !in 200..299) {
                        logger?.warn(LOG_TAG, "update check got HTTP ${response.code}")
                        return@withContext ApiResult.HttpError(response.code, bodyText)
                    }
                    val release = try {
                        json.decodeFromString(GithubRelease.serializer(), bodyText)
                    } catch (e: SerializationException) {
                        logger?.error(LOG_TAG, "malformed release response", e)
                        return@withContext ApiResult.HttpError(
                            response.code,
                            "malformed release response: ${e.message}",
                        )
                    }
                    ApiResult.Success(resolveUpdate(release, currentVersion))
                }
            } catch (e: IOException) {
                logger?.error(LOG_TAG, "update check failed", e)
                ApiResult.NetworkError(e)
            }
        }

    // Downloads the raw APK bytes for [downloadUrl] -- kept as pure
    // networking here (returns ByteArray, no file I/O) so it's testable
    // the same MockWebServer way as everything else in :core; :app's
    // ApkInstaller is the one that ever touches disk/FileProvider/Intents.
    suspend fun downloadApk(downloadUrl: String): ApiResult<ByteArray> =
        withContext(Dispatchers.IO) {
            logger?.info(LOG_TAG, "downloading update apk from $downloadUrl")
            val request = Request.Builder().url(downloadUrl).build()
            try {
                httpClient.newCall(request).execute().use { response ->
                    if (response.code !in 200..299) {
                        logger?.warn(LOG_TAG, "apk download got HTTP ${response.code}")
                        return@withContext ApiResult.HttpError(response.code, "download failed")
                    }
                    val bytes = response.body?.bytes() ?: ByteArray(0)
                    logger?.info(LOG_TAG, "downloaded ${bytes.size} bytes")
                    ApiResult.Success(bytes)
                }
            } catch (e: IOException) {
                logger?.error(LOG_TAG, "apk download failed", e)
                ApiResult.NetworkError(e)
            }
        }

    private fun resolveUpdate(release: GithubRelease, currentVersion: String): UpdateInfo? {
        val asset = release.assets.firstOrNull { it.name.endsWith(APK_ASSET_SUFFIX) }
        if (asset == null) {
            logger?.debug(LOG_TAG, "latest release ${release.tag_name} has no .apk asset")
            return null
        }
        val latest = parseSemVer(release.tag_name)
        if (latest == null) {
            logger?.warn(LOG_TAG, "could not parse release tag as semver: ${release.tag_name}")
            return null
        }
        val running = parseSemVer(currentVersion)
        if (running == null) {
            logger?.warn(LOG_TAG, "could not parse running version as semver: $currentVersion")
            return null
        }
        if (latest <= running) {
            logger?.debug(LOG_TAG, "already up to date (running=$running, latest=$latest)")
            return null
        }
        logger?.info(LOG_TAG, "update available: $running -> $latest")
        return UpdateInfo(version = release.tag_name, downloadUrl = asset.browser_download_url)
    }
}
