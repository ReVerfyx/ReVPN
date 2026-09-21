#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash server/repair-full.sh"
  exit 1
fi

XRAY_BIN="$(command -v xray || true)"
[[ -n "$XRAY_BIN" ]] || { echo "xray not found"; exit 1; }
[[ -f /root/revpn-client.json ]] || { echo "/root/revpn-client.json not found"; exit 1; }
[[ -f /usr/local/etc/xray/config.json ]] || { echo "/usr/local/etc/xray/config.json not found"; exit 1; }

apt-get update >/dev/null
DEBIAN_FRONTEND=noninteractive apt-get install -y jq curl haproxy >/dev/null

CLIENT=/root/revpn-client.json
SERVER=/usr/local/etc/xray/config.json

HOST="$(jq -r '.servers[0].host // empty' "$CLIENT")"
UUID="$(jq -r '.servers[0].uuid // empty' "$CLIENT")"
PUBLIC_KEY="$(jq -r '.servers[0].realityPassword // empty' "$CLIENT")"
PRIVATE_KEY="$(jq -r '.inbounds[0].streamSettings.realitySettings.privateKey // empty' "$SERVER")"

mask_value() {
  local id="$1" field="$2"
  jq -r --arg id "$id" --arg field "$field" '.servers[0].masks[] | select(.id==$id) | .[$field] // empty' "$CLIENT" | head -n1
}

SID_STANDARD="$(mask_value standard shortId)"
SID_MAX="$(mask_value max shortId)"
SID_VK="$(mask_value vk shortId)"
SID_VKVIDEO="$(mask_value vkvideo shortId)"
SID_YADISK="$(mask_value yadisk shortId)"

for v in HOST UUID PUBLIC_KEY PRIVATE_KEY SID_STANDARD SID_MAX SID_VK SID_VKVIDEO SID_YADISK; do
  [[ -n "${!v}" && "${!v}" != "null" ]] || { echo "Missing value: $v"; exit 1; }
done

COUNTRY=""
CITY=""
GEO="$(curl -fsS --max-time 8 "https://ipwho.is/$HOST" || true)"
if [[ -n "$GEO" ]] && [[ "$(jq -r '.success // false' <<<"$GEO" 2>/dev/null || true)" == "true" ]]; then
  COUNTRY="$(jq -r '.country // empty' <<<"$GEO")"
  CITY="$(jq -r '.city // empty' <<<"$GEO")"
fi
[[ -n "$COUNTRY" ]] || COUNTRY="Не определено"
[[ -n "$CITY" ]] || CITY="Авто"

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
      "settings": {"users": [{"id": "$UUID", "flow": "xtls-rprx-vision"}], "decryption": "none"},
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
      "settings": {"users": [{"id": "$UUID", "flow": "xtls-rprx-vision"}], "decryption": "none"},
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
      "settings": {"users": [{"id": "$UUID", "flow": "xtls-rprx-vision"}], "decryption": "none"},
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
      "settings": {"users": [{"id": "$UUID", "flow": "xtls-rprx-vision"}], "decryption": "none"},
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
      "settings": {"users": [{"id": "$UUID", "flow": "xtls-rprx-vision"}], "decryption": "none"},
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

jq --arg country "$COUNTRY" --arg city "$CITY" '
  .servers[0].name = "ReVPN #1"
  | .servers[0].country = $country
  | .servers[0].city = $city
' "$CLIENT" > "$CLIENT.tmp"
mv "$CLIENT.tmp" "$CLIENT"

systemctl enable xray haproxy >/dev/null
systemctl restart xray
systemctl restart haproxy

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow 443/tcp >/dev/null
fi

echo
echo "ReVPN server repaired."
echo "Location: $COUNTRY / $CITY"
echo "Public host: $HOST"
echo
systemctl is-active xray haproxy
ss -ltnp | grep -E ':443|:1100[0-4]' || true
echo
echo "Updated client config:"
cat "$CLIENT"
