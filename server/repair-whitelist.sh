#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash server/repair-whitelist.sh"
  exit 1
fi

CLIENT=/root/revpn-client.json
SERVER=/usr/local/etc/xray/config.json
XRAY_BIN="$(command -v xray || true)"

[[ -n "$XRAY_BIN" ]] || { echo "xray not found"; exit 1; }
[[ -f "$CLIENT" ]] || { echo "$CLIENT not found"; exit 1; }
[[ -f "$SERVER" ]] || { echo "$SERVER not found"; exit 1; }

UUID="$(jq -r '.servers[0].uuid // empty' "$CLIENT")"
PUBLIC_KEY="$(jq -r '.servers[0].realityPassword // empty' "$CLIENT")"
HOST="$(jq -r '.servers[0].host // empty' "$CLIENT")"
PRIVATE_KEY="$(jq -r '[.inbounds[].streamSettings.realitySettings.privateKey // empty] | map(select(length>0)) | .[0] // empty' "$SERVER")"

sid() {
  local id="$1"
  jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .shortId' "$CLIENT" | head -n1
}

SID_STANDARD="$(sid standard)"
SID_MAX="$(sid max)"
SID_VK="$(sid vk)"
SID_VKVIDEO="$(sid vkvideo)"
SID_YADISK="$(sid yadisk)"

for v in UUID PUBLIC_KEY HOST PRIVATE_KEY SID_STANDARD SID_MAX SID_VK SID_VKVIDEO SID_YADISK; do
  [[ -n "${!v}" && "${!v}" != "null" ]] || { echo "Missing $v"; exit 1; }
done

cp -a "$SERVER" "$SERVER.bak.$(date +%s)"
cp -a "$CLIENT" "$CLIENT.bak.$(date +%s)"

systemctl stop haproxy 2>/dev/null || true
systemctl stop xray 2>/dev/null || true

cat >"$SERVER" <<EOF
{
  "log": {"loglevel": "warning"},
  "inbounds": [
    {
      "tag": "standard",
      "listen": "127.0.0.1",
      "port": 11000,
      "protocol": "vless",
      "settings": {
        "users": [{"id": "$UUID", "flow": "xtls-rprx-vision"}],
        "decryption": "none"
      },
      "streamSettings": {
        "method": "raw",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "target": "www.cloudflare.com:443",
          "xver": 0,
          "serverNames": ["www.cloudflare.com"],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SID_STANDARD"]
        }
      }
    },
    {
      "tag": "max",
      "listen": "127.0.0.1",
      "port": 11001,
      "protocol": "vless",
      "settings": {
        "users": [{"id": "$UUID", "flow": "xtls-rprx-vision"}],
        "decryption": "none"
      },
      "streamSettings": {
        "method": "raw",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "target": "max.ru:443",
          "xver": 0,
          "serverNames": ["max.ru"],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SID_MAX"]
        }
      }
    },
    {
      "tag": "vk",
      "listen": "127.0.0.1",
      "port": 11002,
      "protocol": "vless",
      "settings": {
        "users": [{"id": "$UUID", "flow": "xtls-rprx-vision"}],
        "decryption": "none"
      },
      "streamSettings": {
        "method": "raw",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "target": "vk.com:443",
          "xver": 0,
          "serverNames": ["vk.com"],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SID_VK"]
        }
      }
    },
    {
      "tag": "vkvideo",
      "listen": "127.0.0.1",
      "port": 11003,
      "protocol": "vless",
      "settings": {
        "users": [{"id": "$UUID", "flow": "xtls-rprx-vision"}],
        "decryption": "none"
      },
      "streamSettings": {
        "method": "raw",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "target": "vkvideo.ru:443",
          "xver": 0,
          "serverNames": ["vkvideo.ru"],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SID_VKVIDEO"]
        }
      }
    },
    {
      "tag": "yadisk",
      "listen": "127.0.0.1",
      "port": 11004,
      "protocol": "vless",
      "settings": {
        "users": [{"id": "$UUID", "flow": "xtls-rprx-vision"}],
        "decryption": "none"
      },
      "streamSettings": {
        "method": "raw",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "target": "disk.yandex.ru:443",
          "xver": 0,
          "serverNames": ["disk.yandex.ru"],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SID_YADISK"]
        }
      }
    }
  ],
  "outbounds": [
    {"tag": "direct", "protocol": "freedom"},
    {"tag": "block", "protocol": "blackhole"}
  ]
}
EOF

cat >/etc/haproxy/haproxy.cfg <<'EOF'
global
    log /dev/log local0
    log /dev/log local1 notice
    maxconn 4096

defaults
    log global
    mode tcp
    option tcplog
    timeout connect 5s
    timeout client 2m
    timeout server 2m

frontend revpn_tls
    bind *:443
    mode tcp
    tcp-request inspect-delay 5s
    tcp-request content accept if { req.ssl_hello_type 1 }

    acl sni_standard req.ssl_sni -i www.cloudflare.com
    acl sni_max req.ssl_sni -i max.ru
    acl sni_vk req.ssl_sni -i vk.com
    acl sni_vkvideo req.ssl_sni -i vkvideo.ru
    acl sni_yadisk req.ssl_sni -i disk.yandex.ru

    use_backend xray_standard if sni_standard
    use_backend xray_max if sni_max
    use_backend xray_vk if sni_vk
    use_backend xray_vkvideo if sni_vkvideo
    use_backend xray_yadisk if sni_yadisk
    default_backend xray_standard

backend xray_standard
    server xray 127.0.0.1:11000
backend xray_max
    server xray 127.0.0.1:11001
backend xray_vk
    server xray 127.0.0.1:11002
backend xray_vkvideo
    server xray 127.0.0.1:11003
backend xray_yadisk
    server xray 127.0.0.1:11004
EOF

"$XRAY_BIN" run -test -config "$SERVER"
haproxy -c -f /etc/haproxy/haproxy.cfg

systemctl daemon-reload
systemctl enable xray haproxy >/dev/null
systemctl restart xray
systemctl restart haproxy

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow 443/tcp >/dev/null
fi

jq '
  .servers[0].name = "Сервер 1"
  | .servers[0].country = ""
  | .servers[0].city = ""
  | .servers[0].masks |= map(
      if .id == "standard" then .name = "Обычный VPN"
      elif .id == "max" then .name = "MAX"
      elif .id == "vk" then .name = "VK"
      elif .id == "vkvideo" then .name = "VK Видео"
      elif .id == "yadisk" then .name = "Яндекс Диск"
      else .
      end
      | .port = 443
    )
' "$CLIENT" > "$CLIENT.tmp"
mv "$CLIENT.tmp" "$CLIENT"

echo
echo "=== ReVPN server status ==="
systemctl is-active xray
systemctl is-active haproxy
ss -ltnp | grep -E ':443|:1100[0-4]' || true
echo
echo "Config OK. Existing UUID/key/shortIds preserved."
echo "Client config: $CLIENT"
