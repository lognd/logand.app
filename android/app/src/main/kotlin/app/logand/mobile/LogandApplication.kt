package app.logand.mobile

import android.app.Application
import app.logand.mobile.data.AppContainer
import app.logand.mobile.logging.CrashHandler

class LogandApplication : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        // Installed as early as possible in the app's lifetime -- any
        // uncaught exception on any thread from this point on gets
        // logged before the app actually dies.
        CrashHandler.install(container.logger)
        container.logger.info("App", "app started")
    }
}
