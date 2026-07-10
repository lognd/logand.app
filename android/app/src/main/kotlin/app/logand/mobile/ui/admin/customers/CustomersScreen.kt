package app.logand.mobile.ui.admin.customers

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
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
import app.logand.core.model.CustomerListItem
import app.logand.mobile.ui.theme.AccentGreen
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall

@Composable
fun CustomersScreen(viewModel: CustomersViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold { padding ->
        Column(modifier = Modifier.padding(padding).padding(horizontal = SpacingMedium)) {
            OutlinedTextField(
                value = uiState.query,
                onValueChange = { viewModel.search(it) },
                label = { Text("Search by email") },
                singleLine = true,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = SpacingMedium)
                    .semantics { contentDescription = "customer search" },
            )

            uiState.errorMessage?.let { message ->
                Text(
                    text = message,
                    color = AccentRed,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .semantics { contentDescription = "customers error: $message" },
                )
            }

            if (uiState.isLoading && uiState.customers.isEmpty()) {
                CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
            } else if (uiState.customers.isEmpty()) {
                Text(
                    "No customers match.",
                    modifier = Modifier.padding(SpacingMedium),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                LazyColumn {
                    items(uiState.customers, key = { it.id }) { customer ->
                        CustomerRow(
                            customer = customer,
                            isExpanded = uiState.selectedId == customer.id,
                            onToggle = { viewModel.toggleDetail(customer.id) },
                        )
                        if (uiState.selectedId == customer.id) {
                            CustomerDetailPanel(viewModel = viewModel, userId = customer.id)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun CustomerRow(customer: CustomerListItem, isExpanded: Boolean, onToggle: () -> Unit) {
    Button(
        onClick = onToggle,
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = SpacingSmall)
            .semantics { contentDescription = "toggle details for ${customer.email}" },
    ) {
        Text(customer.email, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun CustomerDetailPanel(viewModel: CustomersViewModel, userId: String) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var confirmingDeactivate by remember { mutableStateOf(false) }
    var resettingPassword by remember { mutableStateOf(false) }
    var newPassword by remember { mutableStateOf("") }

    Column(modifier = Modifier.padding(bottom = SpacingMedium)) {
        if (uiState.isDetailLoading) {
            CircularProgressIndicator(modifier = Modifier.padding(SpacingSmall))
            return@Column
        }
        val customer = uiState.selectedDetail ?: return@Column

        Text(
            "Account created ${customer.created_at}",
            style = MaterialTheme.typography.labelMedium,
        )
        Text(
            if (customer.disabled_at != null) {
                "Deactivated (${customer.disabled_at})"
            } else {
                "Active"
            },
            color = if (customer.disabled_at != null) AccentRed else AccentGreen,
            style = MaterialTheme.typography.bodyLarge,
        )

        if (customer.disabled_at != null) {
            Button(
                onClick = { viewModel.reactivate(userId) },
                enabled = !uiState.isActionInProgress,
                modifier = Modifier.semantics { contentDescription = "reactivate account" },
            ) {
                Text("Reactivate account")
            }
        } else if (!confirmingDeactivate) {
            Button(
                onClick = { confirmingDeactivate = true },
                modifier = Modifier.semantics { contentDescription = "deactivate account" },
            ) {
                Text("Deactivate account")
            }
        } else {
            Text(
                "This will immediately prevent ${customer.email} from logging in. " +
                    "Their data/invoices are untouched -- reactivate to restore login access " +
                    "at any time.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Button(
                onClick = {
                    viewModel.deactivate(userId) { confirmingDeactivate = false }
                },
                enabled = !uiState.isActionInProgress,
                modifier = Modifier.semantics { contentDescription = "confirm deactivate" },
            ) {
                Text("Confirm deactivate")
            }
            Button(onClick = { confirmingDeactivate = false }) { Text("Cancel") }
        }

        if (!resettingPassword) {
            Button(
                onClick = { resettingPassword = true },
                modifier = Modifier.semantics { contentDescription = "reset password" },
            ) {
                Text("Reset password")
            }
        } else {
            OutlinedTextField(
                value = newPassword,
                onValueChange = { newPassword = it },
                label = { Text("New password for ${customer.email}") },
                singleLine = true,
                modifier = Modifier.semantics { contentDescription = "new password field" },
            )
            Button(
                onClick = {
                    viewModel.resetPassword(userId, newPassword) { ok ->
                        if (ok) {
                            resettingPassword = false
                            newPassword = ""
                        }
                    }
                },
                enabled = newPassword.length >= 8 && !uiState.isActionInProgress,
                modifier = Modifier.semantics { contentDescription = "confirm reset password" },
            ) {
                Text(if (uiState.isActionInProgress) "Resetting..." else "Confirm reset")
            }
            Button(
                onClick = { resettingPassword = false; newPassword = "" },
            ) { Text("Cancel") }
        }
    }
}
