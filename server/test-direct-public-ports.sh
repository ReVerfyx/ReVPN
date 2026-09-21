#!/usr/bin/env bash
set -euo pipefail

CLIENT=/root/revpn-client.json
XRAY_BIN="$(command -v xray || true)"
[[ -n "$XRAY_BIN" ]] || { echo "xray not found"; exit 1; }
[[ -f "$CLIENT" ]] || { echo "$CLIENT not found"; exit 1; }

UUID="$(jq -r '.servers[0].uuid' "$CLIENT")"
PASSWORD="$(jq -r '.servers[0].realityPassword' "$CLIENT")"

test_once() {
  local id="$1"
  local sni shortid fingerprint port cfg log pid
  sni="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .serverName' "$CLIENT")"
  shortid="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .shortId' "$CLIENT")"
  fingerprint="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | (.fingerprint // "firefox")' "$CLIENT")"
  port="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .port' "$CLIENT")"
  cfg="/tmp/revpn-direct-public-$id.json"
  log="/tmp/revpn-direct-public-$id.log"

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
  pid=$!
  sleep 0.7
  local rc=1
  if curl -fsS --max-time 6 --socks5-hostname 127.0.0.1:10808 https://www.google.com/generate_204 >/dev/null 2>&1; then
    rc=0
  fi
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -f "$cfg" "$log"
  return "$rc"
}

failed=0
for id in standard max vk vkvideo yadisk; do
  pass=0
  for n in 1 2 3; do
    if test_once "$id"; then pass=$((pass+1)); fi
    sleep 0.3
  done
  printf '%-9s %s/3\n' "$id" "$pass"
  [[ "$pass" -ge 2 ]] || failed=1
done

echo
if [[ "$failed" -eq 0 ]]; then
  echo "DIRECT PORTS STABLE"
  exit 0
else
  echo "ONE OR MORE DIRECT PROFILES UNSTABLE"
  exit 1
fi
