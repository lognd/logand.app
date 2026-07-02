package app.logand.mobile.ui.receipts

import android.content.Context
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.File
import java.util.UUID

// Creates the cache-dir file + content:// Uri the system camera app
// writes a photo into -- separated from the Composable/ViewModel so it's
// plain, easily-unit-testable (Robolectric) logic rather than tangled
// into a Composable's side-effect handling.
class ReceiptCaptureController(private val context: Context) {
    fun newPhotoUri(): Pair<File, Uri> {
        // .canonicalFile -- FileProvider's SimplePathStrategy resolves
        // res/xml/file_paths.xml's cache-path root via
        // context.cacheDir.canonicalFile internally, so an un-canonicalized
        // cacheDir here (which can legitimately differ by a symlink hop,
        // e.g. a /tmp -> /private/tmp-style indirection some hosts and
        // Robolectric's own sandbox use) makes it look like this file
        // falls outside the configured root even though it's the exact
        // same real directory -- confirmed by a real test failure
        // (IllegalArgumentException: "Failed to find configured root")
        // before this fix.
        val dir = File(context.cacheDir.canonicalFile, "receipts").apply { mkdirs() }
        val file = File(dir, "${UUID.randomUUID()}.jpg")
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        return file to uri
    }
}
