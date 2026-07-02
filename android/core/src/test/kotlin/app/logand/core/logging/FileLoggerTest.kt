package app.logand.core.logging

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class FileLoggerTest {
    private fun tempDir(): File = kotlin.io.path.createTempDirectory().toFile()

    @Test
    fun `writes a log line to the live file`() {
        val dir = tempDir()
        val logger = FileLogger(dir)

        logger.info("Test", "hello world")

        val liveFile = File(dir, "app.log")
        assertTrue(liveFile.exists())
        assertTrue(liveFile.readText().contains("hello world"))
        assertTrue(liveFile.readText().contains("[INFO]"))
    }

    @Test
    fun `includes the full stack trace for an error with a throwable`() {
        val dir = tempDir()
        val logger = FileLogger(dir)

        logger.error("Test", "boom", RuntimeException("deliberate failure"))

        val content = File(dir, "app.log").readText()
        assertTrue(content.contains("[ERROR]"))
        assertTrue(content.contains("RuntimeException"))
        assertTrue(content.contains("deliberate failure"))
    }

    @Test
    fun `rotates to app-log-1 once the live file exceeds the size cap`() {
        val dir = tempDir()
        val logger = FileLogger(dir, maxBytesPerFile = 100, maxBackupFiles = 3)

        repeat(20) { logger.info("Test", "padding out the live log file quickly $it") }

        val rotated = File(dir, "app.log.1")
        assertTrue(rotated.exists(), "expected at least one rotation to have happened")
        val live = File(dir, "app.log")
        assertTrue(live.exists())
    }

    @Test
    fun `never keeps more than maxBackupFiles rotated files`() {
        val dir = tempDir()
        val logger = FileLogger(dir, maxBytesPerFile = 50, maxBackupFiles = 2)

        repeat(200) { logger.info("Test", "line number $it to force many rotations") }

        assertFalse(File(dir, "app.log.3").exists())
        val backupCount = (1..2).count { File(dir, "app.log.$it").exists() }
        assertTrue(backupCount in 1..2)
    }

    @Test
    fun `allLogFiles returns the live file first then rotated backups`() {
        val dir = tempDir()
        val logger = FileLogger(dir, maxBytesPerFile = 50, maxBackupFiles = 3)

        repeat(30) { logger.info("Test", "line $it") }

        val files = logger.allLogFiles()
        assertTrue(files.isNotEmpty())
        assertEquals("app.log", files.first().name)
    }
}
