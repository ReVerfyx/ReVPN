package com.reverfyx.revpn

import android.Manifest
import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.AccountCircle
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Cloud
import androidx.compose.material.icons.rounded.ContentPaste
import androidx.compose.material.icons.rounded.Dns
import androidx.compose.material.icons.rounded.Login
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Logout
import androidx.compose.material.icons.rounded.Person
import androidx.compose.material.icons.rounded.PowerSettingsNew
import androidx.compose.material.icons.rounded.Public
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material.icons.rounded.VerifiedUser
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.reverfyx.revpn.auth.AuthStore
import com.reverfyx.revpn.auth.GoogleAccount
import com.reverfyx.revpn.auth.GoogleAuthManager
import com.reverfyx.revpn.data.MaskProfile
import com.reverfyx.revpn.data.ServerProfile
import com.reverfyx.revpn.data.ServerStore
import com.reverfyx.revpn.data.TrafficQuotaStore
import com.reverfyx.revpn.vpn.ReVpnService
import com.reverfyx.revpn.ui.AppTheme
import com.reverfyx.revpn.ui.ConnectionMode
import com.reverfyx.revpn.ui.ThemeRuntime
import com.reverfyx.revpn.ui.UiPreferences
import com.reverfyx.revpn.ui.paletteFor
import kotlinx.coroutines.launch

private val Bg get() = ThemeRuntime.current.bg
private val CardBg get() = ThemeRuntime.current.card
private val CardBg2 get() = ThemeRuntime.current.card2
private val Accent get() = ThemeRuntime.current.accent
private val Mint get() = ThemeRuntime.current.mint
private val Purple get() = ThemeRuntime.current.purple
private val Muted get() = ThemeRuntime.current.muted
private val Danger get() = ThemeRuntime.current.danger
private val TextColor get() = ThemeRuntime.current.text

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { ReVpnRoot() }
    }
}

private enum class Page { VPN, SERVERS, ACCOUNT, SETTINGS }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReVpnRoot() {
    val context = LocalContext.current
    val activity = context as? Activity
    val scope = rememberCoroutineScope()

    var revision by remember { mutableIntStateOf(0) }
    var authRevision by remember { mutableIntStateOf(0) }
    var appTheme by remember { mutableStateOf(UiPreferences.theme(context)) }
    var connectionMode by remember { mutableStateOf(UiPreferences.connectionMode(context)) }
    ThemeRuntime.current = paletteFor(appTheme)

    val servers = remember(revision) { ServerStore.load(context) }
    var selectedServer by remember(revision) { mutableStateOf(ServerStore.selectedServer(context)) }
    var selectedMask by remember(revision, selectedServer?.id) {
        mutableStateOf(ServerStore.selectedMask(context, selectedServer))
    }

    var account by remember(authRevision) { mutableStateOf(AuthStore.account(context)) }
    var guestUsed by remember { mutableLongStateOf(TrafficQuotaStore.guestUsedBytes(context)) }

    var page by remember { mutableStateOf(Page.VPN) }
    var showMasks by remember { mutableStateOf(false) }
    var showVpnDisclosure by remember { mutableStateOf(false) }

    var status by remember {
        mutableStateOf(
            if (ReVpnService.isRunning(context)) ReVpnService.STATUS_CONNECTED
            else ReVpnService.STATUS_DISCONNECTED
        )
    }
    var statusMessage by remember { mutableStateOf<String?>(null) }
    var authBusy by remember { mutableStateOf(false) }
    var authError by remember { mutableStateOf<String?>(null) }

    val notificationPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }

    LaunchedEffect(connectionMode, selectedServer?.id) {
        val server = selectedServer
        if (server != null) {
            val current = selectedMask
            val desired = when (connectionMode) {
                ConnectionMode.NORMAL ->
                    server.masks.firstOrNull { it.id == "standard" } ?: server.masks.firstOrNull()
                ConnectionMode.WHITELIST ->
                    if (current != null && current.id != "standard") current
                    else server.masks.firstOrNull { it.id != "standard" } ?: server.masks.firstOrNull()
            }
            if (desired != null && desired.id != current?.id) {
                ServerStore.selectMask(context, desired.id)
                selectedMask = desired
            }
        }
    }

    LaunchedEffect(Unit) {
        if (
            Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS
            ) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    fun startVpn() {
        val intent = Intent(context, ReVpnService::class.java)
            .setAction(ReVpnService.ACTION_CONNECT)
        ContextCompat.startForegroundService(context, intent)
    }

    val vpnPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) startVpn()
    }

    fun requestConnect() {
        val server = ServerStore.selectedServer(context)
        val mask = ServerStore.selectedMask(context, server)

        if (!ServerStore.isConfigured(server, mask)) {
            status = ReVpnService.STATUS_ERROR
            statusMessage = "Сервер ещё не встроен в эту сборку ReVPN."
            return
        }

        if (account == null && TrafficQuotaStore.isGuestLimitReached(context)) {
            status = ReVpnService.STATUS_ERROR
            statusMessage = "Гостевой лимит 1 ГБ закончился. Войди через Google."
            page = Page.ACCOUNT
            return
        }

        if (!UiPreferences.hasAcceptedVpnDisclosure(context)) {
            showVpnDisclosure = true
            return
        }

        val prepare = VpnService.prepare(context)
        if (prepare == null) startVpn() else vpnPermission.launch(prepare)
    }

    fun applyConnectionMode(newMode: ConnectionMode) {
        connectionMode = newMode
        UiPreferences.setConnectionMode(context, newMode)
        val server = ServerStore.selectedServer(context)
        if (server != null) {
            val nextMask = when (newMode) {
                ConnectionMode.NORMAL ->
                    server.masks.firstOrNull { it.id == "standard" } ?: server.masks.firstOrNull()
                ConnectionMode.WHITELIST ->
                    server.masks.firstOrNull { it.id != "standard" } ?: server.masks.firstOrNull()
            }
            if (nextMask != null) {
                ServerStore.selectMask(context, nextMask.id)
                selectedMask = nextMask
            }
        }
    }

    DisposableEffect(Unit) {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, intent: Intent?) {
                when (intent?.action) {
                    ReVpnService.ACTION_STATUS -> {
                        status = intent.getStringExtra(ReVpnService.EXTRA_STATUS)
                            ?: ReVpnService.STATUS_DISCONNECTED
                        statusMessage = intent.getStringExtra(ReVpnService.EXTRA_MESSAGE)
                        guestUsed = TrafficQuotaStore.guestUsedBytes(context)
                    }
                    ReVpnService.ACTION_QUOTA -> {
                        guestUsed = intent.getLongExtra(
                            ReVpnService.EXTRA_QUOTA_USED,
                            TrafficQuotaStore.guestUsedBytes(context)
                        )
                    }
                }
            }
        }

        val filter = IntentFilter().apply {
            addAction(ReVpnService.ACTION_STATUS)
            addAction(ReVpnService.ACTION_QUOTA)
        }

        if (Build.VERSION.SDK_INT >= 33) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("DEPRECATION")
            context.registerReceiver(receiver, filter)
        }

        onDispose { runCatching { context.unregisterReceiver(receiver) } }
    }

    val colors = if (ThemeRuntime.current.isLight) {
        lightColorScheme(
            primary = Accent,
            secondary = Mint,
            background = Bg,
            surface = CardBg,
            onPrimary = Color.White,
            onBackground = TextColor,
            onSurface = TextColor
        )
    } else {
        darkColorScheme(
            primary = Accent,
            secondary = Mint,
            background = Bg,
            surface = CardBg,
            onPrimary = Color(0xFF201C13),
            onBackground = TextColor,
            onSurface = TextColor
        )
    }

    MaterialTheme(colorScheme = colors) {
        Surface(modifier = Modifier.fillMaxSize(), color = Bg) {
            Scaffold(
                containerColor = Bg,
                bottomBar = {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(ThemeRuntime.current.nav)
                            .navigationBarsPadding()
                            .padding(horizontal = 4.dp, vertical = 7.dp),
                        horizontalArrangement = Arrangement.SpaceEvenly
                    ) {
                        NavItem(Modifier.weight(1f), Page.VPN, page, Icons.Rounded.Shield, "VPN") {
                            page = Page.VPN
                        }
                        NavItem(Modifier.weight(1f), Page.SERVERS, page, Icons.Rounded.Public, "Серверы") {
                            page = Page.SERVERS
                        }
                        NavItem(Modifier.weight(1f), Page.ACCOUNT, page, Icons.Rounded.Person, "Аккаунт") {
                            page = Page.ACCOUNT
                        }
                        NavItem(Modifier.weight(1f), Page.SETTINGS, page, Icons.Rounded.Settings, "Настройки") {
                            page = Page.SETTINGS
                        }
                    }
                }
            ) { padding ->
                when (page) {
                    Page.VPN -> HomeScreen(
                        modifier = Modifier.padding(padding),
                        server = selectedServer,
                        mask = selectedMask,
                        status = status,
                        message = statusMessage,
                        account = account,
                        guestUsed = guestUsed,
                        mode = connectionMode,
                        onMode = { applyConnectionMode(it) },
                        onPower = {
                            if (
                                status == ReVpnService.STATUS_CONNECTED ||
                                status == ReVpnService.STATUS_CONNECTING
                            ) {
                                context.startService(
                                    Intent(context, ReVpnService::class.java)
                                        .setAction(ReVpnService.ACTION_DISCONNECT)
                                )
                            } else {
                                requestConnect()
                            }
                        },
                        onServer = { page = Page.SERVERS },
                        onMask = { showMasks = true },
                        onAccount = { page = Page.ACCOUNT }
                    )

                    Page.SERVERS -> ServerScreen(
                        modifier = Modifier.padding(padding),
                        servers = servers,
                        selected = selectedServer,
                        onSelect = { server ->
                            ServerStore.selectServer(context, server.id)
                            selectedServer = server
                            val nextMask = when (connectionMode) {
                                ConnectionMode.NORMAL ->
                                    server.masks.firstOrNull { it.id == "standard" } ?: server.masks.firstOrNull()
                                ConnectionMode.WHITELIST ->
                                    server.masks.firstOrNull { it.id != "standard" } ?: server.masks.firstOrNull()
                            }
                            if (nextMask != null) {
                                ServerStore.selectMask(context, nextMask.id)
                                selectedMask = nextMask
                            }
                            page = Page.VPN
                        }
                    )

                    Page.ACCOUNT -> AccountScreen(
                        modifier = Modifier.padding(padding),
                        account = account,
                        guestUsed = guestUsed,
                        busy = authBusy,
                        error = authError,
                        googleConfigured = AuthStore.googleWebClientId(context).isNotBlank(),
                        onSignIn = {
                            when {
                                activity == null -> {
                                    authError = "Не удалось получить Activity для Google входа"
                                }
                                AuthStore.googleWebClientId(context).isBlank() -> {
                                    authError = "Google-вход ещё не настроен в этой сборке."
                                }
                                else -> {
                                    authBusy = true
                                    authError = null
                                    scope.launch {
                                        GoogleAuthManager.signIn(activity)
                                            .onSuccess {
                                                authRevision++
                                                account = AuthStore.account(context)
                                                statusMessage = null
                                            }
                                            .onFailure {
                                                authError = it.message ?: "Не удалось войти через Google"
                                            }
                                        authBusy = false
                                    }
                                }
                            }
                        },
                        onSignOut = {
                            if (activity == null) {
                                authError = "Не удалось получить Activity для выхода"
                            } else {
                                authBusy = true
                                authError = null
                                scope.launch {
                                    GoogleAuthManager.signOut(activity)
                                        .onSuccess {
                                            authRevision++
                                            account = null
                                            guestUsed = TrafficQuotaStore.guestUsedBytes(context)
                                        }
                                        .onFailure {
                                            authError = it.message ?: "Не удалось выйти из аккаунта"
                                        }
                                    authBusy = false
                                }
                            }
                        }
                    )

                    Page.SETTINGS -> SettingsScreen(
                        modifier = Modifier.padding(padding),
                        theme = appTheme,
                        onTheme = {
                            appTheme = it
                            UiPreferences.setTheme(context, it)
                            ThemeRuntime.current = paletteFor(it)
                        }
                    )
                }
            }

            if (showVpnDisclosure) {
                AlertDialog(
                    onDismissRequest = { showVpnDisclosure = false },
                    title = { Text("Как ReVPN использует VPN") },
                    text = {
                        Text(
                            "ReVPN использует Android VpnService, чтобы направлять сетевой трафик устройства через выбранный VPN-сервер. " +
                                "Приложение считает объём переданного трафика для гостевого лимита 1 ГБ. " +
                                "После входа через Google данные аккаунта используются для статуса аккаунта и снятия гостевого лимита. " +
                                "Продолжая, ты разрешаешь создание VPN-подключения."
                        )
                    },
                    confirmButton = {
                        Button(
                            onClick = {
                                UiPreferences.acceptVpnDisclosure(context)
                                showVpnDisclosure = false
                                requestConnect()
                            }
                        ) { Text("Продолжить") }
                    },
                    dismissButton = {
                        TextButton(onClick = { showVpnDisclosure = false }) {
                            Text("Отмена")
                        }
                    }
                )
            }

            if (showMasks) {
                ModalBottomSheet(
                    onDismissRequest = { showMasks = false },
                    containerColor = CardBg
                ) {
                    Text(
                        "Профиль маскировки",
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(horizontal = 22.dp, vertical = 8.dp)
                    )
                    Text(
                        "Профиль меняет TLS/REALITY SNI. IP VPS при этом не меняется.",
                        color = Muted,
                        modifier = Modifier.padding(horizontal = 22.dp, vertical = 4.dp)
                    )
                    selectedServer?.masks?.filter { it.id != "standard" }?.forEach { mask ->
                        MaskRow(mask, mask.id == selectedMask?.id) {
                            ServerStore.selectMask(context, mask.id)
                            selectedMask = mask
                            showMasks = false
                        }
                    }
                    Spacer(Modifier.height(28.dp))
                }
            }

        }
    }
}

@Composable
private fun NavItem(
    modifier: Modifier,
    page: Page,
    selectedPage: Page,
    icon: ImageVector,
    text: String,
    onClick: () -> Unit
) {
    val selected = page == selectedPage
    Column(
        modifier = modifier
            .clickable(onClick = onClick)
            .padding(vertical = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier
                .size(38.dp)
                .background(
                    if (selected) ThemeRuntime.current.inner else Color.Transparent,
                    RoundedCornerShape(13.dp)
                )
        ) {
            Icon(icon, contentDescription = null, tint = if (selected) Accent else Muted)
        }
        Text(
            text,
            color = if (selected) Accent else Muted,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal
        )
    }
}

@Composable
private fun HomeScreen(
    modifier: Modifier,
    server: ServerProfile?,
    mask: MaskProfile?,
    status: String,
    message: String?,
    account: GoogleAccount?,
    guestUsed: Long,
    mode: ConnectionMode,
    onMode: (ConnectionMode) -> Unit,
    onPower: () -> Unit,
    onServer: () -> Unit,
    onMask: () -> Unit,
    onAccount: () -> Unit
) {
    val connected = status == ReVpnService.STATUS_CONNECTED
    val connecting = status == ReVpnService.STATUS_CONNECTING

    val statusText = when (status) {
        ReVpnService.STATUS_CONNECTED -> "Подключён"
        ReVpnService.STATUS_CONNECTING -> "Соединение…"
        ReVpnService.STATUS_ERROR -> "Ошибка подключения"
        else -> "Отключён"
    }

    val statusColor = when (status) {
        ReVpnService.STATUS_CONNECTED -> Mint
        ReVpnService.STATUS_CONNECTING -> Accent
        ReVpnService.STATUS_ERROR -> Danger
        else -> Muted
    }

    val infinite = rememberInfiniteTransition(label = "connectPulse")
    val pulse by infinite.animateFloat(
        initialValue = 0.97f,
        targetValue = 1.05f,
        animationSpec = infiniteRepeatable(
            animation = tween(850),
            repeatMode = RepeatMode.Reverse
        ),
        label = "pulse"
    )
    val buttonScale = if (connecting) pulse else if (connected) 1.03f else 1f

    LazyColumn(
        modifier = modifier
            .fillMaxSize()
            .background(Bg),
        contentPadding = PaddingValues(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("Re", color = Accent, style = MaterialTheme.typography.headlineMedium)
                Text(
                    "VPN",
                    color = TextColor,
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Black
                )
                Spacer(Modifier.weight(1f))
                IconButton(onClick = onAccount) {
                    Icon(
                        if (account != null) Icons.Rounded.VerifiedUser else Icons.Rounded.AccountCircle,
                        null,
                        tint = if (account != null) Mint else Color.White
                    )
                }
                IconButton(onClick = onServer) {
                    Icon(Icons.Rounded.Public, null, tint = Color.White)
                }
            }
        }

        item {
            ModeSelector(mode = mode, onMode = onMode)
        }

        item {
            TrafficPlanCard(account = account, guestUsed = guestUsed, onAccount = onAccount)
        }

        item {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp)
            ) {
                Box(
                    contentAlignment = Alignment.Center,
                    modifier = Modifier
                        .size(196.dp)
                        .graphicsLayer {
                            scaleX = buttonScale
                            scaleY = buttonScale
                        }
                        .background(
                            brush = Brush.radialGradient(
                                colors = when {
                                    connected -> listOf(
                                        Mint.copy(alpha = .34f),
                                        Purple.copy(alpha = .12f),
                                        Color.Transparent
                                    )
                                    connecting -> listOf(
                                        Accent.copy(alpha = .28f),
                                        Purple.copy(alpha = .10f),
                                        Color.Transparent
                                    )
                                    else -> listOf(Accent.copy(alpha = .14f), Color.Transparent)
                                }
                            ),
                            shape = CircleShape
                        )
                        .border(
                            2.dp,
                            when {
                                connected -> Mint
                                connecting -> Accent
                                else -> Color(0xFF363A4A)
                            },
                            CircleShape
                        )
                        .clickable(onClick = onPower)
                ) {
                    Icon(
                        Icons.Rounded.PowerSettingsNew,
                        contentDescription = null,
                        tint = when {
                            connected -> Mint
                            connecting -> Accent
                            else -> Accent
                        },
                        modifier = Modifier.size(74.dp)
                    )
                }

                Spacer(Modifier.height(18.dp))
                Text(statusText, color = statusColor, fontWeight = FontWeight.Bold)

                if (message != null) {
                    Text(
                        message,
                        color = Danger,
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                } else {
                    Text(
                        server?.let {
                            "${it.city.ifBlank { it.country }} • ${mask?.name ?: "Без профиля"}"
                        } ?: "Сервер не выбран",
                        color = Muted,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.padding(top = 6.dp)
                    )
                }
            }
        }

        item {
            SelectCard(
                icon = Icons.Rounded.Dns,
                title = server?.name ?: "Сервер",
                subtitle = server?.let { "${it.country} • ${it.city}" } ?: "Не выбран",
                badge = "Сервер",
                onClick = onServer
            )
        }

        item {
            if (mode == ConnectionMode.WHITELIST) {
                SelectCard(
                    icon = Icons.Rounded.Cloud,
                    title = mask?.name ?: "Профиль",
                    subtitle = mask?.let { "${it.description} • ${it.serverName}" } ?: "Не выбран",
                    badge = "Белый список",
                    onClick = onMask
                )
            } else {
                SelectCard(
                    icon = Icons.Rounded.Shield,
                    title = "Обычный VPN",
                    subtitle = "Стандартный защищённый туннель",
                    badge = "VPN",
                    onClick = {}
                )
            }
        }

        item {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                SmallStat(
                    Modifier.weight(1f),
                    Icons.Rounded.Lock,
                    "Туннель",
                    if (connected) "Защищён" else "Выключен",
                    if (connected) Mint else Muted
                )
                SmallStat(
                    Modifier.weight(1f),
                    Icons.Rounded.Speed,
                    "Протокол",
                    "VLESS",
                    Accent
                )
            }
        }
    }
}

@Composable
private fun ModeSelector(
    mode: ConnectionMode,
    onMode: (ConnectionMode) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(CardBg2, RoundedCornerShape(22.dp))
            .padding(6.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        ConnectionMode.entries.forEach { item ->
            val selected = item == mode
            Column(
                modifier = Modifier
                    .weight(1f)
                    .background(
                        if (selected) ThemeRuntime.current.inner else Color.Transparent,
                        RoundedCornerShape(17.dp)
                    )
                    .clickable { onMode(item) }
                    .padding(horizontal = 10.dp, vertical = 11.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(
                    item.title,
                    color = if (selected) Accent else Muted,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    item.subtitle,
                    color = Muted,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}

@Composable
private fun TrafficPlanCard(
    account: GoogleAccount?,
    guestUsed: Long,
    onAccount: () -> Unit
) {
    val remaining = (TrafficQuotaStore.GUEST_LIMIT_BYTES - guestUsed).coerceAtLeast(0L)
    val progress = (guestUsed.toFloat() / TrafficQuotaStore.GUEST_LIMIT_BYTES.toFloat())
        .coerceIn(0f, 1f)

    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onAccount),
        colors = CardDefaults.cardColors(containerColor = CardBg2),
        shape = RoundedCornerShape(22.dp)
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    if (account != null) Icons.Rounded.VerifiedUser else Icons.Rounded.Info,
                    null,
                    tint = if (account != null) Mint else Accent
                )
                Column(Modifier.padding(start = 12.dp).weight(1f)) {
                    Text(
                        if (account != null) "Безлимитный трафик" else "Гостевой тариф",
                        fontWeight = FontWeight.Bold
                    )
                    Text(
                        if (account != null) {
                            account.email.ifBlank { "Google аккаунт подключён" }
                        } else {
                            "Без регистрации доступно 1 ГБ"
                        },
                        color = Muted,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                Text(
                    if (account != null) "∞" else TrafficQuotaStore.formatBytes(remaining),
                    color = if (account != null) Mint else Accent,
                    fontWeight = FontWeight.Black
                )
            }

            if (account == null) {
                Spacer(Modifier.height(12.dp))
                Box(
                    Modifier
                        .fillMaxWidth()
                        .height(6.dp)
                        .background(ThemeRuntime.current.progressBg, RoundedCornerShape(99.dp))
                ) {
                    Box(
                        Modifier
                            .fillMaxWidth(progress)
                            .height(6.dp)
                            .background(
                                if (progress >= .9f) Danger else Accent,
                                RoundedCornerShape(99.dp)
                            )
                    )
                }
            }
        }
    }
}

@Composable
private fun SelectCard(
    icon: ImageVector,
    title: String,
    subtitle: String,
    badge: String?,
    onClick: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = CardBg),
        shape = RoundedCornerShape(24.dp)
    ) {
        Row(
            modifier = Modifier.padding(18.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .size(52.dp)
                    .background(ThemeRuntime.current.inner, RoundedCornerShape(16.dp))
            ) {
                Icon(icon, null, tint = Accent)
            }

            Column(Modifier.padding(start = 14.dp).weight(1f)) {
                Text(title, fontWeight = FontWeight.Bold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(subtitle, color = Muted, style = MaterialTheme.typography.bodySmall)
            }

            if (badge != null) {
                Text(
                    badge,
                    color = Accent,
                    style = MaterialTheme.typography.labelMedium,
                    modifier = Modifier
                        .background(ThemeRuntime.current.badge, RoundedCornerShape(14.dp))
                        .padding(horizontal = 11.dp, vertical = 7.dp)
                )
            }
        }
    }
}

@Composable
private fun SmallStat(
    modifier: Modifier,
    icon: ImageVector,
    title: String,
    value: String,
    color: Color
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(containerColor = CardBg),
        shape = RoundedCornerShape(20.dp)
    ) {
        Column(Modifier.padding(16.dp)) {
            Icon(icon, null, tint = color)
            Spacer(Modifier.height(10.dp))
            Text(title, color = Muted, style = MaterialTheme.typography.bodySmall)
            Text(value, color = TextColor, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun ServerScreen(
    modifier: Modifier,
    servers: List<ServerProfile>,
    selected: ServerProfile?,
    onSelect: (ServerProfile) -> Unit
) {
    LazyColumn(
        modifier = modifier.fillMaxSize().background(Bg),
        contentPadding = PaddingValues(18.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        item {
            Text(
                "Выбор сервера",
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold
            )
            Text("Можно хранить несколько VPS и быстро переключаться.", color = Muted)
            Spacer(Modifier.height(10.dp))
        }

        items(servers, key = { it.id }) { server ->
            Card(
                modifier = Modifier.fillMaxWidth().clickable { onSelect(server) },
                colors = CardDefaults.cardColors(containerColor = CardBg),
                shape = RoundedCornerShape(22.dp)
            ) {
                Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        contentAlignment = Alignment.Center,
                        modifier = Modifier
                            .size(52.dp)
                            .background(ThemeRuntime.current.inner, CircleShape)
                    ) {
                        Text(
                            server.country.take(2).uppercase(),
                            fontWeight = FontWeight.Black,
                            color = Accent
                        )
                    }

                    Column(Modifier.padding(start = 14.dp).weight(1f)) {
                        Text(server.name, fontWeight = FontWeight.Bold)
                        Text("${server.country} • ${server.city}", color = Muted)
                    }

                    if (server.id == selected?.id) {
                        Icon(Icons.Rounded.Check, null, tint = Mint)
                    }
                }
            }
        }
    }
}

@Composable
private fun AccountScreen(
    modifier: Modifier,
    account: GoogleAccount?,
    guestUsed: Long,
    busy: Boolean,
    error: String?,
    googleConfigured: Boolean,
    onSignIn: () -> Unit,
    onSignOut: () -> Unit
) {
    val remaining = TrafficQuotaStore.remainingBytesFromUsed(guestUsed)

    LazyColumn(
        modifier = modifier.fillMaxSize().background(Bg),
        contentPadding = PaddingValues(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item {
            Text("Аккаунт", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text("Google аккаунт снимает гостевой лимит трафика.", color = Muted)
        }

        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(containerColor = CardBg),
                shape = RoundedCornerShape(26.dp)
            ) {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(22.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Box(
                        contentAlignment = Alignment.Center,
                        modifier = Modifier
                            .size(82.dp)
                            .background(
                                if (account != null) Mint.copy(alpha = .16f) else ThemeRuntime.current.inner,
                                CircleShape
                            )
                    ) {
                        if (account != null) {
                            Text(
                                account.displayName.ifBlank { account.email }.take(1).uppercase(),
                                color = Mint,
                                style = MaterialTheme.typography.headlineLarge,
                                fontWeight = FontWeight.Black
                            )
                        } else {
                            Icon(Icons.Rounded.AccountCircle, null, tint = Accent, modifier = Modifier.size(48.dp))
                        }
                    }

                    Spacer(Modifier.height(14.dp))

                    if (account != null) {
                        Text(
                            account.displayName.ifBlank { "Google пользователь" },
                            fontWeight = FontWeight.Bold,
                            style = MaterialTheme.typography.titleLarge
                        )
                        Text(account.email, color = Muted)
                        Spacer(Modifier.height(8.dp))
                        Text("Трафик без ограничений", color = Mint, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(18.dp))
                        OutlinedButton(onClick = onSignOut, enabled = !busy) {
                            Icon(Icons.Rounded.Logout, null)
                            Text("Выйти", modifier = Modifier.padding(start = 8.dp))
                        }
                    } else {
                        Text(
                            "Гостевой режим",
                            fontWeight = FontWeight.Bold,
                            style = MaterialTheme.typography.titleLarge
                        )
                        Text(
                            "Осталось ${TrafficQuotaStore.formatBytes(remaining)} из 1 ГБ",
                            color = Accent,
                            modifier = Modifier.padding(top = 4.dp)
                        )
                        Spacer(Modifier.height(18.dp))

                        Button(
                            onClick = onSignIn,
                            enabled = !busy && googleConfigured,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = Color.White,
                                contentColor = Color(0xFF202124)
                            )
                        ) {
                            Icon(Icons.Rounded.Login, null)
                            Text(
                                if (busy) "Входим…" else "Войти через Google",
                                modifier = Modifier.padding(start = 8.dp),
                                fontWeight = FontWeight.Bold
                            )
                        }

                        if (!googleConfigured) {
                            Spacer(Modifier.height(10.dp))
                            Text(
                                "Вход через Google будет доступен в релизной сборке.",
                                color = Muted,
                                style = MaterialTheme.typography.bodySmall
                            )
                        }
                    }

                    if (error != null) {
                        Spacer(Modifier.height(12.dp))
                        Text(error, color = Danger, style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }

        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = CardBg2),
                shape = RoundedCornerShape(22.dp)
            ) {
                Column(Modifier.padding(18.dp)) {
                    Text("Лимиты", fontWeight = FontWeight.Bold, color = Accent)
                    Spacer(Modifier.height(6.dp))
                    Text("Без регистрации: 1 ГБ суммарного VPN-трафика.", color = Muted)
                    Text("После входа через Google: без ограничения.", color = Muted)
                }
            }
        }
    }
}

@Composable
private fun SettingsScreen(
    modifier: Modifier,
    theme: AppTheme,
    onTheme: (AppTheme) -> Unit
) {
    LazyColumn(
        modifier = modifier.fillMaxSize().background(Bg),
        contentPadding = PaddingValues(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Text("Оформление", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text("Выбери внешний вид ReVPN.", color = Muted)
        }

        items(AppTheme.entries, key = { it.key }) { item ->
            ThemeRow(
                theme = item,
                selected = item == theme,
                onClick = { onTheme(item) }
            )
        }

        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = CardBg2),
                shape = RoundedCornerShape(22.dp)
            ) {
                Column(Modifier.padding(18.dp)) {
                    Text("ReVPN", fontWeight = FontWeight.Bold, color = Accent)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Серверы и Google-вход встроены в релизную сборку. Пользователю не нужно вводить технические данные.",
                        color = Muted,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        }
    }
}

@Composable
private fun ThemeRow(
    theme: AppTheme,
    selected: Boolean,
    onClick: () -> Unit
) {
    val preview = paletteFor(theme)
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = CardBg),
        shape = RoundedCornerShape(22.dp)
    ) {
        Row(
            Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(4.dp),
                modifier = Modifier.padding(end = 14.dp)
            ) {
                Box(Modifier.size(18.dp).background(preview.bg, CircleShape).border(1.dp, Muted.copy(alpha=.3f), CircleShape))
                Box(Modifier.size(18.dp).background(preview.accent, CircleShape))
                Box(Modifier.size(18.dp).background(preview.purple, CircleShape))
            }
            Column(Modifier.weight(1f)) {
                Text(theme.title, fontWeight = FontWeight.Bold)
                Text(theme.subtitle, color = Muted, style = MaterialTheme.typography.bodySmall)
            }
            if (selected) Icon(Icons.Rounded.Check, null, tint = Mint)
        }
    }
}

@Composable
private fun SettingsRow(
    icon: ImageVector,
    title: String,
    subtitle: String,
    onClick: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = CardBg),
        shape = RoundedCornerShape(22.dp)
    ) {
        Row(Modifier.padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(icon, null, tint = Accent)
            Column(Modifier.padding(start = 14.dp)) {
                Text(title, fontWeight = FontWeight.Bold)
                Text(subtitle, color = Muted, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun MaskRow(mask: MaskProfile, selected: Boolean, onClick: () -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 22.dp, vertical = 14.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .size(46.dp)
                    .background(
                        if (selected) Purple else ThemeRuntime.current.inner,
                        RoundedCornerShape(15.dp)
                    )
            ) {
                Text(mask.name.take(2).uppercase(), fontWeight = FontWeight.Black)
            }

            Column(Modifier.padding(start = 14.dp).weight(1f)) {
                Text(mask.name, fontWeight = FontWeight.Bold)
                Text(
                    "${mask.description} • ${mask.serverName}",
                    color = Muted,
                    style = MaterialTheme.typography.bodySmall
                )
            }

            if (selected) Icon(Icons.Rounded.Check, null, tint = Mint)
        }

        Divider(color = Color(0xFF2A2E3B), modifier = Modifier.padding(top = 14.dp))
    }
}

@Composable
private fun ImportDialog(onDismiss: () -> Unit, onImported: () -> Unit) {
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current
    var text by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Импорт сервера") },
        text = {
            Column {
                Text(
                    "Вставь содержимое /root/revpn-client.json с VPS.",
                    color = Muted,
                    style = MaterialTheme.typography.bodySmall
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = text,
                    onValueChange = {
                        text = it
                        error = null
                    },
                    minLines = 7,
                    maxLines = 12,
                    label = { Text("JSON") },
                    modifier = Modifier.fillMaxWidth()
                )
                TextButton(onClick = { text = clipboard.getText()?.text.orEmpty() }) {
                    Text("Вставить из буфера")
                }
                if (error != null) {
                    Text(error!!, color = Danger, style = MaterialTheme.typography.bodySmall)
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    ServerStore.importJson(context, text)
                        .onSuccess { onImported() }
                        .onFailure { error = it.message ?: "Неверный JSON" }
                }
            ) {
                Text("Импортировать")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Отмена") }
        }
    )
}

@Composable
private fun GoogleOAuthDialog(
    initial: String,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit
) {
    var value by remember(initial) { mutableStateOf(initial) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Google OAuth") },
        text = {
            Column {
                Text(
                    "Вставь Web Client ID из Google Auth Platform. Он заканчивается на .apps.googleusercontent.com.",
                    color = Muted,
                    style = MaterialTheme.typography.bodySmall
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = value,
                    onValueChange = { value = it },
                    label = { Text("Web Client ID") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { onSave(value.trim()) },
                enabled = value.trim().isNotBlank()
            ) {
                Text("Сохранить")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Отмена") }
        }
    )
}
