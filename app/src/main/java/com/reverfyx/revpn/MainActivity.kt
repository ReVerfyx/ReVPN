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
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.Cloud
import androidx.compose.material.icons.rounded.ContentPaste
import androidx.compose.material.icons.rounded.Dns
import androidx.compose.material.icons.rounded.Info
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.PowerSettingsNew
import androidx.compose.material.icons.rounded.Public
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material.icons.rounded.Speed
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Divider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.reverfyx.revpn.data.MaskProfile
import com.reverfyx.revpn.data.ServerProfile
import com.reverfyx.revpn.data.ServerStore
import com.reverfyx.revpn.vpn.ReVpnService

private val Bg = Color(0xFF11131D)
private val CardBg = Color(0xFF1C2030)
private val CardBg2 = Color(0xFF222738)
private val Accent = Color(0xFFFFD67A)
private val Mint = Color(0xFF2BE3C2)
private val Purple = Color(0xFF8A3FFC)
private val Muted = Color(0xFF9BA1B4)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { ReVpnRoot() }
    }
}

private enum class Page { VPN, SERVERS, SETTINGS }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ReVpnRoot() {
    val context = LocalContext.current
    var revision by remember { mutableIntStateOf(0) }
    val servers = remember(revision) { ServerStore.load(context) }
    var selectedServer by remember(revision) { mutableStateOf(ServerStore.selectedServer(context)) }
    var selectedMask by remember(revision, selectedServer?.id) {
        mutableStateOf(ServerStore.selectedMask(context, selectedServer))
    }
    var page by remember { mutableStateOf(Page.VPN) }
    var showMasks by remember { mutableStateOf(false) }
    var showImport by remember { mutableStateOf(false) }
    var status by remember {
        mutableStateOf(
            if (ReVpnService.isRunning(context)) ReVpnService.STATUS_CONNECTED
            else ReVpnService.STATUS_DISCONNECTED
        )
    }
    var statusMessage by remember { mutableStateOf<String?>(null) }

    val notificationPermission = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }

    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    fun startVpn() {
        val intent = Intent(context, ReVpnService::class.java).setAction(ReVpnService.ACTION_CONNECT)
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
            statusMessage = "Сначала импортируй конфигурацию сервера в Настройках."
            page = Page.SETTINGS
            return
        }
        val prepare = VpnService.prepare(context)
        if (prepare == null) startVpn() else vpnPermission.launch(prepare)
    }

    DisposableEffect(Unit) {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, intent: Intent?) {
                status = intent?.getStringExtra(ReVpnService.EXTRA_STATUS)
                    ?: ReVpnService.STATUS_DISCONNECTED
                statusMessage = intent?.getStringExtra(ReVpnService.EXTRA_MESSAGE)
            }
        }
        val filter = IntentFilter(ReVpnService.ACTION_STATUS)
        if (Build.VERSION.SDK_INT >= 33) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("DEPRECATION")
            context.registerReceiver(receiver, filter)
        }
        onDispose { runCatching { context.unregisterReceiver(receiver) } }
    }

    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Accent,
            secondary = Mint,
            background = Bg,
            surface = CardBg,
            onPrimary = Color(0xFF201C13),
            onBackground = Color.White,
            onSurface = Color.White
        )
    ) {
        Surface(modifier = Modifier.fillMaxSize(), color = Bg) {
            Scaffold(
                containerColor = Bg,
                bottomBar = {
                    NavigationBar(
                        containerColor = Color(0xFF151824),
                        modifier = Modifier.navigationBarsPadding()
                    ) {
                        NavItem(Page.VPN, page, Icons.Rounded.Shield, "VPN") { page = Page.VPN }
                        NavItem(Page.SERVERS, page, Icons.Rounded.Public, "Серверы") { page = Page.SERVERS }
                        NavItem(Page.SETTINGS, page, Icons.Rounded.Settings, "Настройки") { page = Page.SETTINGS }
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
                        onPower = {
                            if (status == ReVpnService.STATUS_CONNECTED ||
                                status == ReVpnService.STATUS_CONNECTING
                            ) {
                                context.startService(
                                    Intent(context, ReVpnService::class.java)
                                        .setAction(ReVpnService.ACTION_DISCONNECT)
                                )
                            } else requestConnect()
                        },
                        onServer = { page = Page.SERVERS },
                        onMask = { showMasks = true }
                    )
                    Page.SERVERS -> ServerScreen(
                        modifier = Modifier.padding(padding),
                        servers = servers,
                        selected = selectedServer,
                        onSelect = { server ->
                            ServerStore.selectServer(context, server.id)
                            selectedServer = server
                            selectedMask = ServerStore.selectedMask(context, server)
                            page = Page.VPN
                        }
                    )
                    Page.SETTINGS -> SettingsScreen(
                        modifier = Modifier.padding(padding),
                        configured = ServerStore.isConfigured(selectedServer, selectedMask),
                        onImport = { showImport = true },
                        onReset = {
                            ServerStore.resetImported(context)
                            revision++
                            selectedServer = ServerStore.selectedServer(context)
                            selectedMask = ServerStore.selectedMask(context, selectedServer)
                        }
                    )
                }
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
                        "Профиль меняет TLS/REALITY SNI. Он не меняет IP твоего VPS.",
                        color = Muted,
                        modifier = Modifier.padding(horizontal = 22.dp, vertical = 4.dp)
                    )
                    selectedServer?.masks?.forEach { mask ->
                        MaskRow(mask, mask.id == selectedMask?.id) {
                            ServerStore.selectMask(context, mask.id)
                            selectedMask = mask
                            showMasks = false
                        }
                    }
                    Spacer(Modifier.height(28.dp))
                }
            }

            if (showImport) {
                ImportDialog(
                    onDismiss = { showImport = false },
                    onImported = {
                        revision++
                        selectedServer = ServerStore.selectedServer(context)
                        selectedMask = ServerStore.selectedMask(context, selectedServer)
                        showImport = false
                        page = Page.VPN
                    }
                )
            }
        }
    }
}

@Composable
private fun NavItem(page: Page, selectedPage: Page, icon: ImageVector, text: String, onClick: () -> Unit) {
    NavigationBarItem(
        selected = page == selectedPage,
        onClick = onClick,
        icon = { Icon(icon, contentDescription = null) },
        label = { Text(text) },
        colors = NavigationBarItemDefaults.colors(
            selectedIconColor = Accent,
            selectedTextColor = Accent,
            indicatorColor = Color(0xFF2A2E3D),
            unselectedIconColor = Muted,
            unselectedTextColor = Muted
        )
    )
}

@Composable
private fun HomeScreen(
    modifier: Modifier,
    server: ServerProfile?,
    mask: MaskProfile?,
    status: String,
    message: String?,
    onPower: () -> Unit,
    onServer: () -> Unit,
    onMask: () -> Unit
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
        ReVpnService.STATUS_ERROR -> Color(0xFFFF8D8D)
        else -> Muted
    }

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
                Text(
                    "Re",
                    color = Accent,
                    style = MaterialTheme.typography.headlineMedium
                )
                Text(
                    "VPN",
                    color = Color.White,
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Black
                )
                Spacer(Modifier.weight(1f))
                IconButton(onClick = onServer) {
                    Icon(Icons.Rounded.Public, null, tint = Color.White)
                }
                IconButton(onClick = {}) {
                    Icon(Icons.Rounded.Refresh, null, tint = Color.White)
                }
            }
        }

        item {
            Card(
                colors = CardDefaults.cardColors(containerColor = CardBg2),
                shape = RoundedCornerShape(22.dp)
            ) {
                Row(
                    modifier = Modifier.padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Icon(Icons.Rounded.Info, null, tint = Accent)
                    Column(Modifier.padding(start = 12.dp)) {
                        Text("Режим маскировки", fontWeight = FontWeight.Bold)
                        Text(
                            "REALITY скрывает тип туннеля под обычный TLS. Строгий IP-whitelist всё равно может блокировать VPS.",
                            color = Muted,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
            }
        }

        item {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp)
            ) {
                Box(
                    contentAlignment = Alignment.Center,
                    modifier = Modifier
                        .size(196.dp)
                        .background(
                            brush = Brush.radialGradient(
                                colors = if (connected)
                                    listOf(Mint.copy(alpha = .34f), Purple.copy(alpha = .12f), Color.Transparent)
                                else
                                    listOf(Accent.copy(alpha = .14f), Color.Transparent)
                            ),
                            shape = CircleShape
                        )
                        .border(2.dp, if (connected) Mint else Color(0xFF363A4A), CircleShape)
                        .clickable(onClick = onPower)
                ) {
                    Icon(
                        Icons.Rounded.PowerSettingsNew,
                        contentDescription = null,
                        tint = if (connected) Mint else Accent,
                        modifier = Modifier.size(74.dp)
                    )
                }
                Spacer(Modifier.height(18.dp))
                Text(statusText, color = statusColor, fontWeight = FontWeight.Bold)
                if (message != null) {
                    Text(
                        message,
                        color = Color(0xFFFF9D9D),
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                } else {
                    Text(
                        if (connecting) "Проверяем защищённый канал" else
                            server?.let { "${it.city.ifBlank { it.country }} • ${mask?.name ?: "Без профиля"}" }
                                ?: "Сервер не выбран",
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
                badge = if (server != null) "Сервер" else null,
                onClick = onServer
            )
        }

        item {
            SelectCard(
                icon = Icons.Rounded.Cloud,
                title = mask?.name ?: "Маскировка",
                subtitle = mask?.let { "${it.description} • ${it.serverName}" } ?: "Не выбрана",
                badge = "REALITY",
                onClick = onMask
            )
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
                modifier = Modifier.size(52.dp).background(Color(0xFF292E40), RoundedCornerShape(16.dp))
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
                        .background(Color(0xFF272737), RoundedCornerShape(14.dp))
                        .padding(horizontal = 11.dp, vertical = 7.dp)
                )
            }
        }
    }
}

@Composable
private fun SmallStat(modifier: Modifier, icon: ImageVector, title: String, value: String, color: Color) {
    Card(modifier = modifier, colors = CardDefaults.cardColors(containerColor = CardBg), shape = RoundedCornerShape(20.dp)) {
        Column(Modifier.padding(16.dp)) {
            Icon(icon, null, tint = color)
            Spacer(Modifier.height(10.dp))
            Text(title, color = Muted, style = MaterialTheme.typography.bodySmall)
            Text(value, color = Color.White, fontWeight = FontWeight.Bold)
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
            Text("Выбор сервера", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text("Можно хранить несколько VPS и переключаться одним нажатием.", color = Muted)
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
                        modifier = Modifier.size(52.dp).background(Color(0xFF292E40), CircleShape)
                    ) {
                        Text(server.country.take(2).uppercase(), fontWeight = FontWeight.Black, color = Accent)
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
        if (servers.isEmpty()) {
            item { Text("Серверов пока нет. Импортируй JSON в Настройках.", color = Muted) }
        }
    }
}

@Composable
private fun SettingsScreen(
    modifier: Modifier,
    configured: Boolean,
    onImport: () -> Unit,
    onReset: () -> Unit
) {
    LazyColumn(
        modifier = modifier.fillMaxSize().background(Bg),
        contentPadding = PaddingValues(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Text("Настройки", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text("Конфигурация хранится только на устройстве.", color = Muted)
        }
        item {
            SettingsRow(
                Icons.Rounded.ContentPaste,
                "Импорт конфигурации",
                if (configured) "Сервер настроен" else "Вставь JSON с VPS",
                onImport
            )
        }
        item {
            SettingsRow(
                Icons.Rounded.Refresh,
                "Сбросить конфигурацию",
                "Вернуть шаблон из приложения",
                onReset
            )
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = CardBg2), shape = RoundedCornerShape(22.dp)) {
                Column(Modifier.padding(18.dp)) {
                    Text("О белых списках", fontWeight = FontWeight.Bold, color = Accent)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Выбор VK / VK Видео / Яндекс Диск / MAX — это профиль SNI/REALITY. Он помогает только там, где фильтрация допускает соединение с IP VPS. Если оператор разрешает только IP самих сервисов, одной подмены домена недостаточно.",
                        color = Muted,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
            }
        }
    }
}

@Composable
private fun SettingsRow(icon: ImageVector, title: String, subtitle: String, onClick: () -> Unit) {
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
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 22.dp, vertical = 14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier.size(46.dp).background(
                    if (selected) Purple else Color(0xFF292E40),
                    RoundedCornerShape(15.dp)
                )
            ) {
                Text(mask.name.take(2).uppercase(), fontWeight = FontWeight.Black)
            }
            Column(Modifier.padding(start = 14.dp).weight(1f)) {
                Text(mask.name, fontWeight = FontWeight.Bold)
                Text("${mask.description} • ${mask.serverName}", color = Muted, style = MaterialTheme.typography.bodySmall)
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
                    onValueChange = { text = it; error = null },
                    minLines = 7,
                    maxLines = 12,
                    label = { Text("JSON") },
                    modifier = Modifier.fillMaxWidth()
                )
                TextButton(onClick = { text = clipboard.getText()?.text.orEmpty() }) {
                    Text("Вставить из буфера")
                }
                if (error != null) Text(error!!, color = Color(0xFFFF9D9D), style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = {
            Button(onClick = {
                ServerStore.importJson(context, text)
                    .onSuccess { onImported() }
                    .onFailure { error = it.message ?: "Неверный JSON" }
            }) { Text("Импортировать") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Отмена") } }
    )
}
