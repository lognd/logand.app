package app.logand.mobile.ui.admin.bom

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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.logand.core.model.BomSummary
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall

// Mirrors Bom.tsx's AdminBom: a list of BOMs, each expandable to its own
// detail (material lines, cost breakdown, consume-stock flow).
@Composable
fun BomScreen(viewModel: BomViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var showCreateDialog by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxWidth()) {
            Row(modifier = Modifier.padding(SpacingMedium)) {
                Button(
                    onClick = { showCreateDialog = true },
                    modifier = Modifier.semantics { contentDescription = "new bill of materials" },
                ) { Text("New bill of materials") }
            }

            uiState.errorMessage?.let { message ->
                Text(
                    text = message,
                    color = AccentRed,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .semantics { contentDescription = "bom error: $message" },
                )
            }

            if (uiState.isLoading && uiState.boms.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize()) {
                    CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
                }
            } else if (uiState.boms.isEmpty()) {
                Text(
                    "No bills of materials yet.",
                    modifier = Modifier.padding(SpacingMedium),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                LazyColumn {
                    items(uiState.boms, key = { it.id }) { bom ->
                        BomRow(
                            bom = bom,
                            expanded = uiState.selectedBomId == bom.id,
                            onToggle = {
                                viewModel.selectBom(if (uiState.selectedBomId == bom.id) null else bom.id)
                            },
                        )
                        if (uiState.selectedBomId == bom.id) {
                            BomDetail(bom = bom, viewModel = viewModel)
                        }
                        HorizontalDivider()
                    }
                }
            }
        }
    }

    if (showCreateDialog) {
        CreateBomDialog(
            viewModel = viewModel,
            onDismiss = { showCreateDialog = false },
            onSubmitted = { showCreateDialog = false },
        )
    }
}

@Composable
private fun BomRow(bom: BomSummary, expanded: Boolean, onToggle: () -> Unit) {
    TextButton(
        onClick = onToggle,
        modifier = Modifier
            .fillMaxWidth()
            .semantics { contentDescription = "${if (expanded) "collapse" else "expand"} ${bom.name}" },
    ) {
        Text(bom.name, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun BomDetail(bom: BomSummary, viewModel: BomViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var selectedItemId by remember { mutableStateOf("") }
    var quantityPerUnit by remember { mutableStateOf("1") }
    var buildQuantity by remember { mutableStateOf("1") }
    var showConsumeConfirm by remember { mutableStateOf(false) }
    var consumeReason by remember { mutableStateOf("") }
    var showDeleteConfirm by remember { mutableStateOf(false) }

    val breakdown = uiState.costBreakdownsByBomId[bom.id]

    Column(modifier = Modifier.padding(SpacingMedium), verticalArrangement = Arrangement.spacedBy(SpacingSmall)) {
        Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
            OutlinedTextField(
                value = selectedItemId,
                onValueChange = { selectedItemId = it },
                label = { Text("Item ID to add") },
                singleLine = true,
                modifier = Modifier.semantics { contentDescription = "material item id input" },
            )
            OutlinedTextField(
                value = quantityPerUnit,
                onValueChange = { quantityPerUnit = it },
                label = { Text("Qty/unit") },
                singleLine = true,
            )
        }
        // Item picker helper: shows the fetched inventory items' names so
        // an admin can look up the id to paste above, since Compose has no
        // built-in dropdown as terse as the web's <select>.
        Text(
            uiState.inventoryItems.joinToString(", ") { "${it.name} (${it.id})" }
                .ifBlank { "No inventory items available." },
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Button(
            onClick = {
                val qty = quantityPerUnit.toIntOrNull() ?: 1
                viewModel.addMaterialLine(bom.id, selectedItemId.trim(), qty)
                selectedItemId = ""
                quantityPerUnit = "1"
            },
            enabled = selectedItemId.isNotBlank(),
        ) { Text("Add line") }

        OutlinedTextField(
            value = buildQuantity,
            onValueChange = {
                buildQuantity = it
                it.toIntOrNull()?.let { qty -> viewModel.loadCostBreakdown(bom.id, qty) }
            },
            label = { Text("Build quantity") },
            singleLine = true,
        )

        if (breakdown != null) {
            Column(modifier = Modifier.semantics { contentDescription = "bom cost breakdown" }) {
                breakdown.material_lines.forEach { line ->
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text("${line.item_name} x${line.quantity} = $${line.line_cost}")
                        TextButton(onClick = { viewModel.removeMaterialLine(bom.id, line.item_id) }) {
                            Text("Remove", color = AccentRed)
                        }
                    }
                }
                Text("Material: $${breakdown.material_cost}")
                Text("Labor: $${breakdown.labor_cost} (${breakdown.labor_hours} hrs)")
                Text("Overhead (${breakdown.overhead_percent}%): $${breakdown.overhead_cost}")
                Text(
                    "Total: $${breakdown.total_cost}",
                    style = MaterialTheme.typography.bodyLarge,
                )
            }
        }

        if (!showConsumeConfirm) {
            Button(onClick = { showConsumeConfirm = true }) { Text("Record a build (consume stock)") }
        } else {
            Text(
                "This will deduct stock for ${buildQuantity.toIntOrNull() ?: 1}x build(s) of " +
                    "${bom.name} from every material line above. This cannot be undone " +
                    "automatically.",
            )
            OutlinedTextField(
                value = consumeReason,
                onValueChange = { consumeReason = it },
                label = { Text("Reason (optional)") },
                singleLine = true,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                Button(
                    onClick = {
                        viewModel.consumeBom(bom.id, buildQuantity.toIntOrNull() ?: 1, consumeReason) {
                            showConsumeConfirm = false
                            consumeReason = ""
                        }
                    },
                    modifier = Modifier.semantics { contentDescription = "confirm consume" },
                ) { Text("Confirm consume") }
                Button(onClick = { showConsumeConfirm = false }) { Text("Cancel") }
            }
        }

        Button(onClick = { showDeleteConfirm = true }) { Text("Delete BOM", color = AccentRed) }
        if (showDeleteConfirm) {
            AlertDialog(
                onDismissRequest = { showDeleteConfirm = false },
                title = { Text("Delete ${bom.name}?") },
                confirmButton = {
                    Button(onClick = { viewModel.deleteBom(bom.id); showDeleteConfirm = false }) {
                        Text("Delete")
                    }
                },
                dismissButton = { Button(onClick = { showDeleteConfirm = false }) { Text("Cancel") } },
            )
        }
    }
}

@Composable
private fun CreateBomDialog(
    viewModel: BomViewModel,
    onDismiss: () -> Unit,
    onSubmitted: () -> Unit,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val form = uiState.createForm

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("New bill of materials") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                OutlinedTextField(
                    value = form.name,
                    onValueChange = { v -> viewModel.updateCreateForm { it.copy(name = v) } },
                    label = { Text("Name") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = form.laborHours,
                    onValueChange = { v -> viewModel.updateCreateForm { it.copy(laborHours = v) } },
                    label = { Text("Labor hours") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = form.laborRate,
                    onValueChange = { v -> viewModel.updateCreateForm { it.copy(laborRate = v) } },
                    label = { Text("Rate ($/hr)") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = form.overheadPercent,
                    onValueChange = { v -> viewModel.updateCreateForm { it.copy(overheadPercent = v) } },
                    label = { Text("Overhead %") },
                    singleLine = true,
                )
                uiState.errorMessage?.let { message -> Text(message, color = AccentRed) }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    viewModel.createBom()
                    onSubmitted()
                },
                enabled = !uiState.isSubmitting,
                modifier = Modifier.semantics { contentDescription = "create bom" },
            ) { Text("Create") }
        },
        dismissButton = { Button(onClick = onDismiss) { Text("Cancel") } },
    )
}
