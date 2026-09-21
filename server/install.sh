#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash server/install.sh"
  exit 1
fi

SERVER_NAME="${SERVER_NAME:-Мой VPS}"
COUNTRY="${COUNTRY:-Нидерланды}"
CITY="${CITY:-Амстердам}"
PUBLIC_HOST="${PUBLIC_HOST:-}"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates jq openssl haproxy

if ! command -v xray >/dev/null 2>&1; then
  bash <(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh) install
fi

systemctl stop haproxy 2>/dev/null || true
systemctl stop xray 2>/dev/null || true

if ss -H -ltn '( sport = :443 )' | grep -q .; then
  echo "Port 443 is already occupied. Stop the process using it, then run the installer again."
  ss -ltnp '( sport = :443 )' || true
  exit 1
fi

if [[ -z "$PUBLIC_HOST" ]]; then
  PUBLIC_HOST="$(curl -4fsS --max-time 5 https://api.ipify.org || true)"
fi
if [[ -z "$PUBLIC_HOST" ]]; then
  PUBLIC_HOST="$(hostname -I | awk '{print $1}')"
fi
if [[ -z "$PUBLIC_HOST" ]]; then
  echo "Could not detect public IP. Run: PUBLIC_HOST=1.2.3.4 sudo -E bash server/install.sh"
  exit 1
fi

UUID="$(xray uuid | tr -d '\r\n')"
KEYS="$(xray x25519)"
PRIVATE_KEY="$(printf '%s\n' "$KEYS" | awk -F': ' '/^PrivateKey:/ {print $2}')"
REALITY_PASSWORD="$(printf '%s\n' "$KEYS" | awk -F': ' '/^Password \(PublicKey\):/ {print $2}')"

if [[ -z "$PRIVATE_KEY" || -z "$REALITY_PASSWORD" ]]; then
  echo "Could not parse Xray X25519 keys:"
  echo "$KEYS"
  exit 1
fi

SID_MAX="$(openssl rand -hex 8)"
SID_VK="$(openssl rand -hex 8)"
SID_VKVIDEO="$(openssl rand -hex 8)"
SID_YADISK="$(openssl rand -hex 8)"

mkdir -p /usr/local/etc/xray

cat >/usr/local/etc/xray/config.json <<EOF
{
  "log": {"loglevel": "warning"},
  "inbounds": [
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

    acl sni_max req.ssl_sni -i max.ru
    acl sni_vk req.ssl_sni -i vk.com
    acl sni_vkvideo req.ssl_sni -i vkvideo.ru
    acl sni_yadisk req.ssl_sni -i disk.yandex.ru

    use_backend xray_max if sni_max
    use_backend xray_vk if sni_vk
    use_backend xray_vkvideo if sni_vkvideo
    use_backend xray_yadisk if sni_yadisk
    default_backend xray_max

backend xray_max
    server xray 127.0.0.1:11001

backend xray_vk
    server xray 127.0.0.1:11002

backend xray_vkvideo
    server xray 127.0.0.1:11003

backend xray_yadisk
    server xray 127.0.0.1:11004
EOF

haproxy -c -f /etc/haproxy/haproxy.cfg

jq -n   --arg id "server-1"   --arg name "$SERVER_NAME"   --arg country "$COUNTRY"   --arg city "$CITY"   --arg host "$PUBLIC_HOST"   --arg uuid "$UUID"   --arg password "$REALITY_PASSWORD"   --arg sidMax "$SID_MAX"   --arg sidVk "$SID_VK"   --arg sidVkVideo "$SID_VKVIDEO"   --arg sidYaDisk "$SID_YADISK"   '{
    servers: [{
      id: $id,
      name: $name,
      country: $country,
      city: $city,
      host: $host,
      uuid: $uuid,
      realityPassword: $password,
      masks: [
        {id:"max",name:"MAX",description:"REALITY / SNI",serverName:"max.ru",port:443,shortId:$sidMax,fingerprint:"chrome"},
        {id:"vk",name:"VK",description:"REALITY / SNI",serverName:"vk.com",port:443,shortId:$sidVk,fingerprint:"chrome"},
        {id:"vkvideo",name:"VK Видео",description:"REALITY / SNI",serverName:"vkvideo.ru",port:443,shortId:$sidVkVideo,fingerprint:"chrome"},
        {id:"yadisk",name:"Яндекс Диск",description:"REALITY / SNI",serverName:"disk.yandex.ru",port:443,shortId:$sidYaDisk,fingerprint:"chrome"}
      ]
    }]
  }' >/root/revpn-client.json

systemctl enable xray haproxy
systemctl restart xray
systemctl restart haproxy

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow 443/tcp
fi

echo
echo "ReVPN server is ready."
echo "Public host: $PUBLIC_HOST"
echo "Client config: /root/revpn-client.json"
echo
cat /root/revpn-client.json
echo
echo "Important: REALITY/SNI camouflage changes the TLS appearance only."
echo "If a mobile operator enforces a strict destination-IP allowlist, the VPS IP can still be blocked."
