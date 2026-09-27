package com.example.kagi.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

/** desktop_app.py's THEMES: the same palette as challenge_site.py, plus result tints. */
data class KagiColors(
    val bg: Color,
    val ink: Color,
    val muted: Color,
    val line: Color,
    val field: Color,
    val green: Color,
    val greenBg: Color,
    val greenFlash: Color,
    val red: Color,
    val redBg: Color,
)

val LightKagi = KagiColors(
    bg = Color(0xFFFAFAFA), ink = Color(0xFF111111), muted = Color(0xFF777777), line = Color(0xFFE2E2E2),
    field = Color(0xFFFFFFFF), green = Color(0xFF16A34A), greenBg = Color(0xFFEEF8F1),
    greenFlash = Color(0xFFD3EFDD), red = Color(0xFFDC2626), redBg = Color(0xFFFDF1F1),
)

val DarkKagi = KagiColors(
    bg = Color(0xFF0E0E0E), ink = Color(0xFFF2F2F2), muted = Color(0xFF8A8A8A), line = Color(0xFF2A2A2A),
    field = Color(0xFF161616), green = Color(0xFF22C55E), greenBg = Color(0xFF0D1A12),
    greenFlash = Color(0xFF163A23), red = Color(0xFFEF4444), redBg = Color(0xFF1C0F0F),
)

val LocalKagi = staticCompositionLocalOf { LightKagi }

@Composable
fun KagiTheme(darkTheme: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val k = if (darkTheme) DarkKagi else LightKagi
    val scheme = (if (darkTheme) darkColorScheme() else lightColorScheme()).copy(
        primary = k.ink, onPrimary = k.bg, background = k.bg, onBackground = k.ink,
        surface = k.bg, onSurface = k.ink, outline = k.line, error = k.red,
    )
    CompositionLocalProvider(LocalKagi provides k) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
