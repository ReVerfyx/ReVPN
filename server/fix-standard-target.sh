#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash server/fix-standard-target.sh"
  exit 1
fi

CLIENT=/root/revpn-client.json
SERVER=/usr/local/etc/xray/config.json
HAPROXY=/etc/haproxy/haproxy.cfg
XRAY_BIN="$(command -v xray || true)"

[[ -n "$XRAY_BIN" ]] || { echo "xray not found"; exit 1; }
[[ -f "$CLIENT" ]] || { echo "$CLIENT not found"; exit 1; }
[[ -f "$SERVER" ]] || { echo "$SERVER not found"; exit 1; }
[[ -f "$HAPROXY" ]] || { echo "$HAPROXY not found"; exit 1; }

UUID="$(jq -r '.servers[0].uuid // empty' "$CLIENT")"
PUBLIC_KEY="$(jq -r '.servers[0].realityPassword // empty' "$CLIENT")"
SID="$(jq -r '.servers[0].masks[] | select(.id=="standard") | .shortId' "$CLIENT" | head -n1)"
PRIVATE_KEY="$(jq -r '[.inbounds[].streamSettings.realitySettings.privateKey // empty] | map(select(length>0)) | .[0] // empty' "$SERVER")"

for v in UUID PUBLIC_KEY SID PRIVATE_KEY; do
  [[ -n "${!v}" && "${!v}" != "null" ]] || { echo "Missing $v"; exit 1; }
done

candidates=(
  "www.apple.com"
  "www.cloudflare.com"
  "www.google.com"
  "www.amazon.com"
  "www.samsung.com"
  "www.nvidia.com"
)
fingerprints=("chrome" "firefox")

cleanup() {
  [[ -n "${CLIENT_PID:-}" ]] && kill "$CLIENT_PID" 2>/dev/null || true
  [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true
  wait "${CLIENT_PID:-}" 2>/dev/null || true
  wait "${SERVER_PID:-}" 2>/dev/null || true
  rm -f /tmp/revpn-probe-server.json /tmp/revpn-probe-client.json /tmp/revpn-probe-server.log /tmp/revpn-probe-client.log
}
trap cleanup EXIT

probe() {
  local target="$1" fp="$2"

  cat >/tmp/revpn-probe-server.json <<EOF
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
        "target": "$target:443",
        "xver": 0,
        "serverNames": ["$target"],
        "privateKey": "$PRIVATE_KEY",
        "shortIds": ["$SID"]
      }
    }
  }],
  "outbounds": [{"tag": "direct", "protocol": "freedom"}]
}
EOF

  cat >/tmp/revpn-probe-client.json <<EOF
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
        "serverName": "$target",
        "fingerprint": "$fp",
        "password": "$PUBLIC_KEY",
        "shortId": "$SID",
        "spiderX": "/"
      }
    }
  }]
}
EOF

  "$XRAY_BIN" run -test -config /tmp/revpn-probe-server.json >/dev/null
  "$XRAY_BIN" run -test -config /tmp/revpn-probe-client.json >/dev/null

  "$XRAY_BIN" run -config /tmp/revpn-probe-server.json >/tmp/revpn-probe-server.log 2>&1 &
  SERVER_PID=$!
  sleep 0.6
  "$XRAY_BIN" run -config /tmp/revpn-probe-client.json >/tmp/revpn-probe-client.log 2>&1 &
  CLIENT_PID=$!
  sleep 0.8

  if curl -fsS --max-time 7 --socks5-hostname 127.0.0.1:11808 https://cp.cloudflare.com/generate_204 >/dev/null; then
    kill "$CLIENT_PID" "$SERVER_PID" 2>/dev/null || true
    wait "$CLIENT_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    CLIENT_PID=""
    SERVER_PID=""
    return 0
  fi

  kill "$CLIENT_PID" "$SERVER_PID" 2>/dev/null || true
  wait "$CLIENT_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
  CLIENT_PID=""
  SERVER_PID=""
  return 1
}

chosen=""
chosen_fp=""

echo "=== probing REALITY targets for ordinary VPN ==="
for target in "${candidates[@]}"; do
  for fp in "${fingerprints[@]}"; do
    printf '%-24s %-8s ' "$target" "$fp"
    if probe "$target" "$fp"; then
      echo "PASS"
      chosen="$target"
      chosen_fp="$fp"
      break 2
    else
      echo "FAIL"
    fi
  done
done

[[ -n "$chosen" ]] || {
  echo "No candidate passed. Current server files were not changed."
  exit 1
}

echo
echo "Selected: $chosen / $chosen_fp"

cp -a "$SERVER" "$SERVER.bak.$(date +%s)"
cp -a "$CLIENT" "$CLIENT.bak.$(date +%s)"
cp -a "$HAPROXY" "$HAPROXY.bak.$(date +%s)"

jq --arg target "$chosen:443" --arg sni "$chosen" '
  .inbounds |= map(
    if .tag == "standard" then
      .streamSettings.realitySettings.target = $target
      | .streamSettings.realitySettings.serverNames = [$sni]
    else .
    end
  )
' "$SERVER" > "$SERVER.tmp"
mv "$SERVER.tmp" "$SERVER"

jq --arg sni "$chosen" --arg fp "$chosen_fp" '
  .servers[0].masks |= map(
    if .id == "standard" then
      .serverName = $sni
      | .fingerprint = $fp
      | .description = "REALITY / авто"
    else .
    end
  )
' "$CLIENT" > "$CLIENT.tmp"
mv "$CLIENT.tmp" "$CLIENT"

sed -i -E "s|^[[:space:]]*acl sni_standard req\.ssl_sni -i .*|    acl sni_standard req.ssl_sni -i $chosen|" "$HAPROXY"

"$XRAY_BIN" run -test -config "$SERVER"
haproxy -c -f "$HAPROXY"

systemctl restart xray
systemctl restart haproxy

echo
echo "=== final test ==="
bash "$(dirname "$0")/test-vpn.sh"
echo
echo "Ordinary VPN target repaired: $chosen ($chosen_fp)"
echo "Client config changed: $CLIENT"
echo "Update REVPN_SERVER_CONFIG_BASE64 before the next APK/AAB build."
