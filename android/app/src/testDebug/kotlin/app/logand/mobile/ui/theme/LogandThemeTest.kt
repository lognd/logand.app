package app.logand.mobile.ui.theme

import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import app.logand.core.ApiClient
import app.logand.mobile.ui.login.LoginScreen
import app.logand.mobile.ui.login.LoginViewModel
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.GraphicsMode

// Regression tests for the black-on-black home (login) screen:
// MaterialTheme alone does NOT provide LocalContentColor (its default is
// Color.Black), so before LogandTheme owned a root Surface, any screen
// composed without its own Surface/Scaffold -- LoginScreen, the first
// thing the app shows -- rendered black text on the dark window
// background. These pin the theme's content-color contract so that
// can't quietly come back.
// LEGACY graphics, explicitly -- Robolectric 4.10+ defaults to NATIVE,
// whose native runtime has no linux-aarch64 build (this dev host; see
// README's aarch64 section), failing every test at ComposeView creation
// with "native runtime is not supported". These tests assert composition
// state (content color, node presence), never rendered pixels, so the
// legacy shadow graphics are fully sufficient.
@RunWith(RobolectricTestRunner::class)
@GraphicsMode(GraphicsMode.Mode.LEGACY)
class LogandThemeTest {
    @get:Rule
    val compose = createComposeRule()

    @Test
    fun `content color inside the theme is FgPrimary, never black`() {
        var contentColor: Color? = null
        var background: Color? = null
        compose.setContent {
            LogandTheme {
                contentColor = LocalContentColor.current
                background = MaterialTheme.colorScheme.background
            }
        }
        compose.waitForIdle()

        assertEquals(FgPrimary, contentColor)
        assertNotEquals(Color.Black, contentColor)
        // The pair that actually matters for readability: light-on-dark.
        assertEquals(BgPrimary, background)
    }

    @Test
    fun `login screen heading renders under the theme`() {
        // A dead client is fine -- LoginScreen makes no calls on
        // composition, only login() does (see LoginViewModelTest for the
        // real HTTP coverage).
        val viewModel = LoginViewModel(
            apiClient = { ApiClient(baseUrl = "http://localhost:1/") },
        )
        compose.setContent {
            LogandTheme {
                LoginScreen(viewModel)
            }
        }
        compose.waitForIdle()

        compose.onNodeWithContentDescription("logand.app").assertIsDisplayed()
        compose.onNodeWithContentDescription("sign in").assertIsDisplayed()
    }
}
