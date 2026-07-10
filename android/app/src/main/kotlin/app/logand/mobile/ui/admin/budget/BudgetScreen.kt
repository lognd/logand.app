package app.logand.mobile.ui.admin.budget

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.logand.core.model.BudgetEntry
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall
import kotlinx.coroutines.launch

private val ACCEPTED_EVIDENCE_MIME_TYPES = arrayOf("application/pdf", "image/png", "image/jpeg")

// Mirrors Budget.tsx's AdminBudget: list entries, create-entry form, and
// a per-row evidence file picker (PDF/PNG/JPEG). Also exposes the CSV
// export AdminApi already supports (see AdminApi.exportBudgetCsv) as a
// share-sheet action, since it's an accountant-handoff feature that's
// just as useful on mobile as on the web admin console.
@Composable
fun BudgetScreen(viewModel: BudgetViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var evidenceTargetEntryId by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) { viewModel.load() }

    val pickEvidence = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri: Uri? ->
        val entryId = evidenceTargetEntryId
        evidenceTargetEntryId = null
        if (uri == null || entryId == null) return@rememberLauncherForActivityResult
        scope.launch {
            val resolver = context.contentResolver
            val mimeType = resolver.getType(uri) ?: "application/octet-stream"
            var filename = "evidence"
            resolver.query(uri, null, null, null, null)?.use { cursor ->
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (nameIndex >= 0 && cursor.moveToFirst()) {
                    filename = cursor.getString(nameIndex) ?: filename
                }
            }
            val bytes = resolver.openInputStream(uri)?.use { it.readBytes() } ?: return@launch
            viewModel.uploadEvidence(entryId, bytes, filename, mimeType)
        }
    }

    val exportCsv = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("text/csv"),
    ) { uri: Uri? ->
        if (uri == null) return@rememberLauncherForActivityResult
        viewModel.exportCsv { bytes ->
            context.contentResolver.openOutputStream(uri)?.use { out ->
                out.write(bytes)
            }
        }
    }

    Scaffold { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxWidth()) {
            CreateEntryForm(viewModel = viewModel)

            Row(modifier = Modifier.padding(horizontal = SpacingMedium)) {
                Button(
                    onClick = { exportCsv.launch("budget-export.csv") },
                    enabled = !uiState.isExporting,
                    modifier = Modifier.semantics { contentDescription = "export budget csv" },
                ) { Text(if (uiState.isExporting) "Exporting..." else "Export CSV") }
            }

            uiState.errorMessage?.let { message ->
                Text(
                    text = message,
                    color = AccentRed,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .semantics { contentDescription = "budget error: $message" },
                )
            }

            if (uiState.isLoading && uiState.entries.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize()) {
                    CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
                }
            } else if (uiState.entries.isEmpty()) {
                Text(
                    "No budget entries yet.",
                    modifier = Modifier.padding(SpacingMedium),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                LazyColumn {
                    items(uiState.entries, key = { it.id }) { entry ->
                        BudgetRow(
                            entry = entry,
                            isUploading = uiState.uploadingEntryId == entry.id,
                            onAttachEvidence = {
                                evidenceTargetEntryId = entry.id
                                pickEvidence.launch(ACCEPTED_EVIDENCE_MIME_TYPES)
                            },
                        )
                        HorizontalDivider()
                    }
                }
            }
        }
    }
}

@Composable
private fun CreateEntryForm(viewModel: BudgetViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val form = uiState.createForm

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(SpacingMedium),
        verticalArrangement = Arrangement.spacedBy(SpacingSmall),
    ) {
        OutlinedTextField(
            value = form.amount,
            onValueChange = { v -> viewModel.updateCreateForm { it.copy(amount = v) } },
            label = { Text("Amount") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = form.category,
            onValueChange = { v -> viewModel.updateCreateForm { it.copy(category = v) } },
            label = { Text("Category") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = form.occurredOn,
            onValueChange = { v -> viewModel.updateCreateForm { it.copy(occurredOn = v) } },
            label = { Text("Date (YYYY-MM-DD)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = { viewModel.createEntry() },
            enabled = !uiState.isSubmitting,
            modifier = Modifier.semantics { contentDescription = "add budget entry" },
        ) { Text("Add entry") }
    }
}

@Composable
private fun BudgetRow(entry: BudgetEntry, isUploading: Boolean, onAttachEvidence: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column {
            Text("${entry.occurred_on} -- ${entry.category}", style = MaterialTheme.typography.bodyLarge)
            Text(
                "$${entry.amount}" + (entry.vendor?.let { " -- $it" } ?: ""),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        TextButton(
            onClick = onAttachEvidence,
            enabled = !isUploading,
            modifier = Modifier.semantics {
                contentDescription = "attach evidence for entry on ${entry.occurred_on}"
            },
        ) {
            Text(if (isUploading) "Uploading..." else "Attach evidence")
        }
    }
}
