package app.logand.mobile.ui.admin.invoices

import android.content.Context
import android.content.Intent
import app.logand.mobile.ui.shared.FileShareController

// Persists a downloaded invoice PDF or payment-proof file's raw bytes
// and builds a share Intent for it, mirroring the web app's plain
// browser-download links (openInvoicePdf / paymentProofFileUrl in
// Invoices.tsx) but via Android's share sheet since there is no browser
// download manager here. Reuses the shared FileShareController plumbing
// (see that class's doc comment) rather than re-deriving the
// cache-dir -> FileProvider -> Intent steps a second time.
class InvoiceDownloadController(context: Context) {
    private val shared = FileShareController(context)

    fun writeAndBuildPdfShareIntent(invoiceId: String, bytes: ByteArray): Intent =
        shared.writeAndBuildShareIntent(
            cacheSubdir = "invoices_export",
            fileName = "invoice-$invoiceId.pdf",
            bytes = bytes,
            mimeType = "application/pdf",
        )

    // contentType comes straight from PaymentProofSummary.content_type
    // (server-recorded at upload time, e.g. "application/pdf" or
    // "image/png") -- used both as the share Intent's mime type and to
    // pick a matching file extension so the receiving app's own
    // type-sniffing has something sane to work with.
    fun writeAndBuildProofShareIntent(
        invoiceId: String,
        proofId: String,
        contentType: String,
        bytes: ByteArray,
    ): Intent {
        val extension = when (contentType) {
            "application/pdf" -> "pdf"
            "image/png" -> "png"
            "image/jpeg" -> "jpg"
            else -> "bin"
        }
        return shared.writeAndBuildShareIntent(
            cacheSubdir = "invoices_export",
            fileName = "payment-proof-$invoiceId-$proofId.$extension",
            bytes = bytes,
            mimeType = contentType,
        )
    }
}
