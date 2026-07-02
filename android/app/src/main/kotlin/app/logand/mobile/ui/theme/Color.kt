package app.logand.mobile.ui.theme

import androidx.compose.ui.graphics.Color

// Gruvbox Dark -- exact same hex values as frontend/src/styles/tokens.css,
// see docs/design/09-design-system.md. Also mirrored in res/values/colors.xml
// for the pre-Compose window background; kept in both places since Compose
// code reads these Kotlin constants directly rather than round-tripping
// through Android resource IDs.
val BgPrimary = Color(0xFF282828)
val BgSecondary = Color(0xFF3C3836)
val FgPrimary = Color(0xFFEBDBB2)
val FgMuted = Color(0xFFA89984)
val AccentOrange = Color(0xFFFE8019)
val AccentGreen = Color(0xFFB8BB26)
val AccentRed = Color(0xFFFB4934)
val AccentAqua = Color(0xFF8EC07C)
val BorderColor = Color(0xFF504945)
