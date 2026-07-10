package app.logand.mobile.ui.admin.invoices

import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.logand.core.model.InvoicePayment
import app.logand.core.model.InvoiceSummary
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall

private val MANUAL_PAYMENT_METHODS = listOf(
    "zelle" to "Zelle",
    "paypal" to "PayPal (sent directly)",
    "in_person" to "In person",
    "other" to "Other",
)

// Same "which payment statuses still have something left to refund" rule
// as the web app's REFUNDABLE_PAYMENT_STATUSES (see Invoices.tsx).
private val REFUNDABLE_PAYMENT_STATUSES = setOf("succeeded", "partially_refunded")

@Composable
fun InvoicesScreen(viewModel: InvoicesViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var showCreateDialog by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val downloadController = remember { InvoiceDownloadController(context) }

    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold(
        floatingActionButton = {
            FloatingActionButton(
                onClick = { showCreateDialog = true },
                modifier = Modifier.semantics { contentDescription = "new invoice" },
            ) {
                Text("+", style = MaterialTheme.typography.headlineSmall)
            }
        },
    ) { padding ->
        Column(modifier = Modifier.padding(padding)) {
            uiState.errorMessage?.let { message ->
                Text(
                    text = message,
                    color = AccentRed,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .semantics { contentDescription = "invoices error: $message" },
                )
            }

            if (uiState.isLoading && uiState.invoices.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize()) {
                    CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
                }
            } else if (uiState.invoices.isEmpty()) {
                Text(
                    "No invoices yet.",
                    modifier = Modifier.padding(SpacingMedium),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                LazyColumn {
                    items(uiState.invoices, key = { it.id }) { invoice ->
                        InvoiceRow(
                            invoice = invoice,
                            isExpanded = uiState.selectedInvoiceId == invoice.id,
                            isDownloadingPdf = uiState.downloadingPdfInvoiceId == invoice.id,
                            onToggleExpand = { viewModel.toggleDetail(invoice.id) },
                            onSend = { viewModel.sendInvoice(invoice.id) },
                            onVoid = { viewModel.voidInvoice(invoice.id) },
                            onDownloadPdf = {
                                viewModel.downloadInvoicePdf(invoice.id) { bytes ->
                                    if (bytes != null) {
                                        val intent = downloadController.writeAndBuildPdfShareIntent(
                                            invoice.id,
                                            bytes,
                                        )
                                        context.startActivity(
                                            Intent.createChooser(intent, "Share invoice PDF"),
                                        )
                                    }
                                }
                            },
                        )
                        if (uiState.selectedInvoiceId == invoice.id) {
                            InvoiceDetailPanel(
                                viewModel = viewModel,
                                invoiceId = invoice.id,
                                downloadController = downloadController,
                                context = context,
                            )
                        }
                        HorizontalDivider()
                    }
                }
            }
        }
    }

    if (showCreateDialog) {
        CreateInvoiceDialog(
            viewModel = viewModel,
            onDismiss = { showCreateDialog = false },
            onCreated = { showCreateDialog = false },
        )
    }
}

@Composable
private fun InvoiceRow(
    invoice: InvoiceSummary,
    isExpanded: Boolean,
    isDownloadingPdf: Boolean,
    onToggleExpand: () -> Unit,
    onSend: () -> Unit,
    onVoid: () -> Unit,
    onDownloadPdf: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Column {
                Text(
                    "${invoice.status} -- ${invoice.amount_total} ${invoice.currency.uppercase()}",
                    style = MaterialTheme.typography.bodyLarge,
                )
                Text(
                    listOfNotNull(
                        invoice.due_date?.let { "due $it" },
                        invoice.memo,
                    ).joinToString(" -- ").ifBlank { "invoice ${invoice.id}" },
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Button(
                onClick = onToggleExpand,
                modifier = Modifier.semantics {
                    contentDescription = "toggle details for invoice ${invoice.id}"
                },
            ) {
                Text(if (isExpanded) "Hide" else "Details")
            }
        }
        Row(
            horizontalArrangement = Arrangement.spacedBy(SpacingSmall),
            modifier = Modifier.padding(top = SpacingSmall),
        ) {
            Button(
                onClick = onSend,
                enabled = invoice.status == "draft",
                modifier = Modifier.semantics { contentDescription = "send invoice ${invoice.id}" },
            ) {
                Text("Send")
            }
            Button(
                onClick = onVoid,
                enabled = invoice.status != "void",
                modifier = Modifier.semantics { contentDescription = "void invoice ${invoice.id}" },
            ) {
                Text("Void")
            }
            Button(
                onClick = onDownloadPdf,
                enabled = !isDownloadingPdf,
                modifier = Modifier.semantics {
                    contentDescription = "download pdf for invoice ${invoice.id}"
                },
            ) {
                Text(if (isDownloadingPdf) "Downloading..." else "PDF")
            }
        }
    }
}

@Composable
private fun InvoiceDetailPanel(
    viewModel: InvoicesViewModel,
    invoiceId: String,
    downloadController: InvoiceDownloadController,
    context: android.content.Context,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var showManualPaymentForm by remember { mutableStateOf(false) }

    Column(modifier = Modifier.padding(start = SpacingMedium, end = SpacingMedium, bottom = SpacingMedium)) {
        if (uiState.isDetailLoading) {
            CircularProgressIndicator(modifier = Modifier.padding(SpacingSmall))
        }

        val detail = uiState.selectedDetail
        val invoice = uiState.invoices.find { it.id == invoiceId }

        if (invoice != null && (invoice.status == "sent" || invoice.status == "overdue")) {
            if (!showManualPaymentForm) {
                Button(
                    onClick = { showManualPaymentForm = true },
                    modifier = Modifier.semantics {
                        contentDescription = "record manual payment for invoice $invoiceId"
                    },
                ) {
                    Text("Record payment")
                }
            } else {
                ManualPaymentForm(
                    invoiceId = invoiceId,
                    isSubmitting = uiState.isSubmitting,
                    onCancel = { showManualPaymentForm = false },
                    onSubmit = { method, amount, note ->
                        viewModel.recordManualPayment(invoiceId, method, amount, note) { ok ->
                            if (ok) showManualPaymentForm = false
                        }
                    },
                )
            }
        }

        if (uiState.isProofsLoading) {
            Text("Loading payment proofs...", style = MaterialTheme.typography.labelMedium)
        } else if (uiState.paymentProofs.isEmpty()) {
            Text(
                "No proof uploaded by the customer yet.",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            uiState.paymentProofs.forEach { proof ->
                Row(
                    verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(SpacingSmall),
                ) {
                    Text(
                        "Proof: ${proof.content_type} (${proof.created_at})",
                        style = MaterialTheme.typography.labelMedium,
                    )
                    val isDownloadingThisProof = uiState.downloadingProofId == proof.id
                    Button(
                        onClick = {
                            viewModel.downloadPaymentProof(invoiceId, proof.id) { bytes ->
                                if (bytes != null) {
                                    val intent = downloadController.writeAndBuildProofShareIntent(
                                        invoiceId,
                                        proof.id,
                                        proof.content_type,
                                        bytes,
                                    )
                                    context.startActivity(
                                        Intent.createChooser(intent, "Share payment proof"),
                                    )
                                }
                            }
                        },
                        enabled = !isDownloadingThisProof,
                        modifier = Modifier.semantics {
                            contentDescription = "download payment proof ${proof.id}"
                        },
                    ) {
                        Text(if (isDownloadingThisProof) "Downloading..." else "Open")
                    }
                }
            }
        }

        detail?.payments?.forEach { payment ->
            PaymentDetailRow(
                invoiceId = invoiceId,
                payment = payment,
                isSubmitting = uiState.isSubmitting,
                onRefund = { amount, reason ->
                    viewModel.refundPayment(invoiceId, payment.id, amount, reason)
                },
            )
        }
    }
}

@Composable
private fun PaymentDetailRow(
    invoiceId: String,
    payment: InvoicePayment,
    isSubmitting: Boolean,
    onRefund: (amount: String?, reason: String?) -> Unit,
) {
    var showRefundForm by remember { mutableStateOf(false) }

    Column(modifier = Modifier.padding(vertical = SpacingSmall)) {
        Text(
            "${payment.method} -- ${payment.amount} (${payment.status})",
            style = MaterialTheme.typography.bodyLarge,
        )
        payment.note?.let {
            Text("Note: $it", style = MaterialTheme.typography.labelMedium)
        }
        payment.dispute_status?.let {
            Text("Dispute: $it", style = MaterialTheme.typography.labelMedium, color = AccentRed)
        }
        payment.refunds.forEach { refund ->
            Text(
                "Refunded ${refund.amount}" + (refund.reason?.let { " -- $it" } ?: ""),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        if (payment.status in REFUNDABLE_PAYMENT_STATUSES) {
            if (!showRefundForm) {
                Button(
                    onClick = { showRefundForm = true },
                    modifier = Modifier.semantics {
                        contentDescription = "refund payment ${payment.id}"
                    },
                ) {
                    Text("Refund")
                }
            } else {
                var amount by remember { mutableStateOf("") }
                var reason by remember { mutableStateOf("") }
                OutlinedTextField(
                    value = amount,
                    onValueChange = { amount = it },
                    label = { Text("Amount (blank = full remaining)") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = reason,
                    onValueChange = { reason = it },
                    label = { Text("Reason (optional)") },
                    singleLine = true,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                    Button(
                        onClick = {
                            onRefund(amount.ifBlank { null }, reason.ifBlank { null })
                            showRefundForm = false
                        },
                        enabled = !isSubmitting,
                        modifier = Modifier.semantics {
                            contentDescription = "confirm refund for payment ${payment.id}"
                        },
                    ) {
                        Text(if (isSubmitting) "Refunding..." else "Confirm refund")
                    }
                    Button(onClick = { showRefundForm = false }) { Text("Cancel") }
                }
            }
        }
    }
}

@Composable
private fun ManualPaymentForm(
    invoiceId: String,
    isSubmitting: Boolean,
    onCancel: () -> Unit,
    onSubmit: (method: String, amount: String, note: String?) -> Unit,
) {
    var method by remember { mutableStateOf(MANUAL_PAYMENT_METHODS.first().first) }
    var methodMenuOpen by remember { mutableStateOf(false) }
    var amount by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }

    Column {
        Box {
            Button(
                onClick = { methodMenuOpen = true },
                modifier = Modifier.semantics { contentDescription = "manual payment method" },
            ) {
                Text(MANUAL_PAYMENT_METHODS.first { it.first == method }.second)
            }
            DropdownMenu(expanded = methodMenuOpen, onDismissRequest = { methodMenuOpen = false }) {
                MANUAL_PAYMENT_METHODS.forEach { (value, label) ->
                    DropdownMenuItem(
                        text = { Text(label) },
                        onClick = { method = value; methodMenuOpen = false },
                    )
                }
            }
        }
        OutlinedTextField(
            value = amount,
            onValueChange = { amount = it },
            label = { Text("Amount") },
            singleLine = true,
        )
        OutlinedTextField(
            value = note,
            onValueChange = { note = it },
            label = { Text("Note (optional)") },
            singleLine = true,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
            Button(
                onClick = { onSubmit(method, amount, note.ifBlank { null }) },
                enabled = !isSubmitting && amount.isNotBlank(),
                modifier = Modifier.semantics {
                    contentDescription = "save manual payment for invoice $invoiceId"
                },
            ) {
                Text(if (isSubmitting) "Recording..." else "Save")
            }
            Button(onClick = onCancel) { Text("Cancel") }
        }
    }
}

@Composable
private fun CreateInvoiceDialog(
    viewModel: InvoicesViewModel,
    onDismiss: () -> Unit,
    onCreated: () -> Unit,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val form = uiState.createForm

    LaunchedEffect(Unit) { viewModel.loadBoms() }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("New invoice") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                    InvoiceRecipientMode.entries.forEach { candidate ->
                        val selected = candidate == form.recipientMode
                        Button(
                            onClick = {
                                viewModel.updateCreateForm { it.copy(recipientMode = candidate) }
                            },
                            colors = if (selected) {
                                ButtonDefaults.buttonColors()
                            } else {
                                ButtonDefaults.outlinedButtonColors()
                            },
                            modifier = Modifier.semantics {
                                contentDescription = when (candidate) {
                                    InvoiceRecipientMode.EXISTING_CUSTOMER -> "bill an existing customer"
                                    InvoiceRecipientMode.BARE_EMAIL -> "bill a bare email address"
                                }
                            },
                        ) {
                            Text(
                                when (candidate) {
                                    InvoiceRecipientMode.EXISTING_CUSTOMER -> "Customer"
                                    InvoiceRecipientMode.BARE_EMAIL -> "Email only"
                                },
                            )
                        }
                    }
                }

                if (form.recipientMode == InvoiceRecipientMode.EXISTING_CUSTOMER) {
                    OutlinedTextField(
                        value = form.customerId,
                        onValueChange = { v ->
                            viewModel.updateCreateForm { it.copy(customerId = v) }
                        },
                        label = { Text("Customer id") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                } else {
                    // Addresses the invoice to an email with no existing
                    // account -- backend get-or-creates a contact user
                    // (see docs/design/16-contact-users-and-email-verification.md).
                    OutlinedTextField(
                        value = form.customerEmail,
                        onValueChange = { v ->
                            viewModel.updateCreateForm { it.copy(customerEmail = v) }
                        },
                        label = { Text("Customer email (no account needed)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }

                if (uiState.boms.isNotEmpty()) {
                    BomImportSection(
                        boms = uiState.boms,
                        importBomId = form.importBomId,
                        importBuildQuantity = form.importBuildQuantity,
                        isImporting = uiState.isImportingBom,
                        importError = uiState.bomImportError,
                        onImportBomIdChange = { id ->
                            viewModel.updateCreateForm { it.copy(importBomId = id) }
                        },
                        onImportBuildQuantityChange = { qty ->
                            viewModel.updateCreateForm { it.copy(importBuildQuantity = qty) }
                        },
                        onImport = { viewModel.importBomAsLineItems() },
                    )
                }

                Text("Line items", style = MaterialTheme.typography.labelLarge)
                form.lineItems.forEachIndexed { index, item ->
                    Column {
                        OutlinedTextField(
                            value = item.description,
                            onValueChange = { v ->
                                viewModel.updateLineItem(index) { it.copy(description = v) }
                            },
                            label = { Text("Description") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                            OutlinedTextField(
                                value = item.quantity,
                                onValueChange = { v ->
                                    viewModel.updateLineItem(index) { it.copy(quantity = v) }
                                },
                                label = { Text("Qty") },
                                singleLine = true,
                            )
                            OutlinedTextField(
                                value = item.unit,
                                onValueChange = { v ->
                                    viewModel.updateLineItem(index) { it.copy(unit = v) }
                                },
                                label = { Text("Unit") },
                                singleLine = true,
                            )
                            OutlinedTextField(
                                value = item.unitPrice,
                                onValueChange = { v ->
                                    viewModel.updateLineItem(index) { it.copy(unitPrice = v) }
                                },
                                label = { Text("Unit price") },
                                singleLine = true,
                            )
                        }
                        Button(
                            onClick = { viewModel.removeLineItem(index) },
                            enabled = form.lineItems.size > 1,
                            modifier = Modifier.semantics {
                                contentDescription = "remove line item ${index + 1}"
                            },
                        ) {
                            Text("Remove")
                        }
                    }
                }
                Button(
                    onClick = { viewModel.addLineItem() },
                    modifier = Modifier.semantics { contentDescription = "add line item" },
                ) {
                    Text("Add line item")
                }

                OutlinedTextField(
                    value = form.memo,
                    onValueChange = { v -> viewModel.updateCreateForm { it.copy(memo = v) } },
                    label = { Text("Memo (optional)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )

                uiState.errorMessage?.let { message ->
                    Text(message, color = AccentRed)
                }
            }
        },
        confirmButton = {
            Button(
                onClick = { viewModel.createInvoice { ok -> if (ok) onCreated() } },
                enabled = !uiState.isSubmitting,
                modifier = Modifier.semantics { contentDescription = "create invoice" },
            ) {
                Text(if (uiState.isSubmitting) "Creating..." else "Create invoice")
            }
        },
        dismissButton = {
            Button(onClick = onDismiss) { Text("Cancel") }
        },
    )
}

// Lets the admin pick a bill-of-materials and a build quantity, then
// replace the create-invoice form's line items with that BOM's cost
// breakdown -- mirrors the "Import from bill of materials" section in
// Invoices.tsx (one line per material, plus lump labor/overhead lines).
@Composable
private fun BomImportSection(
    boms: List<app.logand.core.model.BomSummary>,
    importBomId: String,
    importBuildQuantity: String,
    isImporting: Boolean,
    importError: String?,
    onImportBomIdChange: (String) -> Unit,
    onImportBuildQuantityChange: (String) -> Unit,
    onImport: () -> Unit,
) {
    var bomMenuOpen by remember { mutableStateOf(false) }
    val selectedBom = boms.find { it.id == importBomId }

    Column {
        Text("Import from bill of materials", style = MaterialTheme.typography.labelLarge)
        Row(
            horizontalArrangement = Arrangement.spacedBy(SpacingSmall),
        ) {
            Box {
                Button(
                    onClick = { bomMenuOpen = true },
                    modifier = Modifier.semantics { contentDescription = "select bom to import" },
                ) {
                    Text(selectedBom?.name ?: "Select a BOM...")
                }
                DropdownMenu(expanded = bomMenuOpen, onDismissRequest = { bomMenuOpen = false }) {
                    boms.forEach { bom ->
                        DropdownMenuItem(
                            text = { Text(bom.name) },
                            onClick = { onImportBomIdChange(bom.id); bomMenuOpen = false },
                        )
                    }
                }
            }
            OutlinedTextField(
                value = importBuildQuantity,
                onValueChange = onImportBuildQuantityChange,
                label = { Text("Build qty") },
                singleLine = true,
            )
            Button(
                onClick = onImport,
                enabled = importBomId.isNotBlank() && !isImporting,
                modifier = Modifier.semantics { contentDescription = "import bom as line items" },
            ) {
                Text(if (isImporting) "Importing..." else "Import as line items")
            }
        }
        importError?.let {
            Text(it, color = AccentRed, style = MaterialTheme.typography.labelMedium)
        }
    }
}
