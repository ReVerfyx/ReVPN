#!/usr/bin/env bash
set -euo pipefail

CLIENT=/root/revpn-client.json
XRAY_BIN="$(command -v xray || true)"
[[ -n "$XRAY_BIN" ]] || { echo "xray not found"; exit 1; }
[[ -f "$CLIENT" ]] || { echo "$CLIENT not found"; exit 1; }

UUID="$(jq -r '.servers[0].uuid' "$CLIENT")"
PASSWORD="$(jq -r '.servers[0].realityPassword' "$CLIENT")"

declare -A BACKEND_PORTS=(
  [standard]=11000
  [max]=11001
  [vk]=11002
  [vkvideo]=11003
  [yadisk]=11004
)

test_profile() {
  local label="$1"
  local id="$2"
  local connect_port="$3"

  local sni shortid fingerprint
  sni="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .serverName' "$CLIENT")"
  shortid="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .shortId' "$CLIENT")"
  fingerprint="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | (.fingerprint // "chrome")' "$CLIENT")"

  local cfg="/tmp/revpn-test-$label-$id.json"
  local log="/tmp/revpn-test-$label-$id.log"

  cat >"$cfg" <<EOF
{
  "log": {"loglevel": "info"},
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
      "port": $connect_port,
      "id": "$UUID",
      "encryption": "none",
      "flow": "xtls-rprx-vision"
    },
    "streamSettings": {
      "network": "raw",
      "security": "reality",
      "realitySettings": {
        "serverName": "$sni",
        "fingerprint": "$fingerprint",
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

  if curl -fsS --max-time 8 --socks5-hostname 127.0.0.1:10808 https://cp.cloudflare.com/generate_204 >/dev/null; then
    echo "PASS  $label  $id  $sni  port=$connect_port"
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    rm -f "$cfg" "$log"
    return 0
  else
    echo "FAIL  $label  $id  $sni  port=$connect_port"
    tail -n 12 "$log" || true
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
echo "=== direct VPS internet ==="
if curl -4fsS --max-time 8 https://cp.cloudflare.com/generate_204 >/dev/null; then
  echo "PASS  VPS egress"
else
  echo "FAIL  VPS egress"
fi

echo
echo "=== direct Xray backends (bypass HAProxy) ==="
direct_failed=0
for id in standard max vk vkvideo yadisk; do
  test_profile backend "$id" "${BACKEND_PORTS[$id]}" || direct_failed=1
done

echo
echo "=== through HAProxy :443 ==="
haproxy_failed=0
for id in standard max vk vkvideo yadisk; do
  test_profile haproxy "$id" 443 || haproxy_failed=1
done

echo
echo "=== diagnosis ==="
if [[ "$direct_failed" -eq 0 && "$haproxy_failed" -eq 0 ]]; then
  echo "ALL TESTS PASS"
elif [[ "$direct_failed" -eq 0 && "$haproxy_failed" -ne 0 ]]; then
  echo "XRAY_BACKENDS_OK__HAPROXY_BROKEN"
elif [[ "$direct_failed" -ne 0 ]]; then
  echo "XRAY_OR_REALITY_CONFIG_BROKEN"
else
  echo "UNKNOWN_FAILURE"
fi

echo
echo "=== recent server logs ==="
journalctl -u xray -n 40 --no-pager || true
