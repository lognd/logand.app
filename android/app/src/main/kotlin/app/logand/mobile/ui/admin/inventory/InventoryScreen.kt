package app.logand.mobile.ui.admin.inventory

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
import androidx.compose.material3.FloatingActionButton
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
import app.logand.core.model.InventoryItem
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall

// Mirrors AdminInventory.tsx: a list of items with inline unit-cost and
// quantity-adjust controls, plus a create-item form reachable from the FAB.
@Composable
fun InventoryScreen(viewModel: InventoryViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var showCreateDialog by remember { mutableStateOf(false) }
    var adjustTargetItem by remember { mutableStateOf<InventoryItem?>(null) }
    var unitCostTargetItem by remember { mutableStateOf<InventoryItem?>(null) }
    var historyTargetItemId by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold(
        floatingActionButton = {
            FloatingActionButton(
                onClick = { showCreateDialog = true },
                modifier = Modifier.semantics { contentDescription = "add inventory item" },
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
                        .semantics { contentDescription = "inventory error: $message" },
                )
            }

            if (uiState.isLoading && uiState.items.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize()) {
                    CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
                }
            } else if (uiState.items.isEmpty()) {
                Text(
                    "No inventory items yet.",
                    modifier = Modifier.padding(SpacingMedium),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                LazyColumn {
                    items(uiState.items, key = { it.id }) { item ->
                        InventoryRow(
                            item = item,
                            onAdjust = { adjustTargetItem = item },
                            onEditUnitCost = { unitCostTargetItem = item },
                            onShowHistory = {
                                historyTargetItemId = item.id
                                viewModel.loadAdjustments(item.id)
                            },
                            onDelete = { viewModel.deleteItem(item.id) },
                        )
                        HorizontalDivider()
                    }
                }
            }
        }
    }

    if (showCreateDialog) {
        CreateItemDialog(
            viewModel = viewModel,
            onDismiss = { showCreateDialog = false },
            onSubmitted = { showCreateDialog = false },
        )
    }

    adjustTargetItem?.let { item ->
        AdjustQuantityDialog(
            item = item,
            onDismiss = { adjustTargetItem = null },
            onConfirm = { delta, reason ->
                viewModel.adjustQuantity(item.id, delta, reason)
                adjustTargetItem = null
            },
        )
    }

    unitCostTargetItem?.let { item ->
        UnitCostDialog(
            item = item,
            onDismiss = { unitCostTargetItem = null },
            onConfirm = { cost ->
                viewModel.setUnitCost(item.id, cost)
                unitCostTargetItem = null
            },
        )
    }

    historyTargetItemId?.let { itemId ->
        AdjustmentHistoryDialog(
            entries = uiState.adjustmentsByItemId[itemId] ?: emptyList(),
            onDismiss = { historyTargetItemId = null },
        )
    }
}

@Composable
private fun InventoryRow(
    item: InventoryItem,
    onAdjust: () -> Unit,
    onEditUnitCost: () -> Unit,
    onShowHistory: () -> Unit,
    onDelete: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
    ) {
        Text("${item.name} -- qty ${item.quantity}", style = MaterialTheme.typography.bodyLarge)
        Text(
            item.tags.joinToString(", ").ifBlank { "no tags" } +
                (item.unit_cost?.let { " -- $$it" } ?: " -- no unit cost set"),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
            TextButton(
                onClick = onAdjust,
                modifier = Modifier.semantics { contentDescription = "adjust quantity for ${item.name}" },
            ) { Text("Adjust") }
            TextButton(onClick = onShowHistory) { Text("History") }
            TextButton(
                onClick = onEditUnitCost,
                modifier = Modifier.semantics { contentDescription = "set unit cost for ${item.name}" },
            ) { Text("Unit cost") }
            TextButton(onClick = onDelete) { Text("Delete", color = AccentRed) }
        }
    }
}

@Composable
private fun CreateItemDialog(
    viewModel: InventoryViewModel,
    onDismiss: () -> Unit,
    onSubmitted: () -> Unit,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val form = uiState.createForm

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add inventory item") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                OutlinedTextField(
                    value = form.name,
                    onValueChange = { v -> viewModel.updateCreateForm { it.copy(name = v) } },
                    label = { Text("Name") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = form.quantity,
                    onValueChange = { v -> viewModel.updateCreateForm { it.copy(quantity = v) } },
                    label = { Text("Quantity") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = form.locationId,
                    onValueChange = { v -> viewModel.updateCreateForm { it.copy(locationId = v) } },
                    label = { Text("Location ID") },
                    singleLine = true,
                )
                uiState.errorMessage?.let { message -> Text(message, color = AccentRed) }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    viewModel.createItem()
                    onSubmitted()
                },
                enabled = !uiState.isSubmitting,
                modifier = Modifier.semantics { contentDescription = "save inventory item" },
            ) { Text("Save") }
        },
        dismissButton = { Button(onClick = onDismiss) { Text("Cancel") } },
    )
}

// Mirrors AdjustQuantityControl.tsx: shows the resolved before/after
// quantity diff before the confirm button is enabled, and refuses a
// projected-negative quantity client-side too.
@Composable
private fun AdjustQuantityDialog(
    item: InventoryItem,
    onDismiss: () -> Unit,
    onConfirm: (delta: Int, reason: String) -> Unit,
) {
    var deltaText by remember { mutableStateOf("") }
    var reason by remember { mutableStateOf("") }

    val parsedDelta = deltaText.toIntOrNull()
    val hasValidDelta = parsedDelta != null && parsedDelta != 0
    val projected = item.quantity + (parsedDelta ?: 0)
    val wouldGoNegative = hasValidDelta && projected < 0

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Adjust quantity for ${item.name}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                OutlinedTextField(
                    value = deltaText,
                    onValueChange = { deltaText = it },
                    label = { Text("Change by (+5 or -3)") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = reason,
                    onValueChange = { reason = it },
                    label = { Text("Reason") },
                    singleLine = true,
                )
                if (hasValidDelta) {
                    Text(
                        "Quantity will change from ${item.quantity} to $projected" +
                            if (wouldGoNegative) " -- not allowed, can't go below zero" else "",
                        color = if (wouldGoNegative) AccentRed else MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.semantics { contentDescription = "quantity diff" },
                    )
                }
            }
        },
        confirmButton = {
            Button(
                onClick = { onConfirm(parsedDelta!!, reason.trim()) },
                enabled = hasValidDelta && !wouldGoNegative && reason.isNotBlank(),
                modifier = Modifier.semantics { contentDescription = "confirm adjustment" },
            ) { Text("Confirm adjustment") }
        },
        dismissButton = { Button(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun UnitCostDialog(
    item: InventoryItem,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    var value by remember { mutableStateOf(item.unit_cost ?: "") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Set unit cost for ${item.name}") },
        text = {
            OutlinedTextField(
                value = value,
                onValueChange = { value = it },
                label = { Text("Unit cost") },
                singleLine = true,
            )
        },
        confirmButton = {
            Button(
                onClick = { onConfirm(value.trim()) },
                enabled = value.isNotBlank(),
            ) { Text("Save") }
        },
        dismissButton = { Button(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun AdjustmentHistoryDialog(
    entries: List<app.logand.core.model.InventoryAdjustment>,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Adjustment history") },
        text = {
            if (entries.isEmpty()) {
                Text("No adjustments recorded yet.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                    entries.forEach { adj ->
                        Column {
                            Text("${adj.quantity_before} -> ${adj.quantity_after} (${if (adj.delta > 0) "+" else ""}${adj.delta})")
                            Text(
                                adj.reason,
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        },
        confirmButton = { Button(onClick = onDismiss) { Text("Close") } },
    )
}
