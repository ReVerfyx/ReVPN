#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash server/pin-reality-targets-ipv4.sh"
  exit 1
fi

CLIENT=/root/revpn-client.json
SERVER=/usr/local/etc/xray/config.json
XRAY_BIN="$(command -v xray || true)"

[[ -n "$XRAY_BIN" ]] || { echo "xray not found"; exit 1; }
[[ -f "$CLIENT" ]] || { echo "$CLIENT not found"; exit 1; }
[[ -f "$SERVER" ]] || { echo "$SERVER not found"; exit 1; }

UUID="$(jq -r '.servers[0].uuid' "$CLIENT")"
PASSWORD="$(jq -r '.servers[0].realityPassword' "$CLIENT")"
PRIVATE_KEY="$(jq -r '[.inbounds[].streamSettings.realitySettings.privateKey // empty] | map(select(length>0)) | .[0] // empty' "$SERVER")"

profiles=(standard max vk vkvideo yadisk)

resolve_v4() {
  local host="$1"
  getent ahostsv4 "$host" 2>/dev/null |
    awk '{print $1}' |
    awk '!seen[$0]++' |
    head -n 4
}

probe_ip() {
  local id="$1" sni="$2" shortid="$3" fingerprint="$4" ip="$5"
  local server_cfg=/tmp/revpn-pin-server.json
  local client_cfg=/tmp/revpn-pin-client.json
  local server_log=/tmp/revpn-pin-server.log
  local client_log=/tmp/revpn-pin-client.log

  cat >"$server_cfg" <<EOF
{
  "log": {"loglevel": "warning"},
  "inbounds": [{
    "listen": "127.0.0.1",
    "port": 11943,
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
        "target": "$ip:443",
        "xver": 0,
        "serverNames": ["$sni"],
        "privateKey": "$PRIVATE_KEY",
        "shortIds": ["$shortid"]
      }
    }
  }],
  "outbounds": [{"tag": "direct", "protocol": "freedom"}]
}
EOF

  cat >"$client_cfg" <<EOF
{
  "log": {"loglevel": "warning"},
  "inbounds": [{
    "listen": "127.0.0.1",
    "port": 11808,
    "protocol": "socks",
    "settings": {"udp": true}
  }],
  "outbounds": [{
    "tag": "proxy",
    "protocol": "vless",
    "settings": {
      "address": "127.0.0.1",
      "port": 11943,
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

  "$XRAY_BIN" run -test -config "$server_cfg" >/dev/null 2>&1 || return 1
  "$XRAY_BIN" run -test -config "$client_cfg" >/dev/null 2>&1 || return 1

  "$XRAY_BIN" run -config "$server_cfg" >"$server_log" 2>&1 &
  local spid=$!
  sleep 0.5
  "$XRAY_BIN" run -config "$client_cfg" >"$client_log" 2>&1 &
  local cpid=$!
  sleep 0.5

  local pass=0
  for n in 1 2; do
    if curl -fsS --max-time 4 --socks5-hostname 127.0.0.1:11808 https://www.google.com/generate_204 >/dev/null 2>&1; then
      pass=$((pass+1))
    fi
    sleep 0.15
  done

  kill "$cpid" "$spid" 2>/dev/null || true
  wait "$cpid" 2>/dev/null || true
  wait "$spid" 2>/dev/null || true
  rm -f "$server_cfg" "$client_cfg" "$server_log" "$client_log"

  [[ "$pass" -ge 1 ]]
}

cp -a "$SERVER" "$SERVER.bak.$(date +%s)"

echo "=== pinning REALITY targets to tested IPv4 edges ==="

for id in "${profiles[@]}"; do
  sni="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .serverName' "$CLIENT")"
  shortid="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | .shortId' "$CLIENT")"
  fingerprint="$(jq -r --arg id "$id" '.servers[0].masks[] | select(.id==$id) | (.fingerprint // "firefox")' "$CLIENT")"

  echo
  echo "[$id] $sni / $fingerprint"

  chosen=""
  while read -r ip; do
    [[ -n "$ip" ]] || continue
    printf '  %-15s ' "$ip"
    if probe_ip "$id" "$sni" "$shortid" "$fingerprint" "$ip"; then
      echo "PASS"
      chosen="$ip"
      break
    else
      echo "FAIL"
    fi
  done < <(resolve_v4 "$sni")

  if [[ -n "$chosen" ]]; then
    jq --arg tag "$id" --arg target "$chosen:443" '
      .inbounds |= map(
        if .tag == $tag then
          .streamSettings.realitySettings.target = $target
        else .
        end
      )
    ' "$SERVER" > "$SERVER.tmp"
    mv "$SERVER.tmp" "$SERVER"
    echo "  selected: $chosen:443"
  else
    echo "  no stable IPv4 edge found; keeping current target"
  fi
done

echo
"$XRAY_BIN" run -test -config "$SERVER"
systemctl restart xray
systemctl restart nginx

echo
echo "=== pinned targets ==="
jq -r '.inbounds[] | "(.tag): (.streamSettings.realitySettings.target) / (.streamSettings.realitySettings.serverNames[0])"' "$SERVER"

echo
echo "=== stability after IPv4 pinning ==="
bash "$(dirname "$0")/test-stability.sh"
