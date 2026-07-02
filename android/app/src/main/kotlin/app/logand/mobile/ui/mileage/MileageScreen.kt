package app.logand.mobile.ui.mileage

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.logand.core.model.MileageEntry
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall
import java.time.LocalDate

@Composable
fun MileageScreen(viewModel: MileageViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var showAddDialog by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold(
        floatingActionButton = {
            FloatingActionButton(
                onClick = { showAddDialog = true },
                modifier = Modifier.semantics { contentDescription = "log a trip" },
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
                        .semantics { contentDescription = "mileage error: $message" },
                )
            }

            if (uiState.isLoading && uiState.entries.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize()) {
                    CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
                }
            } else if (uiState.entries.isEmpty()) {
                Text(
                    "No trips logged yet.",
                    modifier = Modifier.padding(SpacingMedium),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                LazyColumn {
                    items(uiState.entries, key = { it.id }) { entry ->
                        MileageRow(entry = entry, onDelete = { viewModel.delete(entry.id) })
                        HorizontalDivider()
                    }
                }
            }
        }
    }

    if (showAddDialog) {
        AddMileageDialog(
            viewModel = viewModel,
            onDismiss = { showAddDialog = false },
            onSubmitted = { showAddDialog = false },
        )
    }
}

@Composable
private fun MileageRow(entry: MileageEntry, onDelete: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column {
            Text("${entry.vehicle} -- ${entry.distance} mi", style = MaterialTheme.typography.bodyLarge)
            Text(
                entry.occurred_on + (entry.purpose?.let { " -- $it" } ?: ""),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        IconButton(
            onClick = onDelete,
            modifier = Modifier.semantics {
                contentDescription = "delete trip on ${entry.occurred_on}"
            },
        ) {
            Icon(Icons.Default.Delete, contentDescription = null, tint = AccentRed)
        }
    }
}

@Composable
private fun AddMileageDialog(
    viewModel: MileageViewModel,
    onDismiss: () -> Unit,
    onSubmitted: () -> Unit,
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val form = uiState.form

    LaunchedEffect(Unit) {
        if (form.occurredOn.isBlank()) {
            viewModel.updateForm { it.copy(occurredOn = LocalDate.now().toString()) }
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Log a trip") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                OutlinedTextField(
                    value = form.vehicle,
                    onValueChange = { v -> viewModel.updateForm { it.copy(vehicle = v) } },
                    label = { Text("Vehicle") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = form.occurredOn,
                    onValueChange = { v -> viewModel.updateForm { it.copy(occurredOn = v) } },
                    label = { Text("Date (YYYY-MM-DD)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )

                DistanceInputModeSelector(
                    mode = form.inputMode,
                    onModeChange = { m -> viewModel.updateForm { it.copy(inputMode = m) } },
                )

                if (form.inputMode == DistanceInputMode.RAW_DISTANCE) {
                    OutlinedTextField(
                        value = form.distance,
                        onValueChange = { v -> viewModel.updateForm { it.copy(distance = v) } },
                        label = { Text("Distance (miles)") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                } else {
                    OutlinedTextField(
                        value = form.startOdometer,
                        onValueChange = { v -> viewModel.updateForm { it.copy(startOdometer = v) } },
                        label = { Text("Start odometer") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = form.endOdometer,
                        onValueChange = { v -> viewModel.updateForm { it.copy(endOdometer = v) } },
                        label = { Text("End odometer") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }

                OutlinedTextField(
                    value = form.purpose,
                    onValueChange = { v -> viewModel.updateForm { it.copy(purpose = v) } },
                    label = { Text("Purpose (optional)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )

                Row(
                    verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
                    modifier = Modifier.semantics { contentDescription = "business trip toggle" },
                ) {
                    Checkbox(
                        checked = form.business,
                        onCheckedChange = { v -> viewModel.updateForm { it.copy(business = v) } },
                    )
                    Text("Business trip")
                }

                uiState.errorMessage?.let { message ->
                    Text(message, color = AccentRed)
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    viewModel.submit()
                    onSubmitted()
                },
                enabled = !uiState.isSubmitting,
                modifier = Modifier.semantics { contentDescription = "save trip" },
            ) {
                Text("Save")
            }
        },
        dismissButton = {
            Button(onClick = onDismiss) { Text("Cancel") }
        },
    )
}

@Composable
private fun DistanceInputModeSelector(
    mode: DistanceInputMode,
    onModeChange: (DistanceInputMode) -> Unit,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(SpacingSmall)) {
        DistanceInputMode.entries.forEach { candidate ->
            val selected = candidate == mode
            Button(
                onClick = { onModeChange(candidate) },
                colors = if (selected) {
                    androidx.compose.material3.ButtonDefaults.buttonColors()
                } else {
                    androidx.compose.material3.ButtonDefaults.outlinedButtonColors()
                },
                modifier = Modifier.semantics {
                    contentDescription = when (candidate) {
                        DistanceInputMode.RAW_DISTANCE -> "enter distance directly"
                        DistanceInputMode.ODOMETER_READINGS -> "enter odometer readings"
                    }
                },
            ) {
                Text(
                    when (candidate) {
                        DistanceInputMode.RAW_DISTANCE -> "Distance"
                        DistanceInputMode.ODOMETER_READINGS -> "Odometer"
                    }
                )
            }
        }
    }
}
