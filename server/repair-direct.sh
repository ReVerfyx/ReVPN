#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash server/repair-direct.sh"
  exit 1
fi

XRAY_BIN="$(command -v xray || true)"
[[ -n "$XRAY_BIN" ]] || { echo "xray not found"; exit 1; }
[[ -f /usr/local/etc/xray/config.json ]] || { echo "Xray config not found"; exit 1; }
[[ -f /root/revpn-client.json ]] || { echo "Client config not found"; exit 1; }

UUID="$(jq -r '.servers[0].uuid // empty' /root/revpn-client.json)"
PUBLIC_KEY="$(jq -r '.servers[0].realityPassword // empty' /root/revpn-client.json)"
SHORT_ID="$(jq -r '.servers[0].masks[] | select(.id=="standard") | .shortId' /root/revpn-client.json | head -n1)"
HOST="$(jq -r '.servers[0].host // empty' /root/revpn-client.json)"
PRIVATE_KEY="$(jq -r '.inbounds[0].streamSettings.realitySettings.privateKey // empty' /usr/local/etc/xray/config.json)"

for v in UUID PUBLIC_KEY SHORT_ID HOST PRIVATE_KEY; do
  [[ -n "${!v}" && "${!v}" != "null" ]] || { echo "Missing $v"; exit 1; }
done

systemctl stop haproxy 2>/dev/null || true
systemctl disable haproxy 2>/dev/null || true
systemctl stop xray 2>/dev/null || true

cat >/usr/local/etc/xray/config.json <<EOF
{
  "log": {"loglevel": "warning"},
  "inbounds": [
    {
      "tag": "revpn",
      "listen": "0.0.0.0",
      "port": 443,
      "protocol": "vless",
      "settings": {
        "users": [
          {
            "id": "$UUID",
            "flow": "xtls-rprx-vision"
          }
        ],
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
          "shortIds": ["$SHORT_ID"]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": ["http", "tls", "quic"]
      }
    }
  ],
  "outbounds": [
    {"tag": "direct", "protocol": "freedom"},
    {"tag": "block", "protocol": "blackhole"}
  ]
}
EOF

"$XRAY_BIN" run -test -config /usr/local/etc/xray/config.json
systemctl daemon-reload
systemctl enable xray
systemctl restart xray

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow 443/tcp
fi

jq '
  .servers[0].name = "Основной сервер"
  | .servers[0].country = ""
  | .servers[0].city = ""
  | .servers[0].masks = [
      (.servers[0].masks[] | select(.id=="standard")
        | .name = "Основной"
        | .description = "Защищённое подключение")
    ]
' /root/revpn-client.json > /root/revpn-client.json.tmp
mv /root/revpn-client.json.tmp /root/revpn-client.json

echo
echo "ReVPN direct server repaired."
echo "Host: $HOST"
echo "Port: 443"
echo "Existing client credentials preserved."
echo
systemctl --no-pager --full status xray | sed -n '1,14p'
