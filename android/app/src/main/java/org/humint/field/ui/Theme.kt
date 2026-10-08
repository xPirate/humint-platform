package org.humint.field.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import org.humint.field.data.PaletteChoice
import org.humint.field.data.ThemeChoice

/*
 * The console's four palettes, on the phone.
 *
 * Two axes, the same two as the console: the palette is what the
 * organisation wants the tool to look like, light/dark is about where the
 * screen is — night in a vehicle, or noon in the open. A team that runs
 * its console in Slate can hand out phones that match it.
 *
 *   terminal   The green the app started with. Still the default.
 *   slate      Neutral blue-grey. The one nobody has to defend.
 *   graphite   Warm charcoal, bronze accent, tight corners. An operations
 *              room rather than an app store product.
 *   archive    Warm paper and oxblood, for a team whose day is reading and
 *              writing rather than watching a dashboard.
 *
 * Hues come from frontend/styles.css; values are re-derived for Material
 * rather than copied, because a web --accent used for text and borders is
 * not automatically a Material primary that carries legible text on top.
 * Every primary/onPrimary pair here was picked to clear WCAG AA.
 *
 * Text is deliberately larger than Material's defaults throughout. The
 * person using this is standing up, possibly in the rain, possibly with
 * gloves on, and reading a 12sp label is not something they should have to
 * do.
 */

private val Amber = Color(0xFFFFB020)
val FieldAmber = Amber

// ---------------------------------------------------------------- terminal

private val TerminalDark = darkColorScheme(
    primary = Color(0xFF3DDC84),
    onPrimary = Color(0xFF00210F),
    primaryContainer = Color(0xFF0E6B3A),
    onPrimaryContainer = Color(0xFFCFF8DE),
    secondary = Color(0xFF8FD3B0),
    onSecondary = Color(0xFF00210F),
    background = Color(0xFF0B0F0D),
    onBackground = Color(0xFFE6ECE8),
    surface = Color(0xFF151B18),
    onSurface = Color(0xFFE6ECE8),
    surfaceVariant = Color(0xFF222B26),
    onSurfaceVariant = Color(0xFF9AA9A0),
    surfaceContainer = Color(0xFF151B18),
    surfaceContainerLow = Color(0xFF111613),
    surfaceContainerHigh = Color(0xFF1C2420),
    outline = Color(0xFF34413A),
    outlineVariant = Color(0xFF263029),
    error = Color(0xFFFF5A4E),
    onError = Color(0xFF2A0000),
)

private val TerminalLight = lightColorScheme(
    primary = Color(0xFF0F7A45),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFC6F2D8),
    onPrimaryContainer = Color(0xFF002110),
    secondary = Color(0xFF3C6B55),
    background = Color(0xFFF3F5F4),
    onBackground = Color(0xFF111714),
    surface = Color.White,
    onSurface = Color(0xFF111714),
    surfaceVariant = Color(0xFFE4EAE6),
    onSurfaceVariant = Color(0xFF4F5D55),
    surfaceContainer = Color.White,
    surfaceContainerLow = Color(0xFFF7F9F8),
    surfaceContainerHigh = Color(0xFFEDF1EE),
    outline = Color(0xFFB7C3BC),
    outlineVariant = Color(0xFFD9E0DC),
    error = Color(0xFFB3261E),
)

// ------------------------------------------------------------------- slate

private val SlateDark = darkColorScheme(
    primary = Color(0xFF6BA4F8),
    onPrimary = Color(0xFF081A33),
    primaryContainer = Color(0xFF1C4687),
    onPrimaryContainer = Color(0xFFD6E5FD),
    secondary = Color(0xFF9CC3FB),
    onSecondary = Color(0xFF081A33),
    background = Color(0xFF0F1419),
    onBackground = Color(0xFFDFE5EC),
    surface = Color(0xFF161C23),
    onSurface = Color(0xFFDFE5EC),
    surfaceVariant = Color(0xFF222A34),
    onSurfaceVariant = Color(0xFF96A2B1),
    surfaceContainer = Color(0xFF161C23),
    surfaceContainerLow = Color(0xFF10151B),
    surfaceContainerHigh = Color(0xFF1D2630),
    outline = Color(0xFF34404E),
    outlineVariant = Color(0xFF262F3A),
    error = Color(0xFFF2685F),
    onError = Color(0xFF2A0000),
)

private val SlateLight = lightColorScheme(
    primary = Color(0xFF0B5CAD),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD3E4F7),
    onPrimaryContainer = Color(0xFF0A2540),
    secondary = Color(0xFF3C5B7D),
    background = Color(0xFFF6F8FA),
    onBackground = Color(0xFF1C2128),
    surface = Color.White,
    onSurface = Color(0xFF1C2128),
    surfaceVariant = Color(0xFFEEF1F5),
    onSurfaceVariant = Color(0xFF57606A),
    surfaceContainer = Color.White,
    surfaceContainerLow = Color(0xFFF9FBFC),
    surfaceContainerHigh = Color(0xFFE9EDF2),
    outline = Color(0xFFC2CAD2),
    outlineVariant = Color(0xFFD8DEE4),
    error = Color(0xFFB3261E),
)

// ---------------------------------------------------------------- graphite

private val GraphiteDark = darkColorScheme(
    primary = Color(0xFFD9A066),
    onPrimary = Color(0xFF241303),
    primaryContainer = Color(0xFF8F5C28),
    onPrimaryContainer = Color(0xFFF4E2CC),
    secondary = Color(0xFFC8B394),
    onSecondary = Color(0xFF241303),
    background = Color(0xFF16181A),
    onBackground = Color(0xFFE4E6E8),
    surface = Color(0xFF1E2124),
    onSurface = Color(0xFFE4E6E8),
    surfaceVariant = Color(0xFF2A2E32),
    onSurfaceVariant = Color(0xFF9AA0A6),
    surfaceContainer = Color(0xFF1E2124),
    surfaceContainerLow = Color(0xFF191C1F),
    surfaceContainerHigh = Color(0xFF26292D),
    outline = Color(0xFF3C4146),
    outlineVariant = Color(0xFF2E3236),
    error = Color(0xFFE88178),
    onError = Color(0xFF2A0000),
)

private val GraphiteLight = lightColorScheme(
    primary = Color(0xFF8A5A22),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFEBD9C2),
    onPrimaryContainer = Color(0xFF2E1D08),
    secondary = Color(0xFF6B5B45),
    background = Color(0xFFF4F3F1),
    onBackground = Color(0xFF1B1A18),
    surface = Color.White,
    onSurface = Color(0xFF1B1A18),
    surfaceVariant = Color(0xFFECEAE6),
    onSurfaceVariant = Color(0xFF5A5650),
    surfaceContainer = Color.White,
    surfaceContainerLow = Color(0xFFF8F7F5),
    surfaceContainerHigh = Color(0xFFEBE8E3),
    outline = Color(0xFFC5C1BB),
    outlineVariant = Color(0xFFD8D4CE),
    error = Color(0xFFA3241A),
)

// ----------------------------------------------------------------- archive

private val ArchiveDark = darkColorScheme(
    primary = Color(0xFFE09292),
    onPrimary = Color(0xFF2A0D0D),
    primaryContainer = Color(0xFF9A3F3F),
    onPrimaryContainer = Color(0xFFF8DCDC),
    secondary = Color(0xFFC9B28F),
    onSecondary = Color(0xFF2A0D0D),
    background = Color(0xFF17150F),
    onBackground = Color(0xFFECE7DB),
    surface = Color(0xFF201D16),
    onSurface = Color(0xFFECE7DB),
    surfaceVariant = Color(0xFF2C2820),
    onSurfaceVariant = Color(0xFFA49B8C),
    surfaceContainer = Color(0xFF201D16),
    surfaceContainerLow = Color(0xFF1A1812),
    surfaceContainerHigh = Color(0xFF292519),
    outline = Color(0xFF443E31),
    outlineVariant = Color(0xFF332E24),
    error = Color(0xFFE88179),
    onError = Color(0xFF2A0000),
)

private val ArchiveLight = lightColorScheme(
    primary = Color(0xFF7A2E2E),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFEFD6D6),
    onPrimaryContainer = Color(0xFF300E0E),
    secondary = Color(0xFF6E5B3F),
    background = Color(0xFFFAF8F4),
    onBackground = Color(0xFF1A1714),
    surface = Color.White,
    onSurface = Color(0xFF1A1714),
    surfaceVariant = Color(0xFFF2EFE8),
    onSurfaceVariant = Color(0xFF5D564C),
    surfaceContainer = Color.White,
    surfaceContainerLow = Color(0xFFFCFBF8),
    surfaceContainerHigh = Color(0xFFEFEBE2),
    outline = Color(0xFFD5CEC1),
    outlineVariant = Color(0xFFE1DBD0),
    error = Color(0xFF9B2222),
)

private fun schemes(palette: PaletteChoice): Pair<ColorScheme, ColorScheme> = when (palette) {
    PaletteChoice.TERMINAL -> TerminalDark to TerminalLight
    PaletteChoice.SLATE -> SlateDark to SlateLight
    PaletteChoice.GRAPHITE -> GraphiteDark to GraphiteLight
    PaletteChoice.ARCHIVE -> ArchiveDark to ArchiveLight
}

/** The color a palette is recognised by, for the swatch in Settings. */
fun paletteSwatch(palette: PaletteChoice, dark: Boolean): Color =
    (if (dark) schemes(palette).first else schemes(palette).second).primary

/* Corners follow the console's radii in spirit: graphite and archive are
 * squarer, the way their consoles are. */
private fun shapes(palette: PaletteChoice): Shapes = when (palette) {
    PaletteChoice.GRAPHITE -> Shapes(
        extraSmall = RoundedCornerShape(4.dp), small = RoundedCornerShape(6.dp),
        medium = RoundedCornerShape(8.dp), large = RoundedCornerShape(12.dp),
        extraLarge = RoundedCornerShape(14.dp))
    PaletteChoice.ARCHIVE -> Shapes(
        extraSmall = RoundedCornerShape(2.dp), small = RoundedCornerShape(4.dp),
        medium = RoundedCornerShape(6.dp), large = RoundedCornerShape(8.dp),
        extraLarge = RoundedCornerShape(10.dp))
    else -> Shapes(
        extraSmall = RoundedCornerShape(8.dp), small = RoundedCornerShape(12.dp),
        medium = RoundedCornerShape(16.dp), large = RoundedCornerShape(24.dp),
        extraLarge = RoundedCornerShape(28.dp))
}

private val FieldTypography = Typography().let { base ->
    base.copy(
        headlineMedium = base.headlineMedium.copy(fontSize = 32.sp, letterSpacing = (-0.5).sp),
        headlineSmall = base.headlineSmall.copy(fontSize = 26.sp),
        titleLarge = base.titleLarge.copy(fontSize = 22.sp),
        titleMedium = base.titleMedium.copy(fontSize = 19.sp),
        bodyLarge = base.bodyLarge.copy(fontSize = 18.sp, lineHeight = 26.sp),
        bodyMedium = base.bodyMedium.copy(fontSize = 16.sp, lineHeight = 23.sp),
        labelLarge = base.labelLarge.copy(fontSize = 17.sp),
        labelMedium = base.labelMedium.copy(fontSize = 14.sp),
    )
}

/** Minimum size for anything tappable. Material says 48dp; this is a tool
 *  used with cold or gloved hands, so the buttons that matter are bigger. */
val TapTarget = 56.dp

@Composable
fun FieldTheme(
    choice: ThemeChoice = ThemeChoice.SYSTEM,
    palette: PaletteChoice = PaletteChoice.TERMINAL,
    content: @Composable () -> Unit,
) {
    val dark = when (choice) {
        ThemeChoice.SYSTEM -> isSystemInDarkTheme()
        ThemeChoice.DARK -> true
        ThemeChoice.LIGHT -> false
    }
    // Edge to edge, the status and navigation bars are transparent over the
    // app, so their icons must follow the app's theme rather than the
    // phone's: dark icons on the light palette, light icons on the dark one.
    // The app's theme can differ from the system's (Settings → Appearance).
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as? android.app.Activity)?.window ?: return@SideEffect
            WindowCompat.getInsetsController(window, view).apply {
                isAppearanceLightStatusBars = !dark
                isAppearanceLightNavigationBars = !dark
            }
        }
    }
    val (darkScheme, lightScheme) = schemes(palette)
    MaterialTheme(
        colorScheme = if (dark) darkScheme else lightScheme,
        typography = FieldTypography,
        shapes = shapes(palette),
        content = content,
    )
}

val MonoStyle = TextStyle(fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace)
