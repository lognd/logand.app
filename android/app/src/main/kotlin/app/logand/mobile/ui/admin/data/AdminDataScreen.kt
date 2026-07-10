package app.logand.mobile.ui.admin.data

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import app.logand.core.model.AdminAuditLogEntry
import app.logand.core.model.TableColumn
import app.logand.mobile.ui.theme.AccentGreen
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall
import androidx.lifecycle.compose.collectAsStateWithLifecycle

// The generic "absolute power, but never a corrupt state" table browser
// -- mirrors frontend/src/app/routes/admin/AdminData.tsx exactly: pick a
// table, page its rows, open a row to edit or delete it (both gated
// behind an explicit confirm step), or open the change log to revert a
// past write (also gated). Rows are schemaless (AdminTableRow / JsonObject)
// so every column shown here comes from the live TableColumn schema, never
// a hardcoded field list.
@Composable
fun AdminDataScreen(viewModel: AdminDataViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) { viewModel.loadTables() }

    Scaffold { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxSize()) {
            uiState.errorMessage?.let { message ->
                Text(
                    text = message,
                    color = AccentRed,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .semantics { contentDescription = "admin data error: $message" },
                )
            }

            Column(modifier = Modifier.padding(SpacingMedium)) {
                Text("Data browser", style = MaterialTheme.typography.titleLarge)
                Text(
                    "Direct table access for one-off fixes. Every write is validated " +
                        "against real database constraints and recorded below, so it can " +
                        "always be reverted.",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )

                Row(modifier = Modifier.padding(top = SpacingSmall)) {
                    OutlinedButton(onClick = { viewModel.toggleChangeLog() }) {
                        Text(if (uiState.showChangeLog) "Hide change log" else "Show change log")
                    }
                }
            }

            if (uiState.showChangeLog) {
                ChangeLogSection(
                    changes = uiState.changes,
                    isLoading = uiState.isLoadingChanges,
                    confirmingRevertId = uiState.confirmingRevertId,
                    isSubmittingRevert = uiState.isSubmittingRevert,
                    hasMoreChanges = uiState.hasMoreChanges,
                    onRequestRevert = viewModel::requestRevert,
                    onCancelRevert = viewModel::cancelRevert,
                    onConfirmRevert = viewModel::submitRevert,
                    onNextPage = viewModel::nextChangesPage,
                    onPreviousPage = viewModel::previousChangesPage,
                )
                HorizontalDivider()
            }

            TableSelector(
                tables = uiState.tables,
                selectedTable = uiState.selectedTable,
                onSelect = viewModel::selectTable,
            )

            if (uiState.selectedTable != null) {
                Row(
                    modifier = Modifier.padding(horizontal = SpacingMedium),
                    horizontalArrangement = Arrangement.spacedBy(SpacingSmall),
                ) {
                    OutlinedButton(
                        onClick = viewModel::openInsertDialog,
                        modifier = Modifier.semantics { contentDescription = "insert new row" },
                    ) {
                        Text("Insert row")
                    }
                    OutlinedButton(onClick = viewModel::previousRowsPage) { Text("Prev page") }
                    OutlinedButton(
                        onClick = viewModel::nextRowsPage,
                        enabled = uiState.hasMoreRows,
                    ) { Text("Next page") }
                }
            }

            if (uiState.isLoadingRows && uiState.rows.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize()) {
                    CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
                }
            } else if (uiState.selectedTable != null && uiState.rows.isEmpty()) {
                Text(
                    "No rows in this table.",
                    modifier = Modifier.padding(SpacingMedium),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                LazyColumn {
                    items(uiState.rows, key = { it.rowId() }) { row ->
                        val rowId = row.rowId()
                        Column {
                            Button(
                                onClick = {
                                    viewModel.selectRow(if (uiState.selectedRowId == rowId) null else rowId)
                                },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = SpacingMedium, vertical = SpacingSmall)
                                    .semantics { contentDescription = "row $rowId" },
                            ) {
                                Text(rowId, modifier = Modifier.fillMaxWidth())
                            }
                            if (uiState.selectedRowId == rowId) {
                                RowEditor(viewModel = viewModel)
                            }
                            HorizontalDivider()
                        }
                    }
                }
            }
        }
    }

    if (uiState.insertDialogOpen && uiState.selectedTable != null) {
        InsertRowDialog(viewModel = viewModel)
    }
}

@Composable
private fun TableSelector(
    tables: List<String>,
    selectedTable: String?,
    onSelect: (String?) -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    Box(modifier = Modifier.padding(SpacingMedium)) {
        OutlinedButton(
            onClick = { expanded = true },
            modifier = Modifier.semantics { contentDescription = "select table" },
        ) {
            Text(selectedTable ?: "Select a table...")
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            tables.forEach { name ->
                DropdownMenuItem(
                    text = { Text(name) },
                    onClick = {
                        onSelect(name)
                        expanded = false
                    },
                )
            }
        }
    }
}

@Composable
private fun RowEditor(viewModel: AdminDataViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val row = uiState.selectedRow

    Column(modifier = Modifier.padding(SpacingMedium)) {
        if (uiState.isLoadingRow || row == null) {
            CircularProgressIndicator(modifier = Modifier.padding(SpacingSmall))
            return@Column
        }

        uiState.schema.forEach { column: TableColumn ->
            OutlinedTextField(
                value = uiState.edits[column.name] ?: formatAdminValue(row[column.name]),
                onValueChange = { viewModel.updateEditField(column.name, it) },
                label = { Text(column.name) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }

        if (!uiState.confirmingUpdate) {
            Button(
                onClick = viewModel::requestConfirmUpdate,
                enabled = uiState.changedKeys.isNotEmpty(),
                modifier = Modifier
                    .padding(top = SpacingSmall)
                    .semantics { contentDescription = "review changes" },
            ) {
                Text("Review changes")
            }
        } else {
            Column(modifier = Modifier.padding(top = SpacingSmall)) {
                Text("Confirm the following change" + if (uiState.changedKeys.size > 1) "s:" else ":")
                uiState.changedKeys.forEach { key ->
                    Text(
                        "$key: ${formatAdminValue(row[key])} -> ${uiState.edits[key]}",
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
                Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                    Button(
                        onClick = viewModel::submitUpdate,
                        enabled = !uiState.isSubmittingUpdate,
                        modifier = Modifier.semantics { contentDescription = "confirm change" },
                    ) { Text("Confirm change") }
                    OutlinedButton(onClick = viewModel::cancelConfirmUpdate) { Text("Cancel") }
                }
            }
        }

        if (!uiState.confirmingDelete) {
            OutlinedButton(
                onClick = viewModel::requestConfirmDelete,
                modifier = Modifier
                    .padding(top = SpacingSmall)
                    .semantics { contentDescription = "delete row ${row.rowId()}" },
            ) {
                Text("Delete row", color = AccentRed)
            }
        } else {
            Column(modifier = Modifier.padding(top = SpacingSmall)) {
                Text(
                    "This will permanently delete this row from ${uiState.selectedTable}. " +
                        "It can be restored afterward from the change log.",
                    color = AccentRed,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                    Button(
                        onClick = viewModel::submitDelete,
                        enabled = !uiState.isSubmittingDelete,
                        modifier = Modifier.semantics { contentDescription = "confirm delete" },
                    ) { Text("Confirm delete") }
                    OutlinedButton(onClick = viewModel::cancelConfirmDelete) { Text("Cancel") }
                }
            }
        }
    }
}

@Composable
private fun InsertRowDialog(viewModel: AdminDataViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    AlertDialog(
        onDismissRequest = viewModel::closeInsertDialog,
        title = { Text("Insert row into ${uiState.selectedTable}") },
        text = {
            Column {
                uiState.schema.forEach { column: TableColumn ->
                    OutlinedTextField(
                        value = uiState.insertValues[column.name] ?: "",
                        onValueChange = { viewModel.updateInsertField(column.name, it) },
                        label = { Text(column.name) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        },
        confirmButton = {
            Button(
                onClick = viewModel::submitInsert,
                enabled = !uiState.isSubmittingInsert,
                modifier = Modifier.semantics { contentDescription = "save new row" },
            ) { Text("Insert") }
        },
        dismissButton = {
            Button(onClick = viewModel::closeInsertDialog) { Text("Cancel") }
        },
    )
}

@Composable
private fun ChangeLogSection(
    changes: List<AdminAuditLogEntry>,
    isLoading: Boolean,
    confirmingRevertId: String?,
    isSubmittingRevert: Boolean,
    hasMoreChanges: Boolean,
    onRequestRevert: (String) -> Unit,
    onCancelRevert: () -> Unit,
    onConfirmRevert: (String) -> Unit,
    onNextPage: () -> Unit,
    onPreviousPage: () -> Unit,
) {
    Column(modifier = Modifier.padding(SpacingMedium)) {
        Text("Change log", style = MaterialTheme.typography.titleMedium)
        if (isLoading && changes.isEmpty()) {
            CircularProgressIndicator(modifier = Modifier.padding(SpacingSmall))
        } else if (changes.isEmpty()) {
            Text("No changes recorded yet.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            changes.forEach { entry ->
                Column(modifier = Modifier.padding(vertical = SpacingSmall)) {
                    Text(
                        "${entry.created_at} -- ${entry.action} on " +
                            "${entry.target_table}/${entry.target_id}",
                        style = MaterialTheme.typography.labelMedium,
                    )
                    entry.before_state?.let {
                        Text(
                            "before: ${it}",
                            color = AccentRed,
                            style = MaterialTheme.typography.labelMedium,
                            modifier = Modifier.horizontalScroll(rememberScrollState()),
                        )
                    }
                    entry.after_state?.let {
                        Text(
                            "after: ${it}",
                            color = AccentGreen,
                            style = MaterialTheme.typography.labelMedium,
                            modifier = Modifier.horizontalScroll(rememberScrollState()),
                        )
                    }

                    if (confirmingRevertId == entry.id) {
                        Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                            Button(
                                onClick = { onConfirmRevert(entry.id) },
                                enabled = !isSubmittingRevert,
                                modifier = Modifier.semantics { contentDescription = "confirm revert" },
                            ) { Text("Confirm revert") }
                            OutlinedButton(onClick = onCancelRevert) { Text("Cancel") }
                        }
                    } else {
                        OutlinedButton(
                            onClick = { onRequestRevert(entry.id) },
                            modifier = Modifier.semantics {
                                contentDescription = "revert change ${entry.id}"
                            },
                        ) { Text("Revert this change") }
                    }
                    HorizontalDivider()
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                OutlinedButton(onClick = onPreviousPage) { Text("Prev page") }
                OutlinedButton(onClick = onNextPage, enabled = hasMoreChanges) { Text("Next page") }
            }
        }
    }
}
