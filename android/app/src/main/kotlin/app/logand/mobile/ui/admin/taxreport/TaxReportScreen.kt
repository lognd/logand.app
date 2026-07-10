package app.logand.mobile.ui.admin.taxreport

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall

// Read-only tax-filing breakdown over a date range -- the mobile mirror
// of frontend/src/app/routes/admin/TaxReport.tsx. Everything is computed
// fresh on the server from real invoice rows
// (domain/invoices/tax/report.py); this is an aid for filing, not tax
// advice.
@Composable
fun TaxReportScreen(viewModel: TaxReportViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var fromDraft by remember { mutableStateOf(uiState.range.from) }
    var toDraft by remember { mutableStateOf(uiState.range.to) }

    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold { padding ->
        LazyColumn(modifier = Modifier.padding(padding).fillMaxWidth()) {
            item {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(SpacingMedium),
                    verticalArrangement = Arrangement.spacedBy(SpacingSmall),
                ) {
                    OutlinedTextField(
                        value = fromDraft,
                        onValueChange = { fromDraft = it },
                        label = { Text("From (YYYY-MM-DD)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = toDraft,
                        onValueChange = { toDraft = it },
                        label = { Text("To (YYYY-MM-DD)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Button(
                        onClick = { viewModel.setRange(TaxDateRange(fromDraft, toDraft)) },
                        modifier = Modifier.semantics { contentDescription = "run tax report" },
                    ) { Text("Run report") }
                }
            }

            item {
                if (uiState.isLoadingReport && uiState.report == null) {
                    CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
                }
                uiState.errorMessage?.let { message ->
                    Text(
                        text = message,
                        color = AccentRed,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(SpacingMedium)
                            .semantics { contentDescription = "tax report error: $message" },
                    )
                }
            }

            uiState.report?.let { report ->
                item {
                    Column(modifier = Modifier.fillMaxWidth().padding(SpacingMedium)) {
                        StatRow("Invoices", report.invoice_count.toString())
                        StatRow("Total sales", report.total_sales)
                        StatRow("Tax collected", report.total_tax_collected)

                        Text(
                            "Jurisdictions to file for",
                            style = MaterialTheme.typography.titleMedium,
                            modifier = Modifier.padding(top = SpacingMedium),
                        )
                        if (report.filing_jurisdictions.isEmpty()) {
                            Text(
                                "No tax was collected in this range -- nothing to file.",
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        } else {
                            Text(report.filing_jurisdictions.joinToString(", "))
                        }

                        Text(
                            "Tax collected by jurisdiction",
                            style = MaterialTheme.typography.titleMedium,
                            modifier = Modifier.padding(top = SpacingMedium),
                        )
                    }
                }
                if (report.by_jurisdiction.isEmpty()) {
                    item {
                        Text(
                            "No tax collected in this range.",
                            modifier = Modifier.padding(horizontal = SpacingMedium),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                } else {
                    items(report.by_jurisdiction, key = { "${it.jurisdiction}-${it.tax_type}" }) { row ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text("${row.jurisdiction} -- ${row.tax_type}")
                            Text("${row.taxable_base} / ${row.tax_collected}")
                        }
                        HorizontalDivider()
                    }
                }

                item {
                    Text(
                        "Sales by tax category",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(SpacingMedium),
                    )
                }
                if (report.by_category.isEmpty()) {
                    item {
                        Text(
                            "No sales in this range.",
                            modifier = Modifier.padding(horizontal = SpacingMedium),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                } else {
                    items(report.by_category, key = { it.category }) { row ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(row.category)
                            Text("${row.gross} / ${row.taxable_gross}")
                        }
                        HorizontalDivider()
                    }
                }
            }

            item {
                Column(modifier = Modifier.fillMaxWidth().padding(SpacingMedium)) {
                    Text(
                        "Stripe-collected tax (for comparison)",
                        style = MaterialTheme.typography.titleMedium,
                    )
                    Text(
                        "Stripe's own recorded figure for cross-checking -- only covers " +
                            "payments processed through Stripe, not Zelle/PayPal/in-person/other.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    if (uiState.isLoadingStripeReconcile && uiState.stripeReconcile == null) {
                        CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
                    }
                    uiState.stripeErrorMessage?.let { message ->
                        Text(
                            text = message,
                            color = AccentRed,
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(SpacingMedium)
                                .semantics { contentDescription = "stripe reconcile error: $message" },
                        )
                    }
                }
            }

            uiState.stripeReconcile?.let { reconcile ->
                item {
                    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = SpacingMedium)) {
                        StatRow("Stripe tax collected", reconcile.total_tax_collected)
                        StatRow("Stripe transactions", reconcile.transaction_count.toString())
                    }
                }
                if (reconcile.by_jurisdiction.isEmpty()) {
                    item {
                        Text(
                            "No Stripe-collected tax in this range.",
                            modifier = Modifier.padding(SpacingMedium),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                } else {
                    items(reconcile.by_jurisdiction.entries.toList(), key = { it.key }) { (jurisdiction, amount) ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(jurisdiction)
                            Text(amount)
                        }
                        HorizontalDivider()
                    }
                }
            }
        }
    }
}

@Composable
private fun StatRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = SpacingSmall),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.titleMedium)
    }
}
