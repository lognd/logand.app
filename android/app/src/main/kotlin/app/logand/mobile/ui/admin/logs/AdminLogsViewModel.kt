package app.logand.mobile.ui.admin.logs

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.logging.FileLogger
import app.logand.core.model.LogFileInfo
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

private const val LOG_TAG = "AdminLogsViewModel"
private const val TAIL_LINES = 200
private const val TAIL_REFRESH_INTERVAL_MS = 10_000L

data class AdminLogsUiState(
    val files: List<LogFileInfo> = emptyList(),
    val isLoadingFiles: Boolean = false,
    val tailLines: List<String> = emptyList(),
    val isLoadingTail: Boolean = false,
    val isDownloading: Boolean = false,
    val errorMessage: String? = null,
)

// Read-only server log browser -- mirrors
// frontend/src/app/routes/admin/AdminLogs.tsx: list rotated log files
// with a download action, and auto-refresh a 200-line tail of the live
// log every 10s (same refetchInterval the web app uses). Nothing here
// ever triggers log pruning/rotation -- that stays entirely server-side
// (see logging/retention.py), matching the web app's own doc comment.
class AdminLogsViewModel(
    private val apiClient: () -> ApiClient,
    private val logger: FileLogger? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(AdminLogsUiState())
    val uiState: StateFlow<AdminLogsUiState> = _uiState.asStateFlow()

    private var tailAutoRefreshStarted = false

    fun loadFiles() {
        logger?.info(LOG_TAG, "loading log file list")
        _uiState.update { it.copy(isLoadingFiles = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.listLogFiles()) {
                is ApiResult.Success -> _uiState.update { it.copy(files = result.data, isLoadingFiles = false) }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "listLogFiles failed: ${result.message}")
                    _uiState.update { it.copy(
                        isLoadingFiles = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isLoadingFiles = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun loadTail() {
        _uiState.update { it.copy(isLoadingTail = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.tailLiveLog(lines = TAIL_LINES)) {
                is ApiResult.Success -> _uiState.update { it.copy(tailLines = result.data, isLoadingTail = false) }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "tailLiveLog failed: ${result.message}")
                    _uiState.update { it.copy(
                        isLoadingTail = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isLoadingTail = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    // Starts a 10s poll loop of the live tail, same cadence as the web
    // app's useQuery refetchInterval. Idempotent -- calling it again
    // (e.g. from a recomposed LaunchedEffect) never starts a second
    // concurrent loop.
    fun startTailAutoRefresh() {
        if (tailAutoRefreshStarted) return
        tailAutoRefreshStarted = true
        viewModelScope.launch {
            while (isActive) {
                loadTail()
                delay(TAIL_REFRESH_INTERVAL_MS)
            }
        }
    }

    // Downloads one rotated log file's raw bytes -- onResult receives the
    // bytes on success, or null on failure (errorMessage is also set so
    // the screen doesn't need its own duplicate error text). Writing the
    // bytes to disk/share-sheet is the caller's job (needs a Context this
    // ViewModel deliberately does not hold).
    fun downloadFile(name: String, onResult: (ByteArray?) -> Unit) {
        logger?.info(LOG_TAG, "downloading log file: $name")
        _uiState.update { it.copy(isDownloading = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.downloadLogFile(name)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(isDownloading = false) }
                    onResult(result.data)
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "downloadLogFile($name) failed: ${result.message}")
                    _uiState.update { it.copy(
                        isDownloading = false,
                        errorMessage = result.message,
                    ) }
                    onResult(null)
                }
                is ApiResult.NetworkError -> {
                    _uiState.update { it.copy(
                        isDownloading = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                    onResult(null)
                }
            }
        }
    }
}
