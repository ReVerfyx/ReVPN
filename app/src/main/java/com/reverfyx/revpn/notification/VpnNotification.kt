package com.reverfyx.revpn.notification

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.reverfyx.revpn.MainActivity
import com.reverfyx.revpn.R
import com.reverfyx.revpn.auth.AuthStore
import com.reverfyx.revpn.data.MaskProfile
import com.reverfyx.revpn.data.ServerProfile
import com.reverfyx.revpn.data.TrafficQuotaStore
import com.reverfyx.revpn.vpn.ReVpnService

object VpnNotification {
    const val CHANNEL_ID = "revpn_vpn"
    const val FOREGROUND_ID = 41
    private const val IDLE_ID = 42

    fun createChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
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

    fun connecting(context: Context, server: ServerProfile, mask: MaskProfile): Notification {
        val plan = planText(context)
        return base(context)
            .setContentTitle("Соединение…")
            .setContentText("${server.name} • ${mask.name}")
            .setStyle(
                NotificationCompat.BigTextStyle().bigText(
                    "Текущая локация: ${server.city.ifBlank { server.country }}\n" +
                        "Маскировка: ${mask.name}\n$plan"
                )
            )
            .setOngoing(true)
            .addAction(0, "Отключить", serviceAction(context, ReVpnService.ACTION_DISCONNECT, 2, false))
            .build()
    }

    fun connected(context: Context, server: ServerProfile, mask: MaskProfile): Notification {
        val plan = planText(context)
        return base(context)
            .setContentTitle("Подключён")
            .setContentText("${server.city.ifBlank { server.country }} • ${mask.name}")
            .setSubText("ReVPN")
            .setStyle(
                NotificationCompat.BigTextStyle().bigText(
                    "Текущая локация: ${server.city.ifBlank { server.country }}\n" +
                        "Профиль: ${mask.name}\n$plan"
                )
            )
            .setOngoing(true)
            .addAction(0, "Отключить", serviceAction(context, ReVpnService.ACTION_DISCONNECT, 3, false))
            .build()
    }

    fun showDisconnected(context: Context, server: ServerProfile?, mask: MaskProfile?) {
        val location = server?.city?.takeIf { it.isNotBlank() }
            ?: server?.country?.takeIf { it.isNotBlank() }
            ?: "Сервер не выбран"

        val notification = base(context)
            .setContentTitle("Отключён")
            .setContentText("$location • ${planText(context)}")
            .setSubText("ReVPN")
            .setStyle(
                NotificationCompat.BigTextStyle().bigText(
                    "Текущая локация: $location\n" +
                        "Профиль: ${mask?.name ?: "не выбран"}\n" +
                        planText(context)
                )
            )
            .setOngoing(false)
            .setAutoCancel(false)
            .addAction(0, "Подключить", serviceAction(context, ReVpnService.ACTION_CONNECT, 4, true))
            .build()

        try {
            context.getSystemService(NotificationManager::class.java).notify(IDLE_ID, notification)
        } catch (_: SecurityException) {
        }
    }

    fun clearIdle(context: Context) {
        context.getSystemService(NotificationManager::class.java).cancel(IDLE_ID)
    }

    private fun planText(context: Context): String =
        if (AuthStore.isSignedIn(context)) {
            "Трафик: без ограничений • Google"
        } else {
            "Остаток: ${TrafficQuotaStore.formatBytes(TrafficQuotaStore.remainingBytes(context))} из 1 ГБ"
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

    private fun serviceAction(
        context: Context,
        action: String,
        requestCode: Int,
        foreground: Boolean
    ): PendingIntent {
        val intent = Intent(context, ReVpnService::class.java).setAction(action)
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        return if (foreground && Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            PendingIntent.getForegroundService(context, requestCode, intent, flags)
        } else {
            PendingIntent.getService(context, requestCode, intent, flags)
        }
    }
}
