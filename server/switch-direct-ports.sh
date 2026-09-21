#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash server/switch-direct-ports.sh"
  exit 1
fi

CLIENT=/root/revpn-client.json
SERVER=/usr/local/etc/xray/config.json
XRAY_BIN="$(command -v xray || true)"

[[ -n "$XRAY_BIN" ]] || { echo "xray not found"; exit 1; }
[[ -f "$CLIENT" ]] || { echo "$CLIENT not found"; exit 1; }
[[ -f "$SERVER" ]] || { echo "$SERVER not found"; exit 1; }

cp -a "$CLIENT" "$CLIENT.bak.$(date +%s)"
cp -a "$SERVER" "$SERVER.bak.$(date +%s)"

systemctl stop nginx 2>/dev/null || true
systemctl disable nginx 2>/dev/null || true
systemctl stop haproxy 2>/dev/null || true
systemctl disable haproxy 2>/dev/null || true
systemctl stop xray 2>/dev/null || true

jq '
  .inbounds |= map(
    if .tag == "standard" then .listen = "0.0.0.0" | .port = 443
    elif .tag == "max" then .listen = "0.0.0.0" | .port = 8443
    elif .tag == "vk" then .listen = "0.0.0.0" | .port = 9443
    elif .tag == "vkvideo" then .listen = "0.0.0.0" | .port = 10443
    elif .tag == "yadisk" then .listen = "0.0.0.0" | .port = 11443
    else .
    end
  )
' "$SERVER" > "$SERVER.tmp"
mv "$SERVER.tmp" "$SERVER"

jq '
  .servers[0].masks |= map(
    if .id == "standard" then .port = 443
    elif .id == "max" then .port = 8443
    elif .id == "vk" then .port = 9443
    elif .id == "vkvideo" then .port = 10443
    elif .id == "yadisk" then .port = 11443
    else .
    end
  )
' "$CLIENT" > "$CLIENT.tmp"
mv "$CLIENT.tmp" "$CLIENT"

"$XRAY_BIN" run -test -config "$SERVER"

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow 443/tcp >/dev/null
  ufw allow 8443/tcp >/dev/null
  ufw allow 9443/tcp >/dev/null
  ufw allow 10443/tcp >/dev/null
  ufw allow 11443/tcp >/dev/null
fi

systemctl daemon-reload
systemctl enable xray >/dev/null
systemctl restart xray

echo
echo "=== direct profile listeners ==="
systemctl is-active xray
ss -ltnp | grep -E ':443|:8443|:9443|:10443|:11443' || true

echo
echo "=== client ports ==="
jq -r '.servers[0].masks[] | "\(.id): \(.serverName):\(.port) / \(.fingerprint)"' "$CLIENT"

echo
echo "=== repeated direct tests ==="
bash "$(dirname "$0")/test-direct-public-ports.sh"
