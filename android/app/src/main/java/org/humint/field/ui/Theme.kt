package org.humint.field.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.humint.field.data.ThemeChoice

/*
 * Two schemes, and the analyst picks.
 *
 * This is a tool used outside, often at night, and a white screen at 2am is
 * both hard on the eyes and visible from a long way off — so the dark scheme
 * is the one that got the attention. But a phone in direct sun needs the
 * other one, and the system setting does not always know which situation its
 * owner is in. Hence Settings: match the system, or override it.
 *
 * Text is deliberately larger than Material's defaults throughout. The
 * person using this is standing up, possibly in the rain, possibly with
 * gloves on, and reading a 12sp label is not something they should have to
 * do.
 */

/*
 * v1.3: still green, no longer a terminal. The old scheme was neon on
 * near-black with a green cast to every surface, which read as a 1980s
 * monitor. This keeps the green as the one accent and lets the surfaces be
 * neutral and layered — background, then cards a step lighter, then the
 * bottom bar — the way current apps are built. The dark scheme is still the
 * one that got the attention, for the same reason as before: night, and not
 * lighting up the person holding it.
 */
private val Green = Color(0xFF3DDC84)
private val GreenDeep = Color(0xFF0E6B3A)
private val Amber = Color(0xFFFFB020)
private val Red = Color(0xFFFF5A4E)

private val Dark = darkColorScheme(
    primary = Green,
    onPrimary = Color(0xFF00210F),
    primaryContainer = GreenDeep,
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
    error = Red,
    onError = Color(0xFF2A0000),
)

private val Light = lightColorScheme(
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

private val FieldShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(24.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

val FieldAmber = Amber

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
fun FieldTheme(choice: ThemeChoice = ThemeChoice.SYSTEM, content: @Composable () -> Unit) {
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
    MaterialTheme(
        colorScheme = if (dark) Dark else Light,
        typography = FieldTypography,
        shapes = FieldShapes,
        content = content,
    )
}

val MonoStyle = TextStyle(fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace)
