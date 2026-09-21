package com.reverfyx.revpn.xray

import com.reverfyx.revpn.data.MaskProfile
import com.reverfyx.revpn.data.ServerProfile
import org.json.JSONArray
import org.json.JSONObject

object XrayConfigFactory {
    fun build(server: ServerProfile, mask: MaskProfile, tunFd: Int): String {
        val tunInbound = JSONObject()
            .put("tag", "tun-in")
            .put("protocol", "tun")
            .put("settings", JSONObject()
                .put("name", "revpn0")
                .put("mtu", 1500))
            .put("sniffing", JSONObject()
                .put("enabled", true)
                .put("destOverride", JSONArray().put("http").put("tls").put("quic"))
                .put("routeOnly", false))

        val reality = JSONObject()
            .put("serverName", mask.serverName)
            .put("fingerprint", mask.fingerprint)
            .put("password", server.realityPassword)
            .put("shortId", mask.shortId)
            .put("spiderX", "/")

        val proxy = JSONObject()
            .put("tag", "proxy")
            .put("protocol", "vless")
            .put("settings", JSONObject()
                .put("address", server.host)
                .put("port", mask.port)
                .put("id", server.uuid)
                .put("encryption", "none")
                .put("flow", "xtls-rprx-vision"))
            .put("streamSettings", JSONObject()
                .put("method", "raw")
                .put("security", "reality")
                .put("rawSettings", JSONObject()
                    .put("header", JSONObject().put("type", "none")))
                .put("realitySettings", reality))

        return JSONObject()
            .put("env", JSONObject().put("xray.tun.fd", tunFd.toString()))
            .put("log", JSONObject().put("loglevel", "warning"))
            .put("inbounds", JSONArray().put(tunInbound))
            .put("outbounds", JSONArray()
                .put(proxy)
                .put(JSONObject().put("tag", "block").put("protocol", "blackhole")))
            .toString()
    }
}
