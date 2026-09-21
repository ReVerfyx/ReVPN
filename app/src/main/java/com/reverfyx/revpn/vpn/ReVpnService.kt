package com.reverfyx.revpn.vpn

import android.content.Intent
import android.net.VpnService
import android.os.ParcelFileDescriptor
import androidx.core.app.NotificationManagerCompat
import com.reverfyx.revpn.data.MaskProfile
import com.reverfyx.revpn.data.ServerProfile
import com.reverfyx.revpn.data.ServerStore
import com.reverfyx.revpn.notification.VpnNotification
import com.reverfyx.revpn.xray.XrayConfigFactory
import libXray.DialerController
import libXray.LibXray
import org.json.JSONObject

class ReVpnService : VpnService() {

    companion object {
        const val ACTION_CONNECT = "com.reverfyx.revpn.CONNECT"
        const val ACTION_DISCONNECT = "com.reverfyx.revpn.DISCONNECT"
        const val ACTION_STATUS = "com.reverfyx.revpn.STATUS"
        const val EXTRA_STATUS = "status"
        const val EXTRA_MESSAGE = "message"
        const val STATUS_CONNECTING = "connecting"
        const val STATUS_CONNECTED = "connected"
        const val STATUS_DISCONNECTED = "disconnected"
        const val STATUS_ERROR = "error"
        private const val PREFS = "revpn_state"
        private const val KEY_RUNNING = "running"

        fun isRunning(context: android.content.Context): Boolean =
            context.getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean(KEY_RUNNING, false)
    }

    private var tunnel: ParcelFileDescriptor? = null
    private var coreRunning = false
    private var controllerRegistered = false
    private var activeServer: ServerProfile? = null
    private var activeMask: MaskProfile? = null

    private val controller = object : DialerController {
        override fun protectFd(fd: Long): Boolean = protect(fd.toInt())
    }

    override fun onCreate() {
        super.onCreate()
        VpnNotification.createChannel(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_DISCONNECT -> disconnect(showIdle = true)
            ACTION_CONNECT, null -> connect()
        }
        return START_NOT_STICKY
    }

    @Synchronized
    private fun connect() {
        if (coreRunning || tunnel != null) return

        val server = ServerStore.selectedServer(this)
        val mask = ServerStore.selectedMask(this, server)

        if (!ServerStore.isConfigured(server, mask)) {
            sendStatus(STATUS_ERROR, "Сервер ещё не настроен. Импортируй JSON из установщика VPS.")
            VpnNotification.showDisconnected(this, server, mask)
            stopSelf()
            return
        }

        server!!
        mask!!
        activeServer = server
        activeMask = mask
        VpnNotification.clearIdle(this)
        startForeground(VpnNotification.FOREGROUND_ID, VpnNotification.connecting(this, server, mask))
        sendStatus(STATUS_CONNECTING)

        try {
            if (!controllerRegistered) {
                LibXray.registerDialerController(controller)
                LibXray.registerListenerController(controller)
                controllerRegistered = true
            }

            val builder = Builder()
                .setSession("ReVPN • ${server.name}")
                .setMtu(1500)
                .addAddress("10.77.0.2", 30)
                .addRoute("0.0.0.0", 0)
                .addDnsServer("1.1.1.1")
                .addAddress("fd00:77::2", 126)
                .addRoute("::", 0)
                .addDnsServer("2606:4700:4700::1111")

            val established = builder.establish()
                ?: error("Android не создал VPN-интерфейс")
            tunnel = established

            LibXray.setDNS(controller, "1.1.1.1:53")
            val config = XrayConfigFactory.build(server, mask, established.fd)
            val request = JSONObject()
                .put("apiVersion", 3)
                .put("method", "runXray")
                .put("payload", JSONObject().put("xrayJson", config))

            val response = JSONObject(LibXray.invoke(request.toString()))
            if (!response.optBoolean("success", false)) {
                error(response.optString("error", "Xray не запустился"))
            }

            coreRunning = true
            setRunning(true)
            NotificationManagerCompat.from(this).notify(
                VpnNotification.FOREGROUND_ID,
                VpnNotification.connected(this, server, mask)
            )
            sendStatus(STATUS_CONNECTED)
        } catch (t: Throwable) {
            val message = t.message ?: t.javaClass.simpleName
            cleanupCore()
            setRunning(false)
            sendStatus(STATUS_ERROR, message)
            VpnNotification.showDisconnected(this, server, mask)
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    @Synchronized
    private fun disconnect(showIdle: Boolean) {
        val server = activeServer ?: ServerStore.selectedServer(this)
        val mask = activeMask ?: ServerStore.selectedMask(this, server)
        cleanupCore()
        setRunning(false)
        stopForeground(STOP_FOREGROUND_REMOVE)
        sendStatus(STATUS_DISCONNECTED)
        if (showIdle) VpnNotification.showDisconnected(this, server, mask)
        stopSelf()
    }

    private fun cleanupCore() {
        if (coreRunning) {
            runCatching {
                LibXray.invoke("""{"apiVersion":3,"method":"stopXray"}""")
            }
        }
        coreRunning = false
        runCatching { LibXray.resetDNS() }
        runCatching { tunnel?.close() }
        tunnel = null
    }

    private fun sendStatus(status: String, message: String? = null) {
        sendBroadcast(
            Intent(ACTION_STATUS)
                .setPackage(packageName)
                .putExtra(EXTRA_STATUS, status)
                .putExtra(EXTRA_MESSAGE, message)
        )
    }

    private fun setRunning(value: Boolean) {
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putBoolean(KEY_RUNNING, value).apply()
    }

    override fun onRevoke() {
        disconnect(showIdle = true)
        super.onRevoke()
    }

    override fun onDestroy() {
        cleanupCore()
        setRunning(false)
        super.onDestroy()
    }
}
