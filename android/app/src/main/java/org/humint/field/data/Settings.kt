package org.humint.field.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * The handful of preferences that are not secret.
 *
 * Plain SharedPreferences, deliberately. The theme has to be readable
 * *before* the vault is unlocked — the lock screen has to be drawn in the
 * right colours — so it cannot live behind the PIN. Nothing here says
 * anything about a case: which theme somebody likes, and whether they turned
 * on the fingerprint shortcut. Everything that matters is in the encrypted
 * store.
 */
enum class ThemeChoice(val label: String, val blurb: String) {
    SYSTEM("Match the system", "Follow the phone's own light or dark setting"),
    DARK("Always dark", "Easier on the eyes at night, and less to see from a distance"),
    LIGHT("Always light", "Readable in direct sun");

    companion object {
        fun from(name: String?): ThemeChoice =
            entries.firstOrNull { it.name == name } ?: SYSTEM
    }
}

/** The console's palettes, on the phone, under the same names — so a team
 *  that runs its console in Slate can match the handsets to it. */
enum class PaletteChoice(val label: String, val blurb: String) {
    TERMINAL("Terminal", "The green this tool started with"),
    SLATE("Slate", "Neutral blue-grey"),
    GRAPHITE("Graphite", "Warm charcoal and bronze, square corners"),
    ARCHIVE("Archive", "Paper and oxblood, for readers");

    companion object {
        fun from(name: String?): PaletteChoice =
            entries.firstOrNull { it.name == name } ?: TERMINAL
    }
}

object Settings {
    private const val FILE = "field.settings"
    private const val KEY_THEME = "theme"
    private const val KEY_PALETTE = "palette"
    private const val KEY_RELAY = "relay_mode"

    private val _theme = MutableStateFlow(ThemeChoice.SYSTEM)
    val theme: StateFlow<ThemeChoice> = _theme

    private val _palette = MutableStateFlow(PaletteChoice.TERMINAL)
    val palette: StateFlow<PaletteChoice> = _palette

    /** This install is a team relay (1.7). Here rather than in the vault
     *  because the app has to know which frame to draw before the PIN. */
    private val _relayMode = MutableStateFlow(false)
    val relayMode: StateFlow<Boolean> = _relayMode

    fun load(context: Context) {
        val prefs = context.getSharedPreferences(FILE, Context.MODE_PRIVATE)
        _theme.value = ThemeChoice.from(prefs.getString(KEY_THEME, null))
        _palette.value = PaletteChoice.from(prefs.getString(KEY_PALETTE, null))
        _relayMode.value = prefs.getBoolean(KEY_RELAY, false)
    }

    fun setRelayMode(context: Context, on: Boolean) {
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE)
            .edit().putBoolean(KEY_RELAY, on).apply()
        _relayMode.value = on
    }

    fun setTheme(context: Context, choice: ThemeChoice) {
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE)
            .edit().putString(KEY_THEME, choice.name).apply()
        _theme.value = choice
    }

    fun setPalette(context: Context, choice: PaletteChoice) {
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE)
            .edit().putString(KEY_PALETTE, choice.name).apply()
        _palette.value = choice
    }
}
