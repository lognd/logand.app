package app.logand.mobile.ui.receipts

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.model.Receipt
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class ReceiptsUiState(
    val receipts: List<Receipt> = emptyList(),
    val isLoading: Boolean = false,
    val isUploading: Boolean = false,
    val errorMessage: String? = null,
)

class ReceiptsViewModel(private val apiClient: () -> ApiClient) : ViewModel() {
    private val _uiState = MutableStateFlow(ReceiptsUiState())
    val uiState: StateFlow<ReceiptsUiState> = _uiState.asStateFlow()

    fun load() {
        _uiState.value = _uiState.value.copy(isLoading = true, errorMessage = null)
        viewModelScope.launch {
            when (val result = apiClient().listReceipts()) {
                is ApiResult.Success -> _uiState.value =
                    _uiState.value.copy(receipts = result.data, isLoading = false)
                is ApiResult.HttpError -> _uiState.value =
                    _uiState.value.copy(isLoading = false, errorMessage = result.message)
                is ApiResult.NetworkError -> _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                )
            }
        }
    }

    // Only fileBytes/filename/mimeType are required -- everything else
    // is optional, mirroring api/receipts.py's own "the ONLY required
    // input is the photo" design (see docs/design/14-mileage-receipts-documents.md).
    fun capture(
        fileBytes: ByteArray,
        filename: String,
        mimeType: String,
        vendor: String? = null,
        amount: String? = null,
        category: String? = null,
        note: String? = null,
        onDone: (Boolean) -> Unit = {},
    ) {
        _uiState.value = _uiState.value.copy(isUploading = true, errorMessage = null)
        viewModelScope.launch {
            val result = apiClient().captureReceipt(
                fileBytes = fileBytes,
                filename = filename,
                mimeType = mimeType,
                vendor = vendor?.ifBlank { null },
                amount = amount?.ifBlank { null },
                category = category?.ifBlank { null },
                note = note?.ifBlank { null },
            )
            when (result) {
                is ApiResult.Success -> {
                    _uiState.value = _uiState.value.copy(isUploading = false)
                    load()
                    onDone(true)
                }
                is ApiResult.HttpError -> {
                    _uiState.value = _uiState.value.copy(
                        isUploading = false,
                        errorMessage = result.message,
                    )
                    onDone(false)
                }
                is ApiResult.NetworkError -> {
                    _uiState.value = _uiState.value.copy(
                        isUploading = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    )
                    onDone(false)
                }
            }
        }
    }

    fun delete(id: String) {
        viewModelScope.launch {
            when (val result = apiClient().deleteReceipt(id)) {
                is ApiResult.Success -> load()
                is ApiResult.HttpError -> _uiState.value =
                    _uiState.value.copy(errorMessage = result.message)
                is ApiResult.NetworkError -> _uiState.value = _uiState.value.copy(
                    errorMessage = "Could not reach the server. Check your connection.",
                )
            }
        }
    }
}
