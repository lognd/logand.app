package app.logand.mobile.ui.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import java.io.File

// Writes a downloaded APK to this app's own cache dir and builds the
// ACTION_VIEW install Intent for it -- mirrors ReceiptCaptureController's
// shape (plain, Context-scoped, easily unit-testable class, not tangled
// into a ViewModel or Composable) rather than a ViewModel holding a
// Context reference across configuration changes. Never installs
// silently: the returned Intent always surfaces the system installer's
// own confirmation UI, and the caller is expected to route through
// canRequestInstalls()/unknownSourcesSettingsIntent() first.
class ApkInstaller(private val context: Context) {

    /** True if the OS will let this app prompt for an APK install right
     * now. API 26+ gates "install unknown apps" per source app via a
     * Settings toggle, not a runtime permission dialog -- if this is
     * false, route the user to [unknownSourcesSettingsIntent] first. */
    fun canRequestInstalls(): Boolean = context.packageManager.canRequestPackageInstalls()

    /** Deep link into the system settings screen where the user grants
     * this app permission to install unknown APKs. */
    fun unknownSourcesSettingsIntent(): Intent =
        Intent(
            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            Uri.parse("package:${context.packageName}"),
        )

    /** Persists [apkBytes] under the FileProvider-exposed cache dir
     * (see file_paths.xml's apk_updates entry) and returns an
     * ACTION_VIEW install Intent for it. The caller must still call
     * startActivity on the result -- this never launches anything
     * itself, so a UI layer can prompt the user before doing so. */
    fun writeAndBuildInstallIntent(apkBytes: ByteArray, versionTag: String): Intent {
        // .canonicalFile -- see ReceiptCaptureController's own doc
        // comment on why an un-canonicalized cacheDir can make
        // FileProvider's SimplePathStrategy wrongly reject a real file
        // under its configured root.
        val dir = File(context.cacheDir.canonicalFile, "updates").apply { mkdirs() }
        // Sanitize the version tag before it becomes part of a
        // filesystem path -- a release tag is normally just "vX.Y.Z",
        // but nothing about GitHub enforces that at the API level.
        val safeVersionTag = versionTag.replace(Regex("[^A-Za-z0-9._-]"), "_")
        val file = File(dir, "logand-$safeVersionTag.apk")
        file.writeBytes(apkBytes)
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        return Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
    }
}
