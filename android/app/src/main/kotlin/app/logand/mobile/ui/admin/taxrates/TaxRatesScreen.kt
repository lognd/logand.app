package app.logand.mobile.ui.admin.taxrates

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.logand.core.model.TaxRule
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall

private val TAX_TYPES = listOf("sales", "use", "import_duty")

private fun formatPercent(rate: String): String {
    val value = rate.toDoubleOrNull() ?: return rate
    // Trims trailing zeros (0.070 -> 7%) without losing precision for odd
    // rates (0.0725 -> 7.25%), same formatting as the web app's TaxRates.tsx.
    val percent = value * 100
    val text = "%.4f".format(percent).trimEnd('0').trimEnd('.')
    return "$text%"
}

// Admin surface for the tax_rules knowledge base
// (docs/design/16-sales-tax.md) -- the mobile mirror of
// frontend/src/app/routes/admin/TaxRates.tsx. Every rate needs a
// government-source citation URL; Claude only classifies items, it never
// sets the rate.
@Composable
fun TaxRatesScreen(viewModel: TaxRatesViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxWidth()) {
            uiState.errorMessage?.let { message ->
                Text(
                    text = message,
                    color = AccentRed,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .semantics { contentDescription = "tax rates error: $message" },
                )
            }

            if (uiState.isLoading && uiState.rules.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize()) {
                    CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
                }
            } else {
                LazyColumn(modifier = Modifier.weight(1f, fill = false)) {
                    if (uiState.rules.isEmpty()) {
                        item {
                            Text(
                                "No rates entered yet.",
                                modifier = Modifier.padding(SpacingMedium),
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    items(uiState.rules, key = { it.id }) { rule ->
                        TaxRuleRow(rule)
                        HorizontalDivider()
                    }
                }
                AddRuleForm(viewModel)
            }
        }
    }
}

@Composable
private fun TaxRuleRow(rule: TaxRule) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
    ) {
        Text(
            "${rule.jurisdiction} -- ${rule.tax_type} -- ${rule.category}",
            style = MaterialTheme.typography.bodyLarge,
        )
        Text(
            "${formatPercent(rule.rate)} -- ${rule.source}",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun AddRuleForm(viewModel: TaxRatesViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val form = uiState.form

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(SpacingMedium),
        verticalArrangement = Arrangement.spacedBy(SpacingSmall),
    ) {
        Text("Add rate", style = MaterialTheme.typography.titleMedium)
        OutlinedTextField(
            value = form.jurisdiction,
            onValueChange = { v -> viewModel.updateForm { it.copy(jurisdiction = v) } },
            label = { Text("Jurisdiction (e.g. US-TN)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = form.taxType,
            onValueChange = { v -> viewModel.updateForm { it.copy(taxType = v) } },
            label = { Text("Tax type (${TAX_TYPES.joinToString(", ")})") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = form.category,
            onValueChange = { v -> viewModel.updateForm { it.copy(category = v) } },
            label = { Text("Category") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = form.percent,
            onValueChange = { v -> viewModel.updateForm { it.copy(percent = v) } },
            label = { Text("Rate (percent, e.g. 7 for 7%)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = form.source,
            onValueChange = { v -> viewModel.updateForm { it.copy(source = v) } },
            label = { Text("Source (e.g. TN DOR 2026)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = form.citationUrl,
            onValueChange = { v -> viewModel.updateForm { it.copy(citationUrl = v) } },
            label = { Text("Government source URL (required)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
            Button(
                onClick = { viewModel.addRule() },
                enabled = !uiState.isSubmitting,
                modifier = Modifier.semantics { contentDescription = "add tax rate" },
            ) { Text(if (uiState.isSubmitting) "Adding..." else "Add rate") }
        }
    }
}
