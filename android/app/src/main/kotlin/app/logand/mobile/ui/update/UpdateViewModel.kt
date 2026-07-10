package app.logand.mobile.ui.update

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiResult
import app.logand.core.logging.FileLogger
import app.logand.core.update.UpdateChecker
import app.logand.core.update.UpdateInfo
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

private const val LOG_TAG = "UpdateViewModel"

data class UpdateUiState(
    val checking: Boolean = false,
    // Non-null once a newer release has been found and not yet declined
    // or downloaded -- the Compose banner (see UpdateBanner) is driven
    // directly off this being non-null.
    val available: UpdateInfo? = null,
    val downloading: Boolean = false,
    val errorMessage: String? = null,
)

// Drives the "check GitHub for a newer release, offer to download and
// install it" flow end to end. Deliberately does NOT hold a Context (an
// ApiClient/UpdateChecker is pure networking, no Android dependency) --
// the one step that genuinely needs one (writing the downloaded bytes to
// disk and building the install Intent) is handled by ApkInstaller,
// constructed and owned by the Composable itself (see UpdateBanner),
// same split ReceiptsScreen/ReceiptCaptureController already establish.
class UpdateViewModel(
    private val updateChecker: UpdateChecker,
    private val currentVersion: String,
    private val logger: FileLogger? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(UpdateUiState())
    val uiState: StateFlow<UpdateUiState> = _uiState.asStateFlow()

    fun checkForUpdate() {
        logger?.info(LOG_TAG, "checking for update (running version=$currentVersion)")
        _uiState.value = _uiState.value.copy(checking = true, errorMessage = null)
        viewModelScope.launch {
            when (val result = updateChecker.checkForUpdate(currentVersion)) {
                is ApiResult.Success -> {
                    val update = result.data
                    if (update != null) {
                        logger?.info(LOG_TAG, "update available: ${update.version}")
                    } else {
                        logger?.debug(LOG_TAG, "no update available")
                    }
                    _uiState.value = _uiState.value.copy(checking = false, available = update)
                }
                is ApiResult.HttpError -> fail("update check failed: ${result.message}")
                is ApiResult.NetworkError -> fail("Could not reach GitHub to check for updates.")
            }
        }
    }

    /** User dismissed the available-update banner without installing --
     * cleared, not persisted, so it's offered again next launch/check. */
    fun decline() {
        logger?.info(LOG_TAG, "user declined update ${_uiState.value.available?.version}")
        _uiState.value = _uiState.value.copy(available = null)
    }

    // [onDownloaded] is handed the raw APK bytes plus the release
    // version tag once the download succeeds -- the caller (UpdateBanner)
    // is what actually owns a Context/ApkInstaller, so writing the file
    // and building the install Intent happens there, not here; this
    // ViewModel stays pure network state. Not surfaced through
    // [uiState] as a "ready to install" flag on purpose: that would
    // require the state to be reset again after every install-intent
    // launch to avoid re-firing on a configuration change, which is
    // extra bookkeeping the simple callback avoids entirely.
    fun download(onDownloaded: (bytes: ByteArray, version: String) -> Unit) {
        val update = _uiState.value.available ?: return
        logger?.info(LOG_TAG, "downloading update ${update.version}")
        _uiState.value = _uiState.value.copy(downloading = true, errorMessage = null)
        viewModelScope.launch {
            when (val result = updateChecker.downloadApk(update.downloadUrl)) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "download of ${update.version} complete")
                    _uiState.value = _uiState.value.copy(downloading = false)
                    onDownloaded(result.data, update.version)
                }
                is ApiResult.HttpError -> fail("Download failed: ${result.message}")
                is ApiResult.NetworkError -> fail("Could not download the update. Check your connection.")
            }
        }
    }

    // Always clears BOTH in-flight flags (rather than tracking which
    // call site's operation was in progress) -- checkForUpdate() and
    // download() never run concurrently against the same instance (each
    // is only ever triggered by one user/lifecycle action at a time),
    // so an unconditional reset here is simpler and just as correct.
    private fun fail(message: String) {
        logger?.warn(LOG_TAG, message)
        _uiState.value = _uiState.value.copy(
            checking = false,
            downloading = false,
            errorMessage = message,
        )
    }
}
