package app.logand.mobile.ui.admin.taxreport

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.logging.FileLogger
import app.logand.core.model.StripeTaxReconcile
import app.logand.core.model.TaxReport
import java.time.LocalDate
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val LOG_TAG = "TaxReportViewModel"

data class TaxDateRange(val from: String, val to: String)

// Defaults to the current calendar year -- the usual filing window, same
// default as the web app's TaxReport.tsx.
private fun defaultRange(): TaxDateRange {
    val today = LocalDate.now()
    return TaxDateRange(from = "${today.year}-01-01", to = today.toString())
}

data class TaxReportUiState(
    val range: TaxDateRange = defaultRange(),
    val report: TaxReport? = null,
    val isLoadingReport: Boolean = false,
    val errorMessage: String? = null,

    val stripeReconcile: StripeTaxReconcile? = null,
    val isLoadingStripeReconcile: Boolean = false,
    val stripeErrorMessage: String? = null,
)

// Drives the read-only admin Tax report screen -- the mobile mirror of
// frontend/src/app/routes/admin/TaxReport.tsx. Everything is computed
// fresh on the server from real invoice rows
// (domain/invoices/tax/report.py), the same figures the invoices show, so
// it can't drift from what a customer was actually charged. Also loads
// Stripe's own reconciliation figures for the same range as a
// cross-check (only covers Stripe-processed payments) -- both requests
// run independently so a failure in one never blocks the other from
// rendering.
class TaxReportViewModel(
    private val apiClient: () -> ApiClient,
    private val logger: FileLogger? = null,
) : ViewModel() {
    private val _uiState = MutableStateFlow(TaxReportUiState())
    val uiState: StateFlow<TaxReportUiState> = _uiState.asStateFlow()

    fun load() {
        val range = _uiState.value.range
        logger?.debug(LOG_TAG, "loading tax report range=${range.from}..${range.to}")
        loadReport(range)
        loadStripeReconcile(range)
    }

    fun setRange(range: TaxDateRange) {
        logger?.info(LOG_TAG, "tax report range changed to ${range.from}..${range.to}")
        _uiState.update { it.copy(range = range) }
        loadReport(range)
        loadStripeReconcile(range)
    }

    private fun loadReport(range: TaxDateRange) {
        _uiState.update { it.copy(isLoadingReport = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.getTaxReport(range.from, range.to)) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "tax report loaded invoice_count=${result.data.invoice_count}")
                    _uiState.update { it.copy(report = result.data, isLoadingReport = false) }
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "getTaxReport failed: ${result.message}")
                    _uiState.update { it.copy(
                        isLoadingReport = false,
                        errorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "getTaxReport network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isLoadingReport = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }

    private fun loadStripeReconcile(range: TaxDateRange) {
        _uiState.update { it.copy(isLoadingStripeReconcile = true, stripeErrorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.getStripeReconcile(range.from, range.to)) {
                is ApiResult.Success -> {
                    logger?.info(LOG_TAG, "stripe reconcile loaded transaction_count=${result.data.transaction_count}")
                    _uiState.update { it.copy(
                        stripeReconcile = result.data,
                        isLoadingStripeReconcile = false,
                    ) }
                }
                is ApiResult.HttpError -> {
                    logger?.warn(LOG_TAG, "getStripeReconcile failed: ${result.message}")
                    _uiState.update { it.copy(
                        isLoadingStripeReconcile = false,
                        stripeErrorMessage = result.message,
                    ) }
                }
                is ApiResult.NetworkError -> {
                    logger?.warn(LOG_TAG, "getStripeReconcile network error: ${result.cause}")
                    _uiState.update { it.copy(
                        isLoadingStripeReconcile = false,
                        stripeErrorMessage = "Could not reach the server. Check your connection.",
                    ) }
                }
            }
        }
    }
}
