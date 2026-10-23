package com.dhruv.ecgmonitor

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight

// The monitor's whole palette. One accent, the trace; red only for alerts.
// Everything else is black, the grid, and two text greys.
object MonitorColors {
    // True black: the screen is OLED, and the trace should be the brightest thing on it.
    val Black = Color(0xFF000000)
    val GridMinor = Color(0xFF152A20)
    val GridMajor = Color(0xFF1F3A2C)
    // Bedside-monitor ECG green, kept soft rather than acid.
    val Trace = Color(0xFF6EE7A8)
    val Text = Color(0xFFE4ECE7)
    val TextMuted = Color(0xFF8B9B93)
    val Alert = Color(0xFFFF5A4E)
}

// Bundled so the device and Roborazzi draw the same glyphs (third_party/ibm-plex).
val PlexSans = FontFamily(
    Font(R.font.ibm_plex_sans_regular, FontWeight.Normal),
    Font(R.font.ibm_plex_sans_medium, FontWeight.Medium),
)
val PlexSansCondensed = FontFamily(
    Font(R.font.ibm_plex_sans_condensed_medium, FontWeight.Medium),
)

// Plex's figures are tabular by default; "tnum" guards against a font swap.
const val TABULAR = "tnum"

private fun TextStyle.plex() = copy(
    fontFamily = PlexSans,
    fontFeatureSettings = TABULAR,
    // Only Regular and Medium are bundled; anything heavier would be faked.
    fontWeight = if ((fontWeight ?: FontWeight.Normal) > FontWeight.Normal) FontWeight.Medium else FontWeight.Normal,
)

private val base = Typography()
private val MonitorTypography = Typography(
    displayLarge = base.displayLarge.plex(), displayMedium = base.displayMedium.plex(),
    displaySmall = base.displaySmall.plex(), headlineLarge = base.headlineLarge.plex(),
    headlineMedium = base.headlineMedium.plex(), headlineSmall = base.headlineSmall.plex(),
    titleLarge = base.titleLarge.plex(), titleMedium = base.titleMedium.plex(),
    titleSmall = base.titleSmall.plex(), bodyLarge = base.bodyLarge.plex(),
    bodyMedium = base.bodyMedium.plex(), bodySmall = base.bodySmall.plex(),
    labelLarge = base.labelLarge.plex(), labelMedium = base.labelMedium.plex(),
    labelSmall = base.labelSmall.plex(),
)

// Material 3 for its mechanics only. Every role maps onto the palette above,
// so no default purple can leak through, and surfaceTint is transparent so
// raised surfaces don't pick up a tonal tint.
private val MonitorColorScheme = darkColorScheme(
    primary = MonitorColors.Text, onPrimary = MonitorColors.Black,
    primaryContainer = MonitorColors.GridMajor, onPrimaryContainer = MonitorColors.Text,
    inversePrimary = MonitorColors.Black,
    secondary = MonitorColors.TextMuted, onSecondary = MonitorColors.Black,
    secondaryContainer = MonitorColors.GridMajor, onSecondaryContainer = MonitorColors.Text,
    tertiary = MonitorColors.TextMuted, onTertiary = MonitorColors.Black,
    tertiaryContainer = MonitorColors.GridMajor, onTertiaryContainer = MonitorColors.Text,
    background = MonitorColors.Black, onBackground = MonitorColors.Text,
    surface = MonitorColors.Black, onSurface = MonitorColors.Text,
    surfaceVariant = MonitorColors.Black, onSurfaceVariant = MonitorColors.TextMuted,
    surfaceTint = Color.Transparent,
    inverseSurface = MonitorColors.Text, inverseOnSurface = MonitorColors.Black,
    error = MonitorColors.Alert, onError = MonitorColors.Black,
    errorContainer = MonitorColors.Black, onErrorContainer = MonitorColors.Alert,
    outline = MonitorColors.TextMuted, outlineVariant = MonitorColors.GridMajor,
    scrim = MonitorColors.Black,
    surfaceBright = MonitorColors.Black, surfaceDim = MonitorColors.Black,
    surfaceContainer = MonitorColors.Black, surfaceContainerHigh = MonitorColors.Black,
    surfaceContainerHighest = MonitorColors.Black, surfaceContainerLow = MonitorColors.Black,
    surfaceContainerLowest = MonitorColors.Black,
)

@Composable
fun MonitorTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = MonitorColorScheme, typography = MonitorTypography, content = content)
}
