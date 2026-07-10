package app.logand.mobile.ui.admin.logs

import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.logand.core.model.LogFileInfo
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall
import java.text.DateFormat
import java.util.Date

// Read-only server log browser -- mirrors
// frontend/src/app/routes/admin/AdminLogs.tsx: rotated log files with a
// download-to-share action, plus a live tail that auto-refreshes every
// 10 seconds. Nothing here ever triggers pruning/rotation server-side.
@Composable
fun AdminLogsScreen(viewModel: AdminLogsViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val downloadController = remember { LogDownloadController(context) }

    LaunchedEffect(Unit) {
        viewModel.loadFiles()
        viewModel.startTailAutoRefresh()
    }

    Scaffold { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState()),
        ) {
            uiState.errorMessage?.let { message ->
                Text(
                    text = message,
                    color = AccentRed,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .semantics { contentDescription = "admin logs error: $message" },
                )
            }

            Text(
                "Server logs",
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(SpacingMedium),
            )

            Text(
                "Log files",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(horizontal = SpacingMedium),
            )
            if (uiState.isLoadingFiles && uiState.files.isEmpty()) {
                CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
            } else if (uiState.files.isEmpty()) {
                Text(
                    "No log files yet.",
                    modifier = Modifier.padding(SpacingMedium),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                uiState.files.forEach { file ->
                    LogFileRow(
                        file = file,
                        isDownloading = uiState.isDownloading,
                        onDownload = {
                            viewModel.downloadFile(file.name) { bytes ->
                                if (bytes != null) {
                                    val intent = downloadController.writeAndBuildShareIntent(
                                        file.name,
                                        bytes,
                                    )
                                    context.startActivity(
                                        Intent.createChooser(intent, "Share ${file.name}"),
                                    )
                                }
                            }
                        },
                    )
                }
            }

            Text(
                "Live tail (last 200 lines)",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(SpacingMedium),
            )
            if (uiState.isLoadingTail && uiState.tailLines.isEmpty()) {
                CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
            } else {
                Text(
                    text = uiState.tailLines.joinToString("\n"),
                    fontFamily = FontFamily.Monospace,
                    style = MaterialTheme.typography.labelMedium,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .horizontalScroll(rememberScrollState()),
                )
            }
        }
    }
}

@Composable
private fun LogFileRow(file: LogFileInfo, isDownloading: Boolean, onDownload: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Column {
            Text(file.name, style = MaterialTheme.typography.bodyLarge)
            Text(
                "${file.size_bytes / 1024} KB -- " +
                    DateFormat.getDateTimeInstance().format(Date((file.modified_at * 1000).toLong())),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Button(
            onClick = onDownload,
            enabled = !isDownloading,
            modifier = Modifier.semantics { contentDescription = "download ${file.name}" },
        ) {
            Text("Download")
        }
    }
}
