#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Запусти sudo bash install-channel.sh'; exit 1; }
src_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mode="${1:-install}"
[[ "$mode" == install || "$mode" == --update ]] || { echo 'Использование: install-channel.sh [--update]'; exit 1; }
[[ -f /etc/revpn-shop/config.json ]] || { echo 'Сначала установи магазин через install.sh'; exit 1; }
if [[ "$mode" != --update ]]; then
  apt-get update
  apt-get install -y python3 curl
fi
id revpnchannel >/dev/null 2>&1 || useradd --system --home /var/lib/revpn-channel --shell /usr/sbin/nologin revpnchannel
install -d -m 755 /opt/revpn-channel
install -d -o revpnchannel -g revpnchannel -m 700 /var/lib/revpn-channel
if [[ "$mode" != --update ]]; then
if ! command -v ollama >/dev/null; then
  ollama_installer="$(mktemp)"
  trap 'rm -f "$ollama_installer"' EXIT
  curl --fail --show-error --location --max-time 120 https://ollama.com/install.sh -o "$ollama_installer"
  sh "$ollama_installer"
fi
systemctl enable --now ollama
ollama pull qwen3:0.6b
fi
was_active=false
if systemctl is-active --quiet revpn-channel; then was_active=true; fi
systemctl stop revpn-channel 2>/dev/null || true
install -m 644 "$src_dir/channel_agent.py" "$src_dir/channel_news.py" /opt/revpn-channel/
# Copy only the Telegram token; the news user cannot read payment/panel secrets.
python3 - <<'TOKEN'
import json, os, pwd
from pathlib import Path
cfg=json.loads(Path('/etc/revpn-shop/config.json').read_text())
root=Path('/var/lib/revpn-channel')
target=root/'bot-token'
fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
with os.fdopen(fd,'w') as out: out.write(cfg['telegram']['token']+'\n')
who=pwd.getpwnam('revpnchannel')
os.chown(target,who.pw_uid,who.pw_gid);os.chmod(target,0o600)
path=root/'channel.json'
if path.exists():
    import sys
    sys.path.insert(0,'/opt/revpn-channel')
    from channel_agent import migrate_config
    settings=migrate_config(json.loads(path.read_text()))
    settings.pop('api_id',None);settings.pop('api_hash',None)
    path.write_text(json.dumps(settings,ensure_ascii=False,indent=2)+'\n')
    os.chown(path,who.pw_uid,who.pw_gid);os.chmod(path,0o600)
# Preserve the old session on disk but never use it. Pending Telethon sends may
# already have arrived; do not blindly replay them through a different API.
import sqlite3
if (root/'posts.sqlite3').exists():
    db=sqlite3.connect(root/'posts.sqlite3')
    db.execute('CREATE TABLE IF NOT EXISTS agent_meta(key TEXT PRIMARY KEY,value TEXT)')
    if not db.execute("SELECT 1 FROM agent_meta WHERE key='bot_api'").fetchone():
        db.execute("UPDATE posts SET status='uncertain' WHERE status='pending'")
        db.execute("INSERT INTO agent_meta VALUES('bot_api','1')")
    db.commit();db.close()
TOKEN
cat > /usr/local/bin/revpn-channel <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -eq 0 ]]; then
  exec runuser -u revpnchannel -- /usr/bin/python3 /opt/revpn-channel/channel_agent.py "$@"
fi
exec /usr/bin/python3 /opt/revpn-channel/channel_agent.py "$@"
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
ExecStart=/usr/bin/python3 /opt/revpn-channel/channel_agent.py run
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
if [[ "$was_active" == true ]]; then systemctl start revpn-channel; fi
printf '\nГотово. Токен взят из настроек магазина.\nНастрой канал: sudo revpn-channel configure\nПосмотреть пост: sudo revpn-channel preview\nВключить публикации: sudo systemctl enable --now revpn-channel\n'
