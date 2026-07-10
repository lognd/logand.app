package app.logand.mobile.ui.admin.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
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

private val STATUS_LABEL = mapOf(
    "draft" to "Draft",
    "sent" to "Sent",
    "paid" to "Paid",
    "overdue" to "Overdue",
    "void" to "Void",
    "refunded" to "Refunded",
)

private val METHOD_LABEL = mapOf(
    "stripe" to "Stripe",
    "paypal" to "PayPal",
    "zelle" to "Zelle",
    "in_person" to "In person",
    "other" to "Other",
)

@Composable
fun StatsScreen(viewModel: StatsViewModel) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold { padding ->
        val stats = uiState.stats
        Column(
            modifier = Modifier
                .padding(padding)
                .padding(SpacingMedium),
        ) {
            if (uiState.isLoading && stats == null) {
                CircularProgressIndicator(modifier = Modifier.padding(SpacingMedium))
            }
            uiState.errorMessage?.let { message ->
                Text(
                    text = message,
                    color = AccentRed,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(SpacingMedium)
                        .semantics { contentDescription = "stats error: $message" },
                )
            }

            if (stats != null) {
                LazyColumn {
                    item {
                        Column(modifier = Modifier.fillMaxWidth()) {
                            StatTile("Total collected", stats.total_collected)
                            StatTile("Total refunded", stats.total_refunded)
                            StatTile("Net collected", stats.net_collected)
                            StatTile("Outstanding", stats.outstanding)

                            if (stats.open_disputes > 0) {
                                Text(
                                    "${stats.open_disputes} open Stripe dispute" +
                                        (if (stats.open_disputes == 1) "" else "s") +
                                        " need attention.",
                                    color = AccentRed,
                                    modifier = Modifier
                                        .padding(vertical = SpacingMedium)
                                        .semantics { contentDescription = "open disputes alert" },
                                )
                            }

                            Text(
                                "Invoices by status",
                                style = MaterialTheme.typography.titleMedium,
                                modifier = Modifier.padding(top = SpacingMedium),
                            )
                        }
                    }
                    items(stats.by_status.entries.toList()) { (status, breakdown) ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = SpacingSmall),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(STATUS_LABEL[status] ?: status)
                            Text("${breakdown.count} -- ${breakdown.amount_total}")
                        }
                        HorizontalDivider()
                    }
                    item {
                        Text(
                            "Payments by method",
                            style = MaterialTheme.typography.titleMedium,
                            modifier = Modifier.padding(top = SpacingMedium),
                        )
                    }
                    items(stats.by_payment_method.entries.toList()) { (method, breakdown) ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = SpacingSmall),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text(METHOD_LABEL[method] ?: method)
                            Text("${breakdown.count} -- ${breakdown.amount}")
                        }
                        HorizontalDivider()
                    }
                    item {
                        Column(modifier = Modifier.padding(top = SpacingMedium)) {
                            Text("Disputes", style = MaterialTheme.typography.titleMedium)
                            Text("Needs response: ${stats.disputes.needs_response}")
                            Text("Under review: ${stats.disputes.under_review}")
                            Text("Won: ${stats.disputes.won}")
                            Text("Lost: ${stats.disputes.lost}")
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun StatTile(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = SpacingSmall),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.titleMedium)
    }
}
