package app.logand.mobile.ui.shared

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider

// Shared "downloaded bytes -> cache dir -> FileProvider content:// Uri ->
// share Intent" plumbing, factored out of what was originally
// admin/logs/LogDownloadController so admin screens that download other
// kinds of files (invoice PDFs, payment-proof images) don't duplicate it
// -- a plain file:// Uri handed to another app throws
// FileUriExposedException on API 24+, content:// via FileProvider is the
// only way across the process boundary. Every caller shares the SAME
// FileProvider authority declared once in AndroidManifest.xml/
// file_paths.xml.
class FileShareController(private val context: Context) {
    // cacheSubdir keeps each caller's exported files in their own
    // cacheDir bucket (must have a matching cache-path entry in
    // file_paths.xml) so a log export and an invoice PDF never collide
    // on the same file name.
    fun writeAndBuildShareIntent(
        cacheSubdir: String,
        fileName: String,
        bytes: ByteArray,
        mimeType: String = "application/octet-stream",
    ): Intent {
        val dir = context.cacheDir.resolve(cacheSubdir).apply { mkdirs() }
        // Sanitize -- fileName comes from the backend's own listing, but
        // nothing about this client enforces it never contains a path
        // separator before it becomes part of a filesystem path.
        val safeName = fileName.replace(Regex("[^A-Za-z0-9._-]"), "_")
        val file = dir.resolve(safeName)
        file.writeBytes(bytes)
        val uri = FileProvider.getUriForFile(context, "app.logand.mobile.fileprovider", file)
        return Intent(Intent.ACTION_SEND).apply {
            type = mimeType
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
    }
}
