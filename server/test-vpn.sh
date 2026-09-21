#!/usr/bin/env bash
set -euo pipefail

CLIENT=/root/revpn-client.json
XRAY_BIN="$(command -v xray || true)"
[[ -n "$XRAY_BIN" ]] || { echo "xray not found"; exit 1; }
[[ -f "$CLIENT" ]] || { echo "$CLIENT not found"; exit 1; }

UUID="$(jq -r '.servers[0].uuid' "$CLIENT")"
PASSWORD="$(jq -r '.servers[0].realityPassword' "$CLIENT")"

test_profile() {
  local id="$1"
  local sni shortid port
  sni="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .serverName' "$CLIENT")"
  shortid="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .shortId' "$CLIENT")"
  port="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .port' "$CLIENT")"

  local cfg="/tmp/revpn-test-$id.json"
  local log="/tmp/revpn-test-$id.log"
  cat >"$cfg" <<EOF
{
  "log": {"loglevel": "warning"},
  "inbounds": [{
    "listen": "127.0.0.1",
    "port": 10808,
    "protocol": "socks",
    "settings": {"udp": true}
  }],
  "outbounds": [{
    "tag": "proxy",
    "protocol": "vless",
    "settings": {
      "address": "127.0.0.1",
      "port": $port,
      "id": "$UUID",
      "encryption": "none",
      "flow": "xtls-rprx-vision"
    },
    "streamSettings": {
      "method": "raw",
      "security": "reality",
      "realitySettings": {
        "serverName": "$sni",
        "fingerprint": "chrome",
        "password": "$PASSWORD",
        "shortId": "$shortid",
        "spiderX": "/"
      }
    }
  }]
}
EOF

  "$XRAY_BIN" run -config "$cfg" >"$log" 2>&1 &
  local pid=$!
  sleep 1

  if curl -fsS --max-time 10 --socks5-hostname 127.0.0.1:10808 https://cp.cloudflare.com/generate_204 >/dev/null; then
    echo "PASS  $id  $sni"
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    rm -f "$cfg" "$log"
    return 0
  else
    echo "FAIL  $id  $sni"
    tail -n 8 "$log" || true
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    rm -f "$cfg"
    return 1
  fi
}

echo "=== services ==="
systemctl is-active xray || true
systemctl is-active haproxy || true
ss -ltnp | grep -E ':443|:1100[0-4]' || true
echo
echo "=== REALITY profiles ==="

failed=0
for id in standard max vk vkvideo yadisk; do
  test_profile "$id" || failed=1
done

echo
if [[ "$failed" -eq 0 ]]; then
  echo "ALL PROFILES PASS"
else
  echo "ONE OR MORE PROFILES FAILED"
  exit 1
fi
