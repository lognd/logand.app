package app.logand.mobile.ui.admin.taxclassifications

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
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.logand.core.model.TaxClassification
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall

// Admin review queue for the do-as-we-go item tax classifier -- the
// mobile mirror of
// frontend/src/app/routes/admin/TaxClassifications.tsx. Confirming or
// overriding a classification changes financial records, so both actions
// require an explicit confirm step here (AlertDialog), never a one-tap
// write -- see TaxClassificationsViewModel's own doc comment.
@Composable
fun TaxClassificationsScreen(viewModel: TaxClassificationsViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxWidth()) {
            Row(
                modifier = Modifier.padding(horizontal = SpacingMedium, vertical = SpacingSmall),
                horizontalArrangement = Arrangement.spacedBy(SpacingSmall),
            ) {
                FilterChip(
                    selected = uiState.statusFilter == "pending",
                    onClick = { viewModel.setStatusFilter("pending") },
                    label = { Text("Pending review") },
                    modifier = Modifier.semantics { contentDescription = "filter: pending review" },
                )
                FilterChip(
                    selected = uiState.statusFilter == "all",
                    onClick = { viewModel.setStatusFilter("all") },
                    label = { Text("All") },
                    modifier = Modifier.semantics { contentDescription = "filter: all" },
                )
            }

            uiState.errorMessage?.let { message ->
                Text(
                    text = message,
                    color = AccentRed,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .semantics { contentDescription = "tax classifications error: $message" },
                )
            }

            if (uiState.isLoading && uiState.classifications.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize()) {
                    CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
                }
            } else if (uiState.classifications.isEmpty()) {
                Text(
                    "No classifications need review.",
                    modifier = Modifier.padding(SpacingMedium),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                LazyColumn {
                    items(uiState.classifications, key = { it.id }) { classification ->
                        ClassificationRow(classification = classification, viewModel = viewModel)
                        HorizontalDivider()
                    }
                }
            }
        }
    }

    uiState.confirmingKey?.let { key ->
        AlertDialog(
            onDismissRequest = viewModel::cancelConfirm,
            title = { Text("Confirm classification") },
            text = { Text("Accept this classification as-is? This updates a financial record.") },
            confirmButton = {
                TextButton(
                    onClick = { viewModel.submitConfirm(key) },
                    enabled = !uiState.isSubmittingConfirm,
                    modifier = Modifier.semantics { contentDescription = "confirm classification" },
                ) { Text(if (uiState.isSubmittingConfirm) "Confirming..." else "Confirm") }
            },
            dismissButton = {
                TextButton(onClick = viewModel::cancelConfirm) { Text("Cancel") }
            },
        )
    }

    if (uiState.confirmingOverride) {
        AlertDialog(
            onDismissRequest = viewModel::cancelConfirmOverride,
            title = { Text("Save override") },
            text = { Text("Replace this classification with your override? This updates a financial record.") },
            confirmButton = {
                TextButton(
                    onClick = { viewModel.submitOverride() },
                    enabled = !uiState.isSubmittingOverride,
                    modifier = Modifier.semantics { contentDescription = "confirm override" },
                ) { Text(if (uiState.isSubmittingOverride) "Saving..." else "Save") }
            },
            dismissButton = {
                TextButton(onClick = viewModel::cancelConfirmOverride) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun ClassificationRow(
    classification: TaxClassification,
    viewModel: TaxClassificationsViewModel,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val isOverriding = uiState.overridingKey == classification.normalized_key

    Column(modifier = Modifier.fillMaxWidth().padding(SpacingMedium)) {
        Text(classification.description, style = MaterialTheme.typography.bodyLarge)
        Text(
            "${classification.category} -- taxable: ${if (classification.taxable) "yes" else "no"}" +
                (classification.hts_code?.let { " -- HTS $it" } ?: ""),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            "status: ${classification.status} -- source: ${classification.source}",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        classification.rationale?.let { rationale ->
            Text(
                rationale,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        if (classification.status == "pending") {
            Row(
                modifier = Modifier.padding(top = SpacingSmall),
                horizontalArrangement = Arrangement.spacedBy(SpacingSmall),
            ) {
                Button(
                    onClick = { viewModel.requestConfirm(classification.normalized_key) },
                    modifier = Modifier.semantics {
                        contentDescription = "confirm classification for ${classification.description}"
                    },
                ) { Text("Confirm") }
                Button(
                    onClick = {
                        if (isOverriding) viewModel.cancelOverrideForm()
                        else viewModel.openOverrideForm(classification)
                    },
                    modifier = Modifier.semantics {
                        contentDescription = "override classification for ${classification.description}"
                    },
                ) { Text(if (isOverriding) "Cancel override" else "Override") }
            }
        }

        if (isOverriding) {
            OverrideForm(viewModel)
        }
    }
}

@Composable
private fun OverrideForm(viewModel: TaxClassificationsViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val form = uiState.overrideForm

    Column(
        modifier = Modifier.fillMaxWidth().padding(top = SpacingSmall),
        verticalArrangement = Arrangement.spacedBy(SpacingSmall),
    ) {
        OutlinedTextField(
            value = form.category,
            onValueChange = { v -> viewModel.updateOverrideForm { it.copy(category = v) } },
            label = { Text("Category") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Row(
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Checkbox(
                checked = form.taxable,
                onCheckedChange = { v -> viewModel.updateOverrideForm { it.copy(taxable = v) } },
                modifier = Modifier.semantics { contentDescription = "taxable" },
            )
            Text("Taxable")
        }
        OutlinedTextField(
            value = form.htsCode,
            onValueChange = { v -> viewModel.updateOverrideForm { it.copy(htsCode = v) } },
            label = { Text("HTS code") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = { viewModel.requestConfirmOverride() },
            modifier = Modifier.semantics { contentDescription = "save override" },
        ) { Text("Save override") }
    }
}
