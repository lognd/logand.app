package app.logand.mobile.ui.admin.version

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall

// Read-only server version display -- mirrors
// frontend/src/app/routes/admin/AdminVersion.tsx: app version/git commit/
// Python version/platform up top, then a searchable, scrollable list of
// every installed dependency (the map can be large, so it is rendered as
// a LazyColumn with a live filter field rather than one giant Column).
@Composable
fun AdminVersionScreen(viewModel: AdminVersionViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxSize()) {
            uiState.errorMessage?.let { message ->
                Text(
                    text = message,
                    color = AccentRed,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .semantics { contentDescription = "admin version error: $message" },
                )
            }

            if (uiState.isLoading && uiState.versionInfo == null) {
                CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
            }

            uiState.versionInfo?.let { info ->
                Column(modifier = Modifier.padding(SpacingMedium)) {
                    Text("Server version", style = MaterialTheme.typography.titleLarge)
                    VersionRow("App version", info.app_version)
                    VersionRow("Git commit", info.git_commit)
                    VersionRow("Python version", info.python_version)
                    VersionRow("Platform", info.platform)
                }

                Text(
                    "Dependencies (${info.dependencies.size})",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(horizontal = SpacingMedium),
                )
                OutlinedTextField(
                    value = uiState.dependencySearch,
                    onValueChange = viewModel::updateDependencySearch,
                    label = { Text("Search dependencies") },
                    singleLine = true,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .semantics { contentDescription = "search dependencies" },
                )

                val filtered = uiState.filteredDependencies
                if (filtered.isEmpty()) {
                    Text(
                        "No dependencies match this search.",
                        modifier = Modifier.padding(SpacingMedium),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    LazyColumn(modifier = Modifier.fillMaxWidth()) {
                        items(filtered, key = { it.first }) { (name, version) ->
                            DependencyRow(name = name, version = version)
                            HorizontalDivider()
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun VersionRow(label: String, value: String) {
    Text(
        "$label: $value",
        style = MaterialTheme.typography.bodyMedium,
        modifier = Modifier.padding(vertical = SpacingSmall / 4),
    )
}

@Composable
private fun DependencyRow(name: String, version: String) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
    ) {
        Text(name, style = MaterialTheme.typography.bodyLarge)
        Text(
            version,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
