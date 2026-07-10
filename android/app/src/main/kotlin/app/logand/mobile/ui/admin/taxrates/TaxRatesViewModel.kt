package app.logand.mobile.ui.admin.taxrates

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.logging.FileLogger
import app.logand.core.model.TaxRule
import app.logand.core.model.TaxRuleCreateRequest
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val LOG_TAG = "TaxRatesViewModel"

// Rate is staged as a whole-number percent string ("7" -> "0.07" sent to
// the backend) -- easier for an admin to type/check against a state's
// published rate sheet than a bare fraction, same convention as the web
// app's TaxRates.tsx::AddRuleForm.
data class TaxRuleFormState(
    val jurisdiction: String = "",
    val taxType: String = "sales",
    val category: String = "*",
    val percent: String = "",
    val source: String = "",
    val citationUrl: String = "",
)

data class TaxRatesUiState(
    val rules: List<TaxRule> = emptyList(),
    val isLoading: Boolean = false,
    val isSubmitting: Boolean = false,
    val errorMessage: String? = null,
    val form: TaxRuleFormState = TaxRuleFormState(),
)

// Drives the admin Tax rates screen: the tax_rules knowledge base
// (docs/design/16-sales-tax.md) -- the mobile mirror of
// frontend/src/app/routes/admin/TaxRates.tsx. Every rate is admin-entered
// and government-cited; Claude only ever classifies items into a
// category, it never sets or approves the rate itself. The backend
// enforces a non-blank citation_url (migration 0027_tax_rule_citation),
// but this ViewModel validates it BEFORE making the network call too, so
// the requirement is surfaced immediately rather than round-tripped
// through a 400.
class TaxRatesViewModel(
    private val apiClient: () -> ApiClient,
    private val logger: FileLogger? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(TaxRatesUiState())
    val uiState: StateFlow<TaxRatesUiState> = _uiState.asStateFlow()

    fun load() {
        logger?.debug(LOG_TAG, "loading tax rules")
        _uiState.update { it.copy(isLoading = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.listTaxRules()) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "loaded ${result.data.size} tax rules")
                    _uiState.update { it.copy(rules = result.data, isLoading = false) }
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

    fun updateForm(transform: (TaxRuleFormState) -> TaxRuleFormState) {
        _uiState.update { it.copy(form = transform(it.form)) }
    }

    fun addRule() {
        val form = _uiState.value.form
        val percentValue = form.percent.toDoubleOrNull()
        if (
            form.jurisdiction.isBlank() ||
            form.source.isBlank() ||
            form.citationUrl.isBlank() ||
            percentValue == null
        ) {
            logger?.warn(LOG_TAG, "addRule rejected: missing required field or invalid rate")
            _uiState.update { it.copy(
                errorMessage =
                    "Jurisdiction, a valid rate, source, and a government citation URL are required.",
            ) }
            return
        }
        logger?.info(
            LOG_TAG,
            "adding tax rule jurisdiction=${form.jurisdiction} taxType=${form.taxType}",
        )
        _uiState.update { it.copy(isSubmitting = true, errorMessage = null) }
        viewModelScope.launch {
            val result = apiClient().admin.addTaxRule(
                TaxRuleCreateRequest(
                    jurisdiction = form.jurisdiction.trim(),
                    tax_type = form.taxType.trim(),
                    category = form.category.ifBlank { "*" }.trim(),
                    rate = (percentValue / 100).toString(),
                    source = form.source.trim(),
                    citation_url = form.citationUrl.trim(),
                ),
            )
            when (result) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "tax rule added id=${result.data.id}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        form = TaxRuleFormState(),
                    ) }
                    load()
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "addRule failed: ${result.message}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "addRule network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }
}
