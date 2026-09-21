package com.reverfyx.revpn.ui

import android.content.Context
import androidx.compose.ui.graphics.Color

enum class AppTheme(val key: String, val title: String, val subtitle: String) {
    GLASS("glass", "Стекло", "Полупрозрачные карточки и мягкое свечение"),
    NIGHT("night", "Ночная", "Тёмная классическая тема"),
    DAY("day", "Дневная", "Светлый интерфейс"),
    RED("red", "Красная", "Тёмная тема с красным акцентом"),
    BLUE("blue", "Синяя", "Холодный синий акцент"),
    PURPLE("purple", "Фиолетовая", "Фиолетовый неоновый акцент");

    companion object {
        fun fromKey(key: String?): AppTheme =
            entries.firstOrNull { it.key == key } ?: GLASS
    }
}

data class AppPalette(
    val bg: Color,
    val card: Color,
    val card2: Color,
    val accent: Color,
    val mint: Color,
    val purple: Color,
    val muted: Color,
    val danger: Color,
    val text: Color,
    val nav: Color,
    val inner: Color,
    val badge: Color,
    val progressBg: Color,
    val isLight: Boolean
)

object ThemeRuntime {
    var current: AppPalette = paletteFor(AppTheme.GLASS)
}

object UiPreferences {
    private const val PREFS = "revpn_ui"
    private const val KEY_THEME = "theme"
    private const val KEY_VPN_DISCLOSURE = "vpn_disclosure_accepted"

    fun theme(context: Context): AppTheme =
        AppTheme.fromKey(
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString(KEY_THEME, AppTheme.GLASS.key)
        )

    fun setTheme(context: Context, theme: AppTheme) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_THEME, theme.key)
            .apply()
    }

    fun hasAcceptedVpnDisclosure(context: Context): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getBoolean(KEY_VPN_DISCLOSURE, false)

    fun acceptVpnDisclosure(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY_VPN_DISCLOSURE, true)
            .apply()
    }
}

fun paletteFor(theme: AppTheme): AppPalette = when (theme) {
    AppTheme.GLASS -> AppPalette(
        bg = Color(0xFF0C0F19),
        card = Color(0xB81A2030),
        card2 = Color(0x99252B3F),
        accent = Color(0xFFFFD67A),
        mint = Color(0xFF2BE3C2),
        purple = Color(0xFF8A3FFC),
        muted = Color(0xFFADB3C5),
        danger = Color(0xFFFF8D8D),
        text = Color.White,
        nav = Color(0xCC151824),
        inner = Color(0xAA2A3043),
        badge = Color(0xAA292A3A),
        progressBg = Color(0xAA303546),
        isLight = false
    )

    AppTheme.NIGHT -> AppPalette(
        bg = Color(0xFF11131D),
        card = Color(0xFF1C2030),
        card2 = Color(0xFF222738),
        accent = Color(0xFFFFD67A),
        mint = Color(0xFF2BE3C2),
        purple = Color(0xFF8A3FFC),
        muted = Color(0xFF9BA1B4),
        danger = Color(0xFFFF8D8D),
        text = Color.White,
        nav = Color(0xFF151824),
        inner = Color(0xFF292E40),
        badge = Color(0xFF272737),
        progressBg = Color(0xFF303546),
        isLight = false
    )

    AppTheme.DAY -> AppPalette(
        bg = Color(0xFFF3F6FC),
        card = Color.White,
        card2 = Color(0xFFE8EDF6),
        accent = Color(0xFF8A5B00),
        mint = Color(0xFF008D79),
        purple = Color(0xFF6B43D6),
        muted = Color(0xFF667085),
        danger = Color(0xFFBA1A1A),
        text = Color(0xFF111827),
        nav = Color(0xFFFDFEFF),
        inner = Color(0xFFE8EDF5),
        badge = Color(0xFFF0E9D8),
        progressBg = Color(0xFFD9E0EB),
        isLight = true
    )

    AppTheme.RED -> AppPalette(
        bg = Color(0xFF140E11),
        card = Color(0xFF24161C),
        card2 = Color(0xFF301B22),
        accent = Color(0xFFFF5F6D),
        mint = Color(0xFFFFB0B7),
        purple = Color(0xFFC84D78),
        muted = Color(0xFFB9A2AA),
        danger = Color(0xFFFF6673),
        text = Color.White,
        nav = Color(0xFF1B1115),
        inner = Color(0xFF382027),
        badge = Color(0xFF382027),
        progressBg = Color(0xFF43262E),
        isLight = false
    )

    AppTheme.BLUE -> AppPalette(
        bg = Color(0xFF0B1220),
        card = Color(0xFF142238),
        card2 = Color(0xFF1A2B48),
        accent = Color(0xFF58A6FF),
        mint = Color(0xFF49D6FF),
        purple = Color(0xFF6577FF),
        muted = Color(0xFF9DB0CA),
        danger = Color(0xFFFF8D9A),
        text = Color.White,
        nav = Color(0xFF0F192B),
        inner = Color(0xFF203653),
        badge = Color(0xFF203653),
        progressBg = Color(0xFF263D59),
        isLight = false
    )

    AppTheme.PURPLE -> AppPalette(
        bg = Color(0xFF120D1D),
        card = Color(0xFF211631),
        card2 = Color(0xFF2B1B40),
        accent = Color(0xFFC18CFF),
        mint = Color(0xFFB7A2FF),
        purple = Color(0xFF9C5DFF),
        muted = Color(0xFFB4A6C8),
        danger = Color(0xFFFF91B2),
        text = Color.White,
        nav = Color(0xFF190F25),
        inner = Color(0xFF342149),
        badge = Color(0xFF342149),
        progressBg = Color(0xFF3D2954),
        isLight = false
    )
}
