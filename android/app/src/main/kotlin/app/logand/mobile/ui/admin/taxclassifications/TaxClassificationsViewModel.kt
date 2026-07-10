package app.logand.mobile.ui.admin.taxclassifications

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.logging.FileLogger
import app.logand.core.model.TaxClassification
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val LOG_TAG = "TaxClassificationsViewModel"

// Staged edits for the override form on one row -- mirrors the web app's
// TaxClassifications.tsx::OverrideForm local state.
data class OverrideFormState(
    val category: String = "",
    val taxable: Boolean = true,
    val htsCode: String = "",
)

data class TaxClassificationsUiState(
    val classifications: List<TaxClassification> = emptyList(),
    // "pending" or "all" -- matches the web page's own filter values.
    val statusFilter: String = "pending",
    val isLoading: Boolean = false,
    val errorMessage: String? = null,

    // Confirming a classification as-is is still a financial-record
    // change, so it goes through the same arm-then-submit two-step as
    // AdminDataViewModel's row update/delete -- never a single tap.
    val confirmingKey: String? = null,
    val isSubmittingConfirm: Boolean = false,

    // Which row's override form is open, and its staged edits.
    val overridingKey: String? = null,
    val overrideForm: OverrideFormState = OverrideFormState(),
    // Second confirm step before the override write itself fires.
    val confirmingOverride: Boolean = false,
    val isSubmittingOverride: Boolean = false,
)

// Drives the admin review queue for the do-as-we-go item tax classifier
// -- the mobile mirror of
// frontend/src/app/routes/admin/TaxClassifications.tsx. Every new
// normalized item key the tax engine has never seen gets an automatic
// guess (category/taxable/hts_code) that sits "pending" until an admin
// confirms it as-is or overrides it (see docs/design/16-sales-tax.md).
// Both actions change financial records, so both require an explicit
// confirm step here -- never a one-tap write.
class TaxClassificationsViewModel(
    private val apiClient: () -> ApiClient,
    private val logger: FileLogger? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(TaxClassificationsUiState())
    val uiState: StateFlow<TaxClassificationsUiState> = _uiState.asStateFlow()

    fun load() {
        val statusFilter = _uiState.value.statusFilter
        logger?.debug(LOG_TAG, "loading tax classifications filter=$statusFilter")
        _uiState.update { it.copy(isLoading = true, errorMessage = null) }
        viewModelScope.launch {
            val status = if (statusFilter == "pending") "pending" else null
            when (val result = apiClient().admin.listTaxClassifications(status)) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "loaded ${result.data.size} classifications")
                    _uiState.update { it.copy(classifications = result.data, isLoading = false) }
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "load failed: ${result.message}")
                    _uiState.update { it.copy(isLoading = false, errorMessage = result.message) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "load network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isLoading = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    fun setStatusFilter(filter: String) {
        if (_uiState.value.statusFilter == filter) return
        logger?.info(LOG_TAG, "status filter changed to $filter")
        _uiState.update { it.copy(statusFilter = filter) }
        load()
    }

    // Step 1 of 2 for confirming a classification as-is -- arms the
    // confirmation UI, does not write anything yet.
    fun requestConfirm(key: String) {
        _uiState.update { it.copy(confirmingKey = key) }
    }

    fun cancelConfirm() {
        _uiState.update { it.copy(confirmingKey = null) }
    }

    fun submitConfirm(key: String) {
        if (_uiState.value.confirmingKey != key) return
        logger?.info(LOG_TAG, "confirming classification key=$key")
        _uiState.update { it.copy(isSubmittingConfirm = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.confirmTaxClassification(key)) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "classification confirmed key=$key")
                    _uiState.update { it.copy(
                        isSubmittingConfirm = false,
                        confirmingKey = null,
                    ) }
                    load()
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "confirmTaxClassification($key) failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmittingConfirm = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "confirmTaxClassification($key) network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isSubmittingConfirm = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    fun openOverrideForm(classification: TaxClassification) {
        logger?.info(LOG_TAG, "opening override form key=${classification.normalized_key}")
        _uiState.update { it.copy(
            overridingKey = classification.normalized_key,
            overrideForm = OverrideFormState(
                category = classification.category,
                taxable = classification.taxable,
                htsCode = classification.hts_code ?: "",
            ),
            confirmingOverride = false,
        ) }
    }

    fun cancelOverrideForm() {
        _uiState.update { it.copy(
            overridingKey = null,
            overrideForm = OverrideFormState(),
            confirmingOverride = false,
        ) }
    }

    fun updateOverrideForm(transform: (OverrideFormState) -> OverrideFormState) {
        _uiState.update { it.copy(overrideForm = transform(it.overrideForm)) }
    }

    // Step 1 of 2 for the override write -- arms the confirmation UI.
    // Rejected up front (before ever arming) if category is blank.
    fun requestConfirmOverride() {
        if (_uiState.value.overrideForm.category.isBlank()) {
            logger?.warn(LOG_TAG, "requestConfirmOverride rejected: blank category")
            _uiState.update { it.copy(errorMessage = "Category is required.") }
            return
        }
        _uiState.update { it.copy(confirmingOverride = true) }
    }

    fun cancelConfirmOverride() {
        _uiState.update { it.copy(confirmingOverride = false) }
    }

    fun submitOverride() {
        val state = _uiState.value
        val key = state.overridingKey ?: return
        if (!state.confirmingOverride) return
        val form = state.overrideForm
        logger?.info(LOG_TAG, "submitting override key=$key category=${form.category}")
        _uiState.update { it.copy(isSubmittingOverride = true, errorMessage = null) }
        viewModelScope.launch {
            val result = apiClient().admin.overrideTaxClassification(
                key = key,
                category = form.category.trim(),
                taxable = form.taxable,
                htsCode = form.htsCode.ifBlank { null },
            )
            when (result) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "override saved key=$key")
                    _uiState.update { it.copy(
                        isSubmittingOverride = false,
                        overridingKey = null,
                        overrideForm = OverrideFormState(),
                        confirmingOverride = false,
                    ) }
                    load()
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "overrideTaxClassification($key) failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmittingOverride = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "overrideTaxClassification($key) network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isSubmittingOverride = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }
}
