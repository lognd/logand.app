package app.logand.mobile

import android.app.Application
import app.logand.mobile.data.AppContainer

class LogandApplication : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }
}
