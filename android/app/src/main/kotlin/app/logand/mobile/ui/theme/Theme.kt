package app.logand.mobile.ui.theme

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

// Dark-only -- the web frontend's own tokens.css doc comment notes light
// theme is deferred there too; matching that rather than introducing a
// light variant the site itself doesn't have yet.
private val LogandColorScheme = darkColorScheme(
    primary = AccentOrange,
    onPrimary = BgPrimary,
    secondary = AccentAqua,
    onSecondary = BgPrimary,
    error = AccentRed,
    onError = BgPrimary,
    background = BgPrimary,
    onBackground = FgPrimary,
    surface = BgSecondary,
    onSurface = FgPrimary,
    surfaceVariant = BgSecondary,
    onSurfaceVariant = FgMuted,
    outline = BorderColor,
)

// RoundedCornerShape(4.dp) -- matches Tailwind's default `rounded`
// utility (0.25rem = 4px) used throughout the web frontend's
// BUTTON_CLASS/INPUT_CLASS (styles/a11y.ts), not Material's usual more
// rounded default.
private val LogandShapes = Shapes(
    extraSmall = RoundedCornerShape(4.dp),
    small = RoundedCornerShape(4.dp),
    medium = RoundedCornerShape(4.dp),
    large = RoundedCornerShape(4.dp),
)

@Composable
fun LogandTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = LogandColorScheme,
        typography = LogandTypography,
        shapes = LogandShapes,
    ) {
        // The Surface is load-bearing, not decoration: MaterialTheme alone
        // does NOT provide LocalContentColor (its default is Color.Black),
        // so any screen composed without a Surface/Scaffold between itself
        // and the theme rendered black text on this app's dark window
        // background -- exactly what LoginScreen's heading did (bare
        // Column, no Scaffold; the logged-in tabs never showed it only
        // because MainTabs' own Scaffold set a content color). Owning the
        // root Surface here means every current and future screen under
        // this theme -- previews and UI tests included -- starts from
        // background/onBackground instead of each screen re-adding its
        // own.
        Surface(
            modifier = Modifier.fillMaxSize(),
            color = MaterialTheme.colorScheme.background,
            content = content,
        )
    }
}
