package app.logand.mobile.ui.admin.version

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.logging.FileLogger
import app.logand.core.model.VersionInfo
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

private const val LOG_TAG = "AdminVersionViewModel"

data class AdminVersionUiState(
    val versionInfo: VersionInfo? = null,
    val isLoading: Boolean = false,
    val errorMessage: String? = null,
    val dependencySearch: String = "",
) {
    // The dependencies map can be large (every installed backend
    // package) -- filtered here, live, by name so the screen never
    // needs its own copy of this logic. Case-insensitive substring match
    // against the package name only, not the version string.
    val filteredDependencies: List<Pair<String, String>>
        get() {
            val deps = versionInfo?.dependencies ?: return emptyList()
            val query = dependencySearch.trim()
            val entries = deps.entries.sortedBy { it.key.lowercase() }
            val filtered = if (query.isEmpty()) {
                entries
            } else {
                entries.filter { it.key.contains(query, ignoreCase = true) }
            }
            return filtered.map { it.key to it.value }
        }
}

// Read-only "what version of everything do I have on the server" view --
// mirrors frontend/src/app/routes/admin/AdminVersion.tsx exactly: app
// version, deployed git commit, Python version, platform, and every
// installed dependency's version, all read live from the running
// backend process (see api/admin_version.py) rather than a stale doc.
class AdminVersionViewModel(
    private val apiClient: () -> ApiClient,
    private val logger: FileLogger? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(AdminVersionUiState())
    val uiState: StateFlow<AdminVersionUiState> = _uiState.asStateFlow()

    fun load() {
        logger?.info(LOG_TAG, "loading server version info")
        _uiState.update { it.copy(isLoading = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.getVersionInfo()) {
                is ApiResult.Success -> _uiState.update { it.copy(versionInfo = result.data, isLoading = false) }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "getVersionInfo failed: ${result.message}")
                    _uiState.update { it.copy(
                        isLoading = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isLoading = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun updateDependencySearch(query: String) {
        _uiState.update { it.copy(dependencySearch = query) }
    }
}
