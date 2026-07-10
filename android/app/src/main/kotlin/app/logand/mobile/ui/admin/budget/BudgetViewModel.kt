package app.logand.mobile.ui.admin.budget

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.logging.FileLogger
import app.logand.core.model.BudgetEntry
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

private const val LOG_TAG = "BudgetViewModel"

data class BudgetCreateFormState(
    val amount: String = "",
    val category: String = "",
    val occurredOn: String = "",
)

data class BudgetUiState(
    val entries: List<BudgetEntry> = emptyList(),
    val isLoading: Boolean = false,
    val isSubmitting: Boolean = false,
    // Which single entry's evidence upload is in flight, mirroring
    // AdminBudget.tsx's uploadingEntryId -- only that one row shows a
    // pending state, not the whole page.
    val uploadingEntryId: String? = null,
    val isExporting: Boolean = false,
    val errorMessage: String? = null,
    val createForm: BudgetCreateFormState = BudgetCreateFormState(),
)

// Drives the admin Budget screen: list entries, create an entry, attach
// evidence (PDF/PNG/JPEG, multipart) to an entry, and export the
// currently-listed range as CSV -- same surface as Budget.tsx's
// AdminBudget plus the CSV export AdminApi exposes but the web page
// doesn't currently wire up (see AdminApi.exportBudgetCsv's doc comment).
class BudgetViewModel(
    private val apiClient: () -> ApiClient,
    private val logger: FileLogger? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(BudgetUiState())
    val uiState: StateFlow<BudgetUiState> = _uiState.asStateFlow()

    fun load() {
        logger?.debug(LOG_TAG, "loading budget entries")
        _uiState.update { it.copy(isLoading = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.listBudgetEntries()) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "loaded ${result.data.size} budget entries")
                    _uiState.update { it.copy(entries = result.data, isLoading = false) }
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "load failed: ${result.message}")
                    _uiState.update { it.copy(isLoading = false, errorMessage = result.message) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "load network error")
                    _uiState.update { it.copy(
                        isLoading = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    fun updateCreateForm(transform: (BudgetCreateFormState) -> BudgetCreateFormState) {
        _uiState.update { it.copy(createForm = transform(it.createForm)) }
    }

    fun createEntry() {
        val form = _uiState.value.createForm
        if (form.amount.isBlank() || form.category.isBlank() || form.occurredOn.isBlank()) {
            logger?.warn(LOG_TAG, "createEntry rejected: missing required field")
            _uiState.update { it.copy(
                errorMessage = "Amount, category, and date are required.",
            ) }
            return
        }
        logger?.info(LOG_TAG, "creating budget entry category=${form.category} amount=${form.amount}")
        _uiState.update { it.copy(isSubmitting = true, errorMessage = null) }
        viewModelScope.launch {
            val result = apiClient().admin.createBudgetEntry(
                amount = form.amount.trim(),
                category = form.category.trim(),
                occurredOn = form.occurredOn.trim(),
            )
            when (result) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "budget entry created id=${result.data.id}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        createForm = BudgetCreateFormState(),
                    ) }
                    load()
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "createEntry failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "createEntry network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    // Evidence file must be application/pdf, image/png, or image/jpeg --
    // enforced server-side (see AdminApi.uploadBudgetEvidence's own doc
    // comment); this just passes mimeType through, same as the web form's
    // accept attribute is advisory only.
    fun uploadEvidence(entryId: String, fileBytes: ByteArray, filename: String, mimeType: String) {
        logger?.info(LOG_TAG, "uploading evidence entry=$entryId filename=$filename mimeType=$mimeType")
        _uiState.update { it.copy(uploadingEntryId = entryId, errorMessage = null) }
        viewModelScope.launch {
            val result = apiClient().admin.uploadBudgetEvidence(entryId, fileBytes, filename, mimeType)
            when (result) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "evidence uploaded entry=$entryId proofId=${result.data.id}")
                    _uiState.update { it.copy(uploadingEntryId = null) }
                    load()
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "uploadEvidence failed: ${result.message}")
                    _uiState.update { it.copy(
                        uploadingEntryId = null,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "uploadEvidence network error: ${result.cause}")
                    _uiState.update { it.copy(
                        uploadingEntryId = null,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    // Hands the raw CSV bytes to [onExported] (e.g. write to a file and
    // launch a share sheet) -- this ViewModel stays pure network state,
    // same split ReceiptsViewModel/ReceiptCaptureController establish for
    // file handling.
    fun exportCsv(onExported: (ByteArray) -> Unit) {
        logger?.info(LOG_TAG, "exporting budget CSV")
        _uiState.update { it.copy(isExporting = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.exportBudgetCsv()) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "budget CSV export complete, ${result.data.size} bytes")
                    _uiState.update { it.copy(isExporting = false) }
                    onExported(result.data)
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "exportCsv failed: ${result.message}")
                    _uiState.update { it.copy(
                        isExporting = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "exportCsv network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isExporting = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }
}
