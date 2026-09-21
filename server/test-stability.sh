#!/usr/bin/env bash
set -euo pipefail

CLIENT=/root/revpn-client.json
XRAY_BIN="$(command -v xray || true)"
[[ -n "$XRAY_BIN" ]] || { echo "xray not found"; exit 1; }
[[ -f "$CLIENT" ]] || { echo "$CLIENT not found"; exit 1; }

UUID="$(jq -r '.servers[0].uuid' "$CLIENT")"
PASSWORD="$(jq -r '.servers[0].realityPassword' "$CLIENT")"

test_once() {
  local id="$1" address="$2" port="$3"
  local sni shortid fingerprint cfg log
  sni="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .serverName' "$CLIENT")"
  shortid="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .shortId' "$CLIENT")"
  fingerprint="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | (.fingerprint // "firefox")' "$CLIENT")"
  cfg="/tmp/revpn-stability-$id.json"
  log="/tmp/revpn-stability-$id.log"

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
      "address": "$address",
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
  local pid=$!
  sleep 0.8

  local ok=1
  if curl -fsS --max-time 7 --socks5-hostname 127.0.0.1:10808 https://www.google.com/generate_204 >/dev/null 2>&1; then
    ok=0
  fi

  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  rm -f "$cfg"
  return "$ok"
}

score_profile() {
  local id="$1" address="$2" port="$3" label="$4"
  local pass=0
  for n in 1 2 3; do
    if test_once "$id" "$address" "$port"; then
      pass=$((pass+1))
    fi
    sleep 0.4
  done
  printf '%-9s %-9s %s/3
' "$label" "$id" "$pass"
  [[ "$pass" -ge 2 ]]
}

echo "=== repeated backend tests ==="
backend_failed=0
score_profile standard 127.0.0.1 11000 backend || backend_failed=1
score_profile max 127.0.0.1 11001 backend || backend_failed=1
score_profile vk 127.0.0.1 11002 backend || backend_failed=1
score_profile vkvideo 127.0.0.1 11003 backend || backend_failed=1
score_profile yadisk 127.0.0.1 11004 backend || backend_failed=1

echo
echo "=== repeated HAProxy tests ==="
proxy_failed=0
for id in standard max vk vkvideo yadisk; do
  score_profile "$id" 127.0.0.1 443 haproxy || proxy_failed=1
done

echo
if [[ "$backend_failed" -eq 0 && "$proxy_failed" -eq 0 ]]; then
  echo "STABLE: all profiles passed at least 2/3 attempts"
  exit 0
fi

if [[ "$backend_failed" -eq 0 && "$proxy_failed" -ne 0 ]]; then
  echo "DIAGNOSIS: HAProxy SNI routing is unstable"
  exit 2
fi

if [[ "$backend_failed" -ne 0 ]]; then
  echo "DIAGNOSIS: one or more REALITY targets are unstable"
  exit 3
fi
