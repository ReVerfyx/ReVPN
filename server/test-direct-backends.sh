#!/usr/bin/env bash
set -euo pipefail

CLIENT=/root/revpn-client.json
XRAY_BIN="$(command -v xray || true)"
[[ -n "$XRAY_BIN" ]] || { echo "xray not found"; exit 1; }
[[ -f "$CLIENT" ]] || { echo "$CLIENT not found"; exit 1; }

UUID="$(jq -r '.servers[0].uuid' "$CLIENT")"
PASSWORD="$(jq -r '.servers[0].realityPassword' "$CLIENT")"

test_direct() {
  local id="$1" backend_port="$2"
  local sni shortid fingerprint
  sni="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .serverName' "$CLIENT")"
  shortid="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .shortId' "$CLIENT")"
  fingerprint="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | (.fingerprint // "chrome")' "$CLIENT")"

  local cfg="/tmp/revpn-direct-$id.json"
  local log="/tmp/revpn-direct-$id.log"

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
      "port": $backend_port,
      "id": "$UUID",
      "encryption": "none",
      "flow": "xtls-rprx-vision"
    },
    "streamSettings": {
      "method": "raw",
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
    echo "PASS  $id  backend:$backend_port"
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    rm -f "$cfg" "$log"
    return 0
  else
    echo "FAIL  $id  backend:$backend_port"
    tail -n 12 "$log" || true
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    rm -f "$cfg"
    return 1
  fi
}

failed=0
test_direct standard 11000 || failed=1
test_direct max 11001 || failed=1
test_direct vk 11002 || failed=1
test_direct vkvideo 11003 || failed=1
test_direct yadisk 11004 || failed=1

if [[ "$failed" -eq 0 ]]; then
  echo "DIRECT BACKENDS OK"
else
  echo "DIRECT BACKEND TEST FAILED"
  exit 1
fi
