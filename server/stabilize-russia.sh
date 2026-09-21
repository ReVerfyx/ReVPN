#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash server/stabilize-russia.sh"
  exit 1
fi

CLIENT=/root/revpn-client.json
[[ -f "$CLIENT" ]] || { echo "$CLIENT not found"; exit 1; }

cp -a "$CLIENT" "$CLIENT.bak.$(date +%s)"

jq '
  .servers[0].masks |= map(
    .fingerprint = "firefox"
  )
' "$CLIENT" > "$CLIENT.tmp"
mv "$CLIENT.tmp" "$CLIENT"

echo "All client profiles switched to firefox fingerprint."
echo "Running repeated stability test..."
bash "$(dirname "$0")/test-stability.sh"
