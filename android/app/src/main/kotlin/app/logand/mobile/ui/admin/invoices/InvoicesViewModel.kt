package app.logand.mobile.ui.admin.invoices

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.logand.core.ApiClient
import app.logand.core.ApiResult
import app.logand.core.model.BomSummary
import app.logand.core.model.InvoiceDetail
import app.logand.core.model.InvoiceLineItem
import app.logand.core.model.InvoiceSummary
import app.logand.core.model.ManualPaymentRequest
import app.logand.core.model.PaymentProofSummary
import app.logand.core.model.RefundRequest
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

// A blank line item for a new invoice's create form -- same shape as
// the web app's EMPTY_LINE_ITEM constant in
// frontend/src/app/routes/admin/Invoices.tsx.
data class InvoiceLineItemForm(
    val description: String = "",
    val quantity: String = "1",
    val unitPrice: String = "",
    val unit: String = "",
)

// Which "bill to" path the create-invoice form is using -- mirrors the
// backend's "exactly one of customer_id/customer_email" contract (see
// AdminApi.createInvoice's own doc comment and
// docs/design/17-contact-users-and-email-verification.md): an admin can
// either pick an existing customer by id, or address the invoice to a
// bare email with no account yet.
enum class InvoiceRecipientMode { EXISTING_CUSTOMER, BARE_EMAIL }

data class CreateInvoiceFormState(
    val recipientMode: InvoiceRecipientMode = InvoiceRecipientMode.EXISTING_CUSTOMER,
    val customerId: String = "",
    val customerEmail: String = "",
    val memo: String = "",
    val lineItems: List<InvoiceLineItemForm> = listOf(InvoiceLineItemForm()),
    // BOM-import controls -- mirror Invoices.tsx's importBomId/
    // importBuildQuantity component state (not part of the actual
    // create-invoice request body, just inputs to the import action).
    val importBomId: String = "",
    val importBuildQuantity: String = "1",
)

data class InvoicesUiState(
    val invoices: List<InvoiceSummary> = emptyList(),
    val isLoading: Boolean = false,
    val isSubmitting: Boolean = false,
    val errorMessage: String? = null,
    val createForm: CreateInvoiceFormState = CreateInvoiceFormState(),
    // Detail panel for whichever invoice is currently expanded -- lazy
    // loaded on demand, same as the web app's PaymentsPanel.
    val selectedInvoiceId: String? = null,
    val selectedDetail: InvoiceDetail? = null,
    val isDetailLoading: Boolean = false,
    val paymentProofs: List<PaymentProofSummary> = emptyList(),
    val isProofsLoading: Boolean = false,
    // BOMs available to import from -- lazy loaded once the create-invoice
    // dialog opens, same as the web app's bomsQuery (enabled: open).
    val boms: List<BomSummary> = emptyList(),
    val isBomsLoading: Boolean = false,
    val isImportingBom: Boolean = false,
    val bomImportError: String? = null,
    // Which invoice/proof a PDF or payment-proof download is in flight
    // for -- lets the screen disable just that one row's button, same as
    // the web app's pdfMutation.variables === invoice.id check.
    val downloadingPdfInvoiceId: String? = null,
    val downloadingProofId: String? = null,
    // The invoice whose send is awaiting explicit confirmation -- the Send
    // action stages this instead of firing immediately, so the admin always
    // sees the total (and, if flagged, the tax-review reason) and cannot
    // bypass the guard the phone must mirror. Null when no dialog is open.
    val pendingSend: InvoiceSummary? = null,
)

// Drives the admin Invoices screen: list/create/send/void invoices,
// record manual (out-of-band) payments, view a payment's proof/refund
// history, and issue refunds -- the mobile mirror of
// frontend/src/app/routes/admin/Invoices.tsx. Every write funnels
// through AdminApi (see AdminApi.kt) and every failure surfaces as
// errorMessage rather than throwing, per ApiResult's own contract.
class InvoicesViewModel(private val apiClient: () -> ApiClient) : ViewModel() {
    private val _uiState = MutableStateFlow(InvoicesUiState())
    val uiState: StateFlow<InvoicesUiState> = _uiState.asStateFlow()

    fun load() {
        _uiState.update { it.copy(isLoading = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.listInvoices()) {
                is ApiResult.Success -> _uiState.update { it.copy(invoices = result.data, isLoading = false) }
                is ApiResult.HttpError -> _uiState.update { it.copy(isLoading = false, errorMessage = result.message) }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isLoading = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun updateCreateForm(transform: (CreateInvoiceFormState) -> CreateInvoiceFormState) {
        _uiState.update { it.copy(createForm = transform(it.createForm)) }
    }

    fun addLineItem() {
        updateCreateForm { it.copy(lineItems = it.lineItems + InvoiceLineItemForm()) }
    }

    fun removeLineItem(index: Int) {
        updateCreateForm { form ->
            if (form.lineItems.size <= 1) return@updateCreateForm form
            form.copy(lineItems = form.lineItems.filterIndexed { i, _ -> i != index })
        }
    }

    fun updateLineItem(index: Int, transform: (InvoiceLineItemForm) -> InvoiceLineItemForm) {
        updateCreateForm { form ->
            form.copy(
                lineItems = form.lineItems.mapIndexed { i, item ->
                    if (i == index) transform(item) else item
                },
            )
        }
    }

    // Mirrors the web form's hasAtLeastOneRealLineItem gate: a line item
    // only counts once it has both a description and a unit price.
    private fun realLineItems(form: CreateInvoiceFormState): List<InvoiceLineItem> =
        form.lineItems
            .filter { it.description.isNotBlank() && it.unitPrice.isNotBlank() }
            .map {
                InvoiceLineItem(
                    description = it.description.trim(),
                    quantity = it.quantity.trim().ifBlank { "1" },
                    unit_price = it.unitPrice.trim(),
                    unit = it.unit.trim().ifBlank { null },
                )
            }

    fun createInvoice(onDone: (Boolean) -> Unit = {}) {
        val form = _uiState.value.createForm
        val lineItems = realLineItems(form)
        val recipientReady = when (form.recipientMode) {
            InvoiceRecipientMode.EXISTING_CUSTOMER -> form.customerId.isNotBlank()
            InvoiceRecipientMode.BARE_EMAIL -> form.customerEmail.isNotBlank()
        }
        if (!recipientReady || lineItems.isEmpty()) {
            _uiState.update { it.copy(
                errorMessage = "Pick a customer (or enter an email) and at least one line item.",
            ) }
            onDone(false)
            return
        }
        _uiState.update { it.copy(isSubmitting = true, errorMessage = null) }
        viewModelScope.launch {
            val result = apiClient().admin.createInvoice(
                customerId = if (form.recipientMode == InvoiceRecipientMode.EXISTING_CUSTOMER) {
                    form.customerId.trim()
                } else {
                    null
                },
                customerEmail = if (form.recipientMode == InvoiceRecipientMode.BARE_EMAIL) {
                    form.customerEmail.trim()
                } else {
                    null
                },
                lineItems = lineItems,
                memo = form.memo.trim().ifBlank { null },
            )
            when (result) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        createForm = CreateInvoiceFormState(),
                    ) }
                    load()
                    onDone(true)
                }
                is ApiResult.HttpError -> {
                    _uiState.update { it.copy(isSubmitting = false, errorMessage = result.message) }
                    onDone(false)
                }
                is ApiResult.NetworkError -> {
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                    onDone(false)
                }
            }
        }
    }

    // Stages the pre-send confirmation instead of sending outright -- the
    // dialog shows the total and (if flagged) the tax-review reason before
    // the irreversible send.
    fun requestSend(invoice: InvoiceSummary) {
        _uiState.update { it.copy(pendingSend = invoice, errorMessage = null) }
    }

    fun cancelSend() {
        _uiState.update { it.copy(pendingSend = null) }
    }

    // `acknowledgeReview` is the admin's explicit override of the tax-review
    // guard, passed through to the backend as ?acknowledge_review=true (see
    // AdminApi.sendInvoice). A NeedsReview 409 keeps the dialog open with
    // the backend's concrete reason rather than silently dismissing.
    fun confirmSend(invoiceId: String, acknowledgeReview: Boolean = false) {
        _uiState.update { it.copy(isSubmitting = true, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.sendInvoice(invoiceId, acknowledgeReview)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(isSubmitting = false, pendingSend = null) }
                    load()
                }
                is ApiResult.HttpError -> _uiState.update { it.copy(
                    isSubmitting = false,
                    errorMessage = result.message,
                ) }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isSubmitting = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun voidInvoice(invoiceId: String) {
        viewModelScope.launch {
            when (val result = apiClient().admin.voidInvoice(invoiceId)) {
                is ApiResult.Success -> load()
                is ApiResult.HttpError -> _uiState.update { it.copy(errorMessage = result.message) }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    // Toggling the same id again collapses the panel, same as the web
    // app's PaymentsPanel/CustomerDetailPanel expand-toggle convention.
    fun toggleDetail(invoiceId: String) {
        if (_uiState.value.selectedInvoiceId == invoiceId) {
            _uiState.update { it.copy(
                selectedInvoiceId = null,
                selectedDetail = null,
                paymentProofs = emptyList(),
            ) }
            return
        }
        _uiState.update { it.copy(
            selectedInvoiceId = invoiceId,
            selectedDetail = null,
            paymentProofs = emptyList(),
            isDetailLoading = true,
        ) }
        viewModelScope.launch {
            when (val result = apiClient().admin.getInvoice(invoiceId)) {
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
        viewModelScope.launch {
            _uiState.update { it.copy(isProofsLoading = true) }
            when (val result = apiClient().admin.listPaymentProofs(invoiceId)) {
                is ApiResult.Success -> _uiState.update { it.copy(paymentProofs = result.data, isProofsLoading = false) }
                is ApiResult.HttpError -> _uiState.update { it.copy(
                    isProofsLoading = false,
                    errorMessage = result.message,
                ) }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    isProofsLoading = false,
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    private fun refreshDetail(invoiceId: String) {
        viewModelScope.launch {
            when (val result = apiClient().admin.getInvoice(invoiceId)) {
                is ApiResult.Success -> _uiState.update { it.copy(selectedDetail = result.data) }
                is ApiResult.HttpError -> _uiState.update { it.copy(errorMessage = result.message) }
                is ApiResult.NetworkError -> _uiState.update { it.copy(
                    errorMessage = "Could not reach the server. Check your connection.",
                ) }
            }
        }
    }

    fun recordManualPayment(
        invoiceId: String,
        method: String,
        amount: String,
        note: String?,
        onDone: (Boolean) -> Unit = {},
    ) {
        _uiState.update { it.copy(isSubmitting = true, errorMessage = null) }
        viewModelScope.launch {
            val result = apiClient().admin.recordManualPayment(
                invoiceId = invoiceId,
                payment = ManualPaymentRequest(method = method, amount = amount, note = note),
            )
            when (result) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(isSubmitting = false) }
                    load()
                    refreshDetail(invoiceId)
                    onDone(true)
                }
                is ApiResult.HttpError -> {
                    _uiState.update { it.copy(isSubmitting = false, errorMessage = result.message) }
                    onDone(false)
                }
                is ApiResult.NetworkError -> {
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                    onDone(false)
                }
            }
        }
    }

    // idempotency_key is minted fresh per refund attempt here (a plain
    // UUID, not retained across retries by this simple mobile form) --
    // matches RefundRequest's own doc comment: a retried click after a
    // FAILED attempt should mint a new key, which a fresh call to this
    // function naturally does.
    fun refundPayment(
        invoiceId: String,
        paymentId: String,
        amount: String?,
        reason: String?,
        onDone: (Boolean) -> Unit = {},
    ) {
        _uiState.update { it.copy(isSubmitting = true, errorMessage = null) }
        viewModelScope.launch {
            val result = apiClient().admin.refundPayment(
                invoiceId = invoiceId,
                paymentId = paymentId,
                refund = RefundRequest(
                    payment_id = paymentId,
                    amount = amount,
                    reason = reason,
                    idempotency_key = UUID.randomUUID().toString(),
                ),
            )
            when (result) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(isSubmitting = false) }
                    refreshDetail(invoiceId)
                    onDone(true)
                }
                is ApiResult.HttpError -> {
                    _uiState.update { it.copy(isSubmitting = false, errorMessage = result.message) }
                    onDone(false)
                }
                is ApiResult.NetworkError -> {
                    _uiState.update { it.copy(
                        isSubmitting = false,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                    onDone(false)
                }
            }
        }
    }

    // Lazy-loaded the first time the create-invoice dialog opens -- same
    // convention as the web app's bomsQuery (enabled: open). Silently
    // no-ops on failure (surfaced as bomImportError only if the admin
    // then tries to import) since an admin who never touches the BOM
    // import section shouldn't see an error for a feature they didn't use.
    fun loadBoms() {
        if (_uiState.value.boms.isNotEmpty() || _uiState.value.isBomsLoading) return
        _uiState.update { it.copy(isBomsLoading = true) }
        viewModelScope.launch {
            when (val result = apiClient().admin.listBoms()) {
                is ApiResult.Success -> _uiState.update { it.copy(boms = result.data, isBomsLoading = false) }
                is ApiResult.HttpError, is ApiResult.NetworkError ->
                    _uiState.update { it.copy(isBomsLoading = false) }
            }
        }
    }

    // Fetches the selected BOM's cost breakdown and turns it into real
    // invoice line items -- mirrors Invoices.tsx's importMutation exactly:
    // one line per material (its own real quantity/unit cost, so it
    // still reads as "12 resistors @ $0.10"), one lump line for labor
    // (hours as quantity, the BOM's own labor_rate as unit price) if
    // labor_hours > 0, and one lump line for overhead if overhead_cost >
    // 0. This REPLACES the current line items rather than appending --
    // importing from a BOM is meant to BE the invoice's line items, not
    // mixed in with whatever was already half-typed.
    fun importBomAsLineItems(onDone: (Boolean) -> Unit = {}) {
        val form = _uiState.value.createForm
        val bomId = form.importBomId
        if (bomId.isBlank()) {
            onDone(false)
            return
        }
        val buildQuantity = form.importBuildQuantity.toIntOrNull()?.coerceAtLeast(1) ?: 1
        _uiState.update { it.copy(isImportingBom = true, bomImportError = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.getBomCostBreakdown(bomId, buildQuantity)) {
                is ApiResult.Success -> {
                    val breakdown = result.data
                    val bom = _uiState.value.boms.find { it.id == bomId }
                    val materialLines = breakdown.material_lines.map {
                        InvoiceLineItemForm(
                            description = it.item_name,
                            quantity = it.quantity.toString(),
                            unitPrice = it.unit_cost,
                            unit = "ea",
                        )
                    }
                    val laborLine = if ((breakdown.labor_hours.toDoubleOrNull() ?: 0.0) > 0.0) {
                        InvoiceLineItemForm(
                            description = "Labor" + (bom?.let { " (${it.name})" } ?: ""),
                            quantity = breakdown.labor_hours,
                            unitPrice = bom?.labor_rate ?: "0",
                            unit = "hr",
                        )
                    } else {
                        null
                    }
                    val overheadLine = if ((breakdown.overhead_cost.toDoubleOrNull() ?: 0.0) > 0.0) {
                        InvoiceLineItemForm(
                            description = "Overhead (${breakdown.overhead_percent}%)",
                            quantity = "1",
                            unitPrice = breakdown.overhead_cost,
                            unit = "",
                        )
                    } else {
                        null
                    }
                    val imported = materialLines + listOfNotNull(laborLine, overheadLine)
                    updateCreateForm {
                        it.copy(
                            lineItems = imported.ifEmpty { listOf(InvoiceLineItemForm()) },
                        )
                    }
                    _uiState.update { it.copy(isImportingBom = false) }
                    onDone(true)
                }
                is ApiResult.HttpError -> {
                    _uiState.update { it.copy(
                        isImportingBom = false,
                        bomImportError = "Could not import -- every material line needs a" +
                            " real unit_cost set first.",
                    ) }
                    onDone(false)
                }
                is ApiResult.NetworkError -> {
                    _uiState.update { it.copy(
                        isImportingBom = false,
                        bomImportError = "Could not reach the server. Check your connection.",
                    ) }
                    onDone(false)
                }
            }
        }
    }

    // Downloads one invoice's PDF -- onResult receives the bytes on
    // success, or null on failure (errorMessage is also set). Writing
    // the bytes to disk/share-sheet is the caller's job (needs a Context
    // this ViewModel deliberately does not hold), same split as
    // AdminLogsViewModel.downloadFile.
    fun downloadInvoicePdf(invoiceId: String, onResult: (ByteArray?) -> Unit) {
        _uiState.update { it.copy(downloadingPdfInvoiceId = invoiceId, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.getInvoicePdf(invoiceId)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(downloadingPdfInvoiceId = null) }
                    onResult(result.data)
                }
                is ApiResult.HttpError -> {
                    _uiState.update { it.copy(
                        downloadingPdfInvoiceId = null,
                        errorMessage = result.message,
                    ) }
                    onResult(null)
                }
                is ApiResult.NetworkError -> {
                    _uiState.update { it.copy(
                        downloadingPdfInvoiceId = null,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                    onResult(null)
                }
            }
        }
    }

    // Downloads one payment-proof file -- same shape as downloadInvoicePdf
    // above, just against the payment-proof-file route.
    fun downloadPaymentProof(invoiceId: String, proofId: String, onResult: (ByteArray?) -> Unit) {
        _uiState.update { it.copy(downloadingProofId = proofId, errorMessage = null) }
        viewModelScope.launch {
            when (val result = apiClient().admin.downloadPaymentProof(invoiceId, proofId)) {
                is ApiResult.Success -> {
                    _uiState.update { it.copy(downloadingProofId = null) }
                    onResult(result.data)
                }
                is ApiResult.HttpError -> {
                    _uiState.update { it.copy(
                        downloadingProofId = null,
                        errorMessage = result.message,
                    ) }
                    onResult(null)
                }
                is ApiResult.NetworkError -> {
                    _uiState.update { it.copy(
                        downloadingProofId = null,
                        errorMessage = "Could not reach the server. Check your connection.",
                    ) }
                    onResult(null)
                }
            }
        }
    }
}
