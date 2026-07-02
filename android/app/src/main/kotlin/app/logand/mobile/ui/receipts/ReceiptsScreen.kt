package app.logand.mobile.ui.receipts

import android.net.Uri
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.logand.core.model.Receipt
import app.logand.mobile.ui.theme.AccentGreen
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall
import kotlinx.coroutines.launch

@Composable
fun ReceiptsScreen(viewModel: ReceiptsViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val captureController = remember { ReceiptCaptureController(context) }
    var pendingPhoto by remember { mutableStateOf<Pair<java.io.File, Uri>?>(null) }
    var showMetadataDialog by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) { viewModel.load() }

    val takePicture = rememberLauncherForActivityResult(
        ActivityResultContracts.TakePicture(),
    ) { success ->
        if (success) {
            showMetadataDialog = true
        } else {
            pendingPhoto = null
        }
    }

    val requestCameraPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            val photo = captureController.newPhotoUri()
            pendingPhoto = photo
            takePicture.launch(photo.second)
        }
    }

    Scaffold(
        floatingActionButton = {
            FloatingActionButton(
                onClick = { requestCameraPermission.launch(android.Manifest.permission.CAMERA) },
                modifier = Modifier.semantics { contentDescription = "capture receipt photo" },
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
                        .semantics { contentDescription = "receipts error: $message" },
                )
            }

            if (uiState.isLoading && uiState.receipts.isEmpty()) {
                Box(modifier = Modifier.fillMaxSize()) {
                    CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
                }
            } else if (uiState.receipts.isEmpty()) {
                Text(
                    "No receipts captured yet.",
                    modifier = Modifier.padding(SpacingMedium),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                LazyColumn {
                    items(uiState.receipts, key = { it.id }) { receipt ->
                        ReceiptRow(receipt = receipt, onDelete = { viewModel.delete(receipt.id) })
                        HorizontalDivider()
                    }
                }
            }
        }
    }

    if (showMetadataDialog && pendingPhoto != null) {
        ReceiptMetadataDialog(
            onCancel = {
                showMetadataDialog = false
                pendingPhoto = null
            },
            onSave = { vendor, amount, category, note ->
                val (file, _) = pendingPhoto!!
                scope.launch {
                    viewModel.capture(
                        fileBytes = file.readBytes(),
                        filename = file.name,
                        mimeType = "image/jpeg",
                        vendor = vendor,
                        amount = amount,
                        category = category,
                        note = note,
                    ) { showMetadataDialog = false; pendingPhoto = null }
                }
            },
            isUploading = uiState.isUploading,
        )
    }
}

@Composable
private fun ReceiptRow(receipt: Receipt, onDelete: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column {
            Text(
                receipt.vendor ?: "(no vendor yet)",
                style = MaterialTheme.typography.bodyLarge,
            )
            Text(
                listOfNotNull(receipt.amount, receipt.category).joinToString(" -- ")
                    .ifBlank { receipt.captured_at },
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (receipt.reconciled_budget_entry_id != null) {
                Text("Reconciled", style = MaterialTheme.typography.labelMedium, color = AccentGreen)
            }
        }
        IconButton(
            onClick = onDelete,
            modifier = Modifier.semantics { contentDescription = "delete receipt" },
        ) {
            Icon(Icons.Default.Delete, contentDescription = null, tint = AccentRed)
        }
    }
}

@Composable
private fun ReceiptMetadataDialog(
    onCancel: () -> Unit,
    onSave: (vendor: String?, amount: String?, category: String?, note: String?) -> Unit,
    isUploading: Boolean,
) {
    // Every field here is optional -- "snap a photo, done" is a complete,
    // valid submission on its own (see api/receipts.py's doc comment);
    // this dialog exists to let the user add detail WHEN they have time,
    // not to gate the upload on it.
    var vendor by remember { mutableStateOf("") }
    var amount by remember { mutableStateOf("") }
    var category by remember { mutableStateOf("") }
    var note by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text("Receipt captured") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(SpacingSmall)) {
                Text(
                    "Add details now, or just save -- you can reconcile this later.",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedTextField(
                    value = vendor,
                    onValueChange = { vendor = it },
                    label = { Text("Vendor (optional)") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = amount,
                    onValueChange = { amount = it },
                    label = { Text("Amount (optional)") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = category,
                    onValueChange = { category = it },
                    label = { Text("Category (optional)") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = note,
                    onValueChange = { note = it },
                    label = { Text("Note (optional)") },
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    onSave(
                        vendor.ifBlank { null },
                        amount.ifBlank { null },
                        category.ifBlank { null },
                        note.ifBlank { null },
                    )
                },
                enabled = !isUploading,
                modifier = Modifier.semantics { contentDescription = "save receipt" },
            ) {
                Text(if (isUploading) "Saving..." else "Save")
            }
        },
        dismissButton = {
            Button(onClick = onCancel, enabled = !isUploading) { Text("Discard") }
        },
    )
}
