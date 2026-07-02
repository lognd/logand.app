package app.logand.mobile.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.sp
import app.logand.mobile.R

// Real JetBrains Mono (variable-weight TTF, SIL OFL 1.1 license, bundled
// at res/font/jetbrains_mono.ttf) -- the same monospace typeface the web
// frontend uses (see frontend/tailwind.config.ts's fontFamily.mono),
// not a generic system-monospace substitute. "keeping the same style as
// the website" was explicit -- this is the one asset that most directly
// carries that identity over.
val JetBrainsMono = FontFamily(Font(R.font.jetbrains_mono))

private fun mono(size: Int, lineHeight: Int) = TextStyle(
    fontFamily = JetBrainsMono,
    fontSize = size.sp,
    lineHeight = lineHeight.sp,
)

// Body text >= 16sp everywhere -- matches the web frontend's own
// accessibility bar (docs/design/09-design-system.md: "minimum body
// text size" alongside the 44x44 tap-target rule mirrored in
// Dimens.kt::MinTouchTarget).
val LogandTypography = Typography(
    headlineSmall = mono(24, 30),
    titleLarge = mono(20, 26),
    titleMedium = mono(18, 24),
    bodyLarge = mono(16, 24),
    bodyMedium = mono(16, 22),
    labelLarge = mono(16, 20),
    labelMedium = mono(14, 18),
)
