package com.reverfyx.revpn.data

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class MaskProfile(
    val id: String,
    val name: String,
    val description: String,
    val serverName: String,
    val port: Int,
    val shortId: String,
    val fingerprint: String
)

data class ServerProfile(
    val id: String,
    val name: String,
    val country: String,
    val city: String,
    val host: String,
    val uuid: String,
    val realityPassword: String,
    val masks: List<MaskProfile>
)

object ServerStore {
    private const val PREFS = "revpn_config"
    private const val KEY_JSON = "imported_json"
    private const val KEY_SERVER = "selected_server"
    private const val KEY_MASK = "selected_mask"

    fun load(context: Context): List<ServerProfile> {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val raw = prefs.getString(KEY_JSON, null)
            ?: context.assets.open("servers.json").bufferedReader().use { it.readText() }
        return parse(raw)
    }

    fun selectedServer(context: Context): ServerProfile? {
        val servers = load(context)
        if (servers.isEmpty()) return null
        val id = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_SERVER, null)
        return servers.firstOrNull { it.id == id } ?: servers.first()
    }

    fun selectedMask(context: Context, server: ServerProfile? = selectedServer(context)): MaskProfile? {
        server ?: return null
        val id = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_MASK, null)
        return server.masks.firstOrNull { it.id == id } ?: server.masks.firstOrNull()
    }

    fun selectServer(context: Context, serverId: String) {
        val server = load(context).firstOrNull { it.id == serverId } ?: return
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY_SERVER, server.id)
            .putString(KEY_MASK, server.masks.firstOrNull()?.id)
            .apply()
    }

    fun selectMask(context: Context, maskId: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY_MASK, maskId)
            .apply()
    }

    fun importJson(context: Context, raw: String): Result<Int> = runCatching {
        val parsed = parse(raw)
        require(parsed.isNotEmpty()) { "В конфигурации нет серверов" }
        require(parsed.all { it.masks.isNotEmpty() }) { "У каждого сервера нужен хотя бы один профиль маскировки" }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY_JSON, raw)
            .remove(KEY_SERVER)
            .remove(KEY_MASK)
            .apply()
        parsed.size
    }

    fun resetImported(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .remove(KEY_JSON)
            .remove(KEY_SERVER)
            .remove(KEY_MASK)
            .apply()
    }

    fun isConfigured(server: ServerProfile?, mask: MaskProfile?): Boolean {
        if (server == null || mask == null) return false
        val bad = listOf(server.host, server.uuid, server.realityPassword, mask.serverName)
            .any { it.isBlank() || it.contains("YOUR_", ignoreCase = true) }
        return !bad
    }

    private fun parse(raw: String): List<ServerProfile> {
        val root = JSONObject(raw)
        val servers = root.optJSONArray("servers") ?: JSONArray()
        return buildList {
            for (i in 0 until servers.length()) {
                val s = servers.getJSONObject(i)
                val masksJson = s.optJSONArray("masks") ?: JSONArray()
                val masks = buildList {
                    for (j in 0 until masksJson.length()) {
                        val m = masksJson.getJSONObject(j)
                        add(
                            MaskProfile(
                                id = m.getString("id"),
                                name = m.getString("name"),
                                description = m.optString("description", "REALITY"),
                                serverName = m.getString("serverName"),
                                port = m.optInt("port", 443),
                                shortId = m.optString("shortId", ""),
                                fingerprint = m.optString("fingerprint", "chrome")
                            )
                        )
                    }
                }
                add(
                    ServerProfile(
                        id = s.getString("id"),
                        name = s.getString("name"),
                        country = s.optString("country", ""),
                        city = s.optString("city", ""),
                        host = s.getString("host"),
                        uuid = s.getString("uuid"),
                        realityPassword = s.getString("realityPassword"),
                        masks = masks
                    )
                )
            }
        }
    }
}
