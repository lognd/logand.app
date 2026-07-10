package app.logand.mobile.ui.update

import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.logand.mobile.ui.theme.AccentRed
import app.logand.mobile.ui.theme.SpacingMedium
import app.logand.mobile.ui.theme.SpacingSmall

// Sits above the tab content in AppNavHost's MainTabs -- checks for an
// update once per composition, then renders one of: nothing (no update /
// still checking), an offer banner, a downloading indicator, or an
// error. Never auto-installs: the system installer Intent is only ever
// fired from the explicit "Install" button below, and even then the
// system's own confirmation UI is the last word.
@Composable
fun UpdateBanner(viewModel: UpdateViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val installer = remember { ApkInstaller(context) }
    // Local, one-shot Compose state (not ViewModel state) -- the moment
    // this becomes non-null the LaunchedEffect below fires the install
    // flow once and immediately clears it back to null, so it never
    // needs to survive/replay across a configuration change the way
    // uiState deliberately does.
    var pendingInstallIntent by remember { mutableStateOf<Intent?>(null) }

    LaunchedEffect(Unit) { viewModel.checkForUpdate() }

    LaunchedEffect(pendingInstallIntent) {
        val intent = pendingInstallIntent ?: return@LaunchedEffect
        if (installer.canRequestInstalls()) {
            context.startActivity(intent)
        } else {
            // Never install silently -- if the OS blocks this app from
            // prompting an install right now, send the user to the
            // settings screen that lets them allow it, instead of
            // failing invisibly.
            context.startActivity(installer.unknownSourcesSettingsIntent())
        }
        pendingInstallIntent = null
    }

    uiState.errorMessage?.let { message ->
        Surface(color = MaterialTheme.colorScheme.errorContainer) {
            Text(
                text = message,
                color = AccentRed,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(SpacingMedium)
                    .semantics { contentDescription = "update error: $message" },
            )
        }
        return
    }

    if (uiState.downloading) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(SpacingMedium),
            horizontalArrangement = Arrangement.spacedBy(SpacingSmall),
        ) {
            CircularProgressIndicator()
            Text("Downloading update...", style = MaterialTheme.typography.bodyMedium)
        }
        return
    }

    val update = uiState.available ?: return
    Surface(color = MaterialTheme.colorScheme.secondaryContainer) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = SpacingMedium, vertical = SpacingSmall),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                "Update ${update.version} available",
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier.semantics { contentDescription = "update available: ${update.version}" },
            )
            Row {
                TextButton(
                    onClick = viewModel::decline,
                    modifier = Modifier.semantics { contentDescription = "later" },
                ) { Text("Later") }
                Button(
                    onClick = {
                        viewModel.download { bytes, version ->
                            pendingInstallIntent = installer.writeAndBuildInstallIntent(bytes, version)
                        }
                    },
                    modifier = Modifier.semantics { contentDescription = "download and install update" },
                ) { Text("Update") }
            }
        }
    }
}
