package app.logand.mobile.ui.admin.stats

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.model.InvoiceStats
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class StatsUiState(
    val stats: InvoiceStats? = null,
    val isLoading: Boolean = false,
    val errorMessage: String? = null,
)

// Drives the read-only admin Stats screen -- the mobile mirror of
// frontend/src/app/routes/admin/Stats.tsx. Everything shown here is
// computed fresh on the server from real rows (domain/invoices/
// stats.py::get_invoice_stats), never cached/denormalized on this side,
// so it can't drift out of sync with what the Invoices screen itself
// shows.
class StatsViewModel(private val apiClient: () -> ApiClient) : ViewModel() {
    private val _uiState = MutableStateFlow(StatsUiState())
    val uiState: StateFlow<StatsUiState> = _uiState.asStateFlow()

    fun load() {
        _uiState.update { it.copy(isLoading = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.getInvoiceStats()) {
                is ApiResult.Success -> _uiState.update { it.copy(stats = result.data, isLoading = false) }
                is ApiResult.HttpError -> _uiState.update { it.copy(isLoading = false, errorMessage = result.message) }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isLoading = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }
}
