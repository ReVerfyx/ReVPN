package com.reverfyx.revpn.data

import android.content.Context
import java.util.Locale

object TrafficQuotaStore {
    const val GUEST_LIMIT_BYTES: Long = 1024L * 1024L * 1024L

    private const val PREFS = "revpn_quota"
    private const val KEY_GUEST_USED = "guest_used_bytes"

    fun guestUsedBytes(context: Context): Long =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getLong(KEY_GUEST_USED, 0L)
            .coerceAtLeast(0L)

    fun addGuestBytes(context: Context, delta: Long): Long {
        if (delta <= 0L) return guestUsedBytes(context)
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val next = (prefs.getLong(KEY_GUEST_USED, 0L) + delta)
            .coerceAtMost(Long.MAX_VALUE)
        prefs.edit().putLong(KEY_GUEST_USED, next).apply()
        return next
    }

    fun remainingBytes(context: Context): Long =
        (GUEST_LIMIT_BYTES - guestUsedBytes(context)).coerceAtLeast(0L)

    fun isGuestLimitReached(context: Context): Boolean =
        guestUsedBytes(context) >= GUEST_LIMIT_BYTES

    fun formatBytes(bytes: Long): String {
        val value = bytes.coerceAtLeast(0L).toDouble()
        val gb = 1024.0 * 1024.0 * 1024.0
        val mb = 1024.0 * 1024.0
        return when {
            value >= gb -> String.format(Locale.US, "%.2f ГБ", value / gb)
            value >= mb -> String.format(Locale.US, "%.0f МБ", value / mb)
            else -> String.format(Locale.US, "%.0f КБ", value / 1024.0)
        }
    }
}
