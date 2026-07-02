package app.logand.mobile.logging

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import app.logand.core.logging.FileLogger

// "I can retrieve logs from android" -- concatenates every log file
// (live + rotated backups, newest first, see FileLogger.allLogFiles)
// into one temp file and opens the system share sheet, same idea as the
// frontend's "download logs" button and the backend's admin log
// download route, just via Android's own sharing mechanism instead of a
// browser download. Uses the SAME FileProvider authority already
// declared for receipt-photo capture (AndroidManifest.xml/file_paths.xml)
// -- a plain file:// Uri handed to another app (the share target) throws
// FileUriExposedException on API 24+, content:// via FileProvider is the
// only way to hand a file across the process boundary.
object ShareLogsAction {
    fun share(context: Context, logger: FileLogger) {
        val exportDir = context.cacheDir.resolve("logs_export").apply { mkdirs() }
        val exportFile = exportDir.resolve("logand-android-log.txt")
        exportFile.writeText(
            logger.allLogFiles().joinToString("\n\n---\n\n") { it.readText() },
        )

        val uri = FileProvider.getUriForFile(
            context,
            "app.logand.mobile.fileprovider",
            exportFile,
        )
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = "text/plain"
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(Intent.createChooser(intent, "Send app logs"))
    }
}
