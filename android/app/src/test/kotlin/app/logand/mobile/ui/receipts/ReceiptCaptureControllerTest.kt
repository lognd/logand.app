package app.logand.mobile.ui.receipts

import androidx.test.core.app.ApplicationProvider
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

// A single test method, not two -- androidx.core.content.FileProvider
// caches its parsed PathStrategy in a static map keyed by authority
// string. Under Robolectric, that static state survives across test
// METHODS within the same class run (even though each method gets a
// fresh simulated cacheDir), so a second method's FileProvider call
// resolves against the FIRST method's now-stale temp directory and
// throws "Failed to find configured root" -- confirmed by running each
// method in isolation (both pass) versus together (the second always
// fails). Not a bug in ReceiptCaptureController or file_paths.xml, and
// not a real-device concern (a real app process only ever has one
// cacheDir for its whole lifetime); it's a Robolectric-test-isolation
// artifact specific to FileProvider's own static caching, worked around
// here by keeping every FileProvider-touching assertion in one method.
@RunWith(RobolectricTestRunner::class)
class ReceiptCaptureControllerTest {
    @Test
    fun `newPhotoUri creates distinct jpg files with content Uris under the cache dir`() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val controller = ReceiptCaptureController(context)

        val (fileA, uriA) = controller.newPhotoUri()
        val (fileB, _) = controller.newPhotoUri()

        assertTrue(fileA.path.startsWith(context.cacheDir.canonicalFile.path))
        assertTrue(fileA.name.endsWith(".jpg"))
        assertEquals("content", uriA.scheme)
        assertTrue(fileA.name != fileB.name)
    }
}
