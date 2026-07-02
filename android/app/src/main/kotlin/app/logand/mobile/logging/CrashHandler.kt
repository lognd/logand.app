package app.logand.mobile.logging

import app.logand.core.logging.FileLogger

// Installed once, from LogandApplication.onCreate() -- catches an
// uncaught exception on ANY thread, logs the full stack trace to the
// same rotating file the rest of the app writes to (so a crash and the
// events leading up to it end up in one place, not scattered), then
// hands off to whatever handler was already installed (the platform's
// own, which shows the "app has stopped" dialog and actually terminates
// the process) -- this deliberately does NOT swallow the crash or try to
// keep the app running in a broken state, only ensures it's logged
// first. "If anything ever crashes, I want to be able to find exactly
// what happened through the logs."
class CrashHandler(
    private val logger: FileLogger,
    private val previousHandler: Thread.UncaughtExceptionHandler?,
) : Thread.UncaughtExceptionHandler {
    override fun uncaughtException(thread: Thread, throwable: Throwable) {
        try {
            logger.error("Crash", "uncaught exception on thread ${thread.name}", throwable)
        } finally {
            previousHandler?.uncaughtException(thread, throwable)
        }
    }

    companion object {
        fun install(logger: FileLogger) {
            val previous = Thread.getDefaultUncaughtExceptionHandler()
            Thread.setDefaultUncaughtExceptionHandler(CrashHandler(logger, previous))
        }
    }
}
