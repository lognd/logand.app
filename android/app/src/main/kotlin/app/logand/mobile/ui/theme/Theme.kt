package app.logand.mobile.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
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
        content = content,
    )
}
