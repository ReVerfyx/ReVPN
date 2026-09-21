package com.reverfyx.revpn.notification

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import com.reverfyx.revpn.MainActivity
import com.reverfyx.revpn.R
import com.reverfyx.revpn.data.MaskProfile
import com.reverfyx.revpn.data.ServerProfile
import com.reverfyx.revpn.vpn.ReVpnService

object VpnNotification {
    const val CHANNEL_ID = "revpn_vpn"
    const val FOREGROUND_ID = 41
    private const val IDLE_ID = 42

    fun createChannel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                context.getString(R.string.notification_channel),
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Состояние ReVPN"
                setShowBadge(false)
            }
        )
    }

    fun connecting(context: Context, server: ServerProfile, mask: MaskProfile): Notification =
        base(context)
            .setContentTitle("Соединение…")
            .setContentText("${server.name} • ${mask.name}")
            .setOngoing(true)
            .addAction(0, "Отключить", serviceAction(context, ReVpnService.ACTION_DISCONNECT, 2))
            .build()

    fun connected(context: Context, server: ServerProfile, mask: MaskProfile): Notification =
        base(context)
            .setContentTitle("Подключён")
            .setContentText("${server.city.ifBlank { server.country }} • ${mask.name}")
            .setSubText("ReVPN")
            .setOngoing(true)
            .addAction(0, "Отключить", serviceAction(context, ReVpnService.ACTION_DISCONNECT, 3))
            .build()

    fun showDisconnected(context: Context, server: ServerProfile?, mask: MaskProfile?) {
        val text = listOfNotNull(
            server?.city?.takeIf { it.isNotBlank() },
            mask?.name
        ).joinToString(" • ").ifBlank { "VPN выключен" }

        val notification = base(context)
            .setContentTitle("Отключён")
            .setContentText(text)
            .setOngoing(false)
            .setAutoCancel(false)
            .addAction(0, "Подключить", serviceAction(context, ReVpnService.ACTION_CONNECT, 4))
            .build()

        try {
            context.getSystemService(NotificationManager::class.java).notify(IDLE_ID, notification)
        } catch (_: SecurityException) {
        }
    }

    fun clearIdle(context: Context) {
        context.getSystemService(NotificationManager::class.java).cancel(IDLE_ID)
    }

    private fun base(context: Context): NotificationCompat.Builder {
        val open = PendingIntent.getActivity(
            context,
            1,
            Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_vpn)
            .setContentIntent(open)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
    }

    private fun serviceAction(context: Context, action: String, requestCode: Int): PendingIntent =
        PendingIntent.getService(
            context,
            requestCode,
            Intent(context, ReVpnService::class.java).setAction(action),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
}
