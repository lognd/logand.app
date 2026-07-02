package app.logand.core.logging

import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

enum class LogLevel { DEBUG, INFO, WARN, ERROR }

// Pure java.io.File based (no android.* imports) -- lives in :core, not
// :app, specifically so it's testable as a plain JVM unit test (see
// FileLoggerTest) the same way the rest of :core already is, rather than
// needing an instrumented/Robolectric test just to prove file rotation
// works. :app's LogandApplication supplies the real device directory
// (Context.filesDir/logs) at construction time.
//
// Mirrors the backend's logging design (backend/src/logand_backend/
// logging/) at a scale appropriate for one device's local log, not a
// server's: a bounded chain of numbered backups (app.log, app.log.1,
// app.log.2, ...) instead of the backend's calendar-bucketed exponential
// retention -- a single phone generates a tiny fraction of a server's log
// volume, so the meaningful "never overflow" guarantee here is just a
// hard file-count x max-size cap, not a thinning schedule.
class FileLogger(
    private val logDir: File,
    private val maxBytesPerFile: Long = 512 * 1024,
    private val maxBackupFiles: Int = 5,
) {
    private val liveFile: File
        get() = File(logDir, "app.log")

    private val dateFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSSXXX", Locale.US)

    fun log(level: LogLevel, tag: String, message: String, throwable: Throwable? = null) {
        logDir.mkdirs()
        rotateIfNeeded()
        val timestamp = dateFormat.format(Date())
        val line = buildString {
            append(timestamp)
            append(" [")
            append(level.name)
            append("] ")
            append(tag)
            append(": ")
            append(message)
            if (throwable != null) {
                append('\n')
                append(throwable.stackTraceToString())
            }
            append('\n')
        }
        liveFile.appendText(line)
    }

    fun debug(tag: String, message: String) = log(LogLevel.DEBUG, tag, message)

    fun info(tag: String, message: String) = log(LogLevel.INFO, tag, message)

    fun warn(tag: String, message: String) = log(LogLevel.WARN, tag, message)

    fun error(tag: String, message: String, throwable: Throwable? = null) =
        log(LogLevel.ERROR, tag, message, throwable)

    /** The live log file plus every rotated backup, for a "share my logs"
     * action (see :app's ShareLogsAction) -- newest first. */
    fun allLogFiles(): List<File> {
        val files = mutableListOf<File>()
        if (liveFile.exists()) files.add(liveFile)
        for (i in 1..maxBackupFiles) {
            val backup = File(logDir, "app.log.$i")
            if (backup.exists()) files.add(backup)
        }
        return files
    }

    private fun rotateIfNeeded() {
        if (!liveFile.exists() || liveFile.length() < maxBytesPerFile) return

        // Oldest backup beyond the cap is dropped first, then every
        // remaining backup shifts up by one index, then the live file
        // becomes app.log.1 -- classic logrotate-style generational
        // rotation, applied in descending order so no rename ever
        // overwrites a file it hasn't shifted out of the way yet.
        val oldestBeyondCap = File(logDir, "app.log.$maxBackupFiles")
        if (oldestBeyondCap.exists()) oldestBeyondCap.delete()

        for (i in maxBackupFiles - 1 downTo 1) {
            val src = File(logDir, "app.log.$i")
            if (src.exists()) src.renameTo(File(logDir, "app.log.${i + 1}"))
        }
        liveFile.renameTo(File(logDir, "app.log.1"))
    }
}
