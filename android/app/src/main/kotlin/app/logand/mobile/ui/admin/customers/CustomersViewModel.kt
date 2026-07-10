package app.logand.mobile.ui.admin.customers

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.model.CustomerDetail
import app.logand.core.model.CustomerListItem
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class CustomersUiState(
    val query: String = "",
    val customers: List<CustomerListItem> = emptyList(),
    val isLoading: Boolean = false,
    val errorMessage: String? = null,
    // Which customer's detail panel is expanded, mirroring the web app's
    // AdminCustomers selectedId toggle -- lazy loaded on demand.
    val selectedId: String? = null,
    val selectedDetail: CustomerDetail? = null,
    val isDetailLoading: Boolean = false,
    val isActionInProgress: Boolean = false,
)

// Drives the admin Customers screen: search customers by email, expand
// one to see its detail, then deactivate/reactivate the account or reset
// its password -- the mobile mirror of
// frontend/src/app/routes/admin/Customers.tsx. Every account-affecting
// write here is a real, hard-to-casually-undo action (same as the web
// app's own doc comment on CustomerDetailPanel), so the screen requires
// an explicit confirm step before firing.
class CustomersViewModel(private val apiClient: () -> ApiClient) : ViewModel() {
    private val _uiState = MutableStateFlow(CustomersUiState())
    val uiState: StateFlow<CustomersUiState> = _uiState.asStateFlow()

    fun search(query: String) {
        _uiState.update { it.copy(query = query, isLoading = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.listCustomers(query.ifBlank { null })) {
                is ApiResult.Success -> _uiState.update { it.copy(customers = result.data, isLoading = false) }
                is ApiResult.HttpError -> _uiState.update { it.copy(isLoading = false, errorMessage = result.message) }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isLoading = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun load() = search(_uiState.value.query)

    // Toggling the same id again collapses the panel, same convention as
    // InvoicesViewModel.toggleDetail.
    fun toggleDetail(userId: String) {
        if (_uiState.value.selectedId == userId) {
            _uiState.update { it.copy(selectedId = null, selectedDetail = null) }
            return
        }
        _uiState.update { it.copy(
            selectedId = userId,
            selectedDetail = null,
            isDetailLoading = true,
        ) }
        loadDetail(userId)
    }

    private fun loadDetail(userId: String) {
        viewModelScope.launch {
            when (val result = apiClient().admin.getCustomer(userId)) {
                is ApiResult.Success -> _uiState.update { it.copy(selectedDetail = result.data, isDetailLoading = false) }
                is ApiResult.HttpError -> _uiState.update { it.copy(
                    isDetailLoading = false,
                    errorMessage = result.message,
                ) }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isDetailLoading = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun deactivate(userId: String, onDone: (Boolean) -> Unit = {}) {
        _uiState.update { it.copy(isActionInProgress = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.deactivateCustomer(userId)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(isActionInProgress = false) }
                    loadDetail(userId)
                    onDone(true)
                }
                is ApiResult.HttpError -> {
                    _uiState.update { it.copy(
                        isActionInProgress = false,
                        errorMessage = result.message,
                    ) }
                    onDone(false)
                }
                is ApiResult.NetworkError -> {
                    _uiState.update { it.copy(
                        isActionInProgress = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                    onDone(false)
                }
            }
        }
    }

    fun reactivate(userId: String, onDone: (Boolean) -> Unit = {}) {
        _uiState.update { it.copy(isActionInProgress = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.reactivateCustomer(userId)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(isActionInProgress = false) }
                    loadDetail(userId)
                    onDone(true)
                }
                is ApiResult.HttpError -> {
                    _uiState.update { it.copy(
                        isActionInProgress = false,
                        errorMessage = result.message,
                    ) }
                    onDone(false)
                }
                is ApiResult.NetworkError -> {
                    _uiState.update { it.copy(
                        isActionInProgress = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                    onDone(false)
                }
            }
        }
    }

    // Requires the new password already be at least 8 characters --
    // enforced by the UI before this is even called, same rule as the web
    // form's Confirm-reset disabled condition (backend rejects shorter
    // ones anyway; this just avoids a guaranteed-failing round trip).
    fun resetPassword(userId: String, newPassword: String, onDone: (Boolean) -> Unit = {}) {
        if (newPassword.length < 8) {
            _uiState.update { it.copy(
                errorMessage = "New password must be at least 8 characters.",
            ) }
            onDone(false)
            return
        }
        _uiState.update { it.copy(isActionInProgress = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.resetCustomerPassword(userId, newPassword)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(isActionInProgress = false) }
                    onDone(true)
                }
                is ApiResult.HttpError -> {
                    _uiState.update { it.copy(
                        isActionInProgress = false,
                        errorMessage = result.message,
                    ) }
                    onDone(false)
                }
                is ApiResult.NetworkError -> {
                    _uiState.update { it.copy(
                        isActionInProgress = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                    onDone(false)
                }
            }
        }
    }
}
