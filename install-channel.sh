#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Запусти sudo bash install-channel.sh'; exit 1; }
src_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
apt-get update
apt-get install -y python3-venv curl
id revpnchannel >/dev/null 2>&1 || useradd --system --home /var/lib/revpn-channel --shell /usr/sbin/nologin revpnchannel
install -d -m 755 /opt/revpn-channel
install -d -o revpnchannel -g revpnchannel -m 700 /var/lib/revpn-channel
python3 -m venv /opt/revpn-channel/venv
/opt/revpn-channel/venv/bin/pip install -r "$src_dir/requirements-channel.txt"
if ! command -v ollama >/dev/null; then
  ollama_installer="$(mktemp)"
  trap 'rm -f "$ollama_installer"' EXIT
  curl --fail --show-error --location --max-time 120 https://ollama.com/install.sh -o "$ollama_installer"
  sh "$ollama_installer"
fi
systemctl enable --now ollama
ollama pull qwen3:0.6b
systemctl stop revpn-channel 2>/dev/null || true
install -m 644 "$src_dir/channel_agent.py" "$src_dir/channel_news.py" /opt/revpn-channel/
cat > /usr/local/bin/revpn-channel <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -eq 0 ]]; then
  exec runuser -u revpnchannel -- /opt/revpn-channel/venv/bin/python /opt/revpn-channel/channel_agent.py "$@"
fi
exec /opt/revpn-channel/venv/bin/python /opt/revpn-channel/channel_agent.py "$@"
WRAPPER
chmod 755 /usr/local/bin/revpn-channel
cat > /etc/systemd/system/revpn-channel.service <<'UNIT'
[Unit]
Description=ReVPN AI channel publisher
Wants=network-online.target
After=network-online.target ollama.service
[Service]
User=revpnchannel
Group=revpnchannel
WorkingDirectory=/opt/revpn-channel
ExecStart=/opt/revpn-channel/venv/bin/python /opt/revpn-channel/channel_agent.py run
Restart=on-failure
RestartSec=30
UMask=0077
Nice=10
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/revpn-channel
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
printf '\nГотово. Настрой: sudo revpn-channel configure\nВход: sudo revpn-channel login\nПосмотреть пост: sudo revpn-channel preview\nВключить публикации: sudo systemctl enable --now revpn-channel\n'
