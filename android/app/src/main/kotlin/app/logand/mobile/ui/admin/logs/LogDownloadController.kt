package app.logand.mobile.ui.admin.logs

import android.content.Context
import android.content.Intent
import app.logand.mobile.ui.shared.FileShareController

// Persists a downloaded server log file's raw bytes and builds a share
// Intent for it, via the shared FileShareController (see that class's
// doc comment for why content:// via FileProvider is required). Kept as
// its own plain, Context-scoped class (not tangled into the ViewModel or
// Composable) matching ReceiptCaptureController/ApkInstaller's
// established shape.
class LogDownloadController(context: Context) {
    private val shared = FileShareController(context)

    fun writeAndBuildShareIntent(fileName: String, bytes: ByteArray): Intent =
        shared.writeAndBuildShareIntent(
            cacheSubdir = "logs_export",
            fileName = fileName,
            bytes = bytes,
            mimeType = "application/octet-stream",
        )
}
