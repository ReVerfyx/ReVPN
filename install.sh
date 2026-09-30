#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Запусти: sudo bash install.sh'; exit 1; fi
src_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null || { echo 'Установи python3: apt install python3'; exit 1; }
command -v systemctl >/dev/null || { echo 'Нужна Ubuntu с systemd.'; exit 1; }
mode="${1:-install}"
if [[ "$mode" != "install" && "$mode" != "--update" ]]; then
  echo 'Использование: sudo bash install.sh [--update]'; exit 1
fi
if [[ "$mode" == "--update" && ! -f /etc/revpn-shop/config.json ]]; then
  echo 'Нет сохранённых настроек. Сначала запусти sudo bash install.sh'; exit 1
fi
# Check the new code and existing configuration before stopping the running bot.
python3 - "$src_dir" <<'PYCHECK'
import sys
from pathlib import Path
root=Path(sys.argv[1])
for name in ('bot.py','core.py','providers.py','delivery.py','subscriptions.py','mtproto_service.py','setup.py'):
    compile((root/name).read_text(),str(root/name),'exec')
sys.path.insert(0,str(root))
if Path('/etc/revpn-shop/config.json').is_file():
    from bot import load_config
    load_config('/etc/revpn-shop/config.json')
    print('Обновление: используем сохранённые настройки и базу заказов.')
PYCHECK
if systemctl is-active --quiet revpn-shop; then systemctl stop revpn-shop; fi
if ! id revpnshop >/dev/null 2>&1; then useradd --system --home /var/lib/revpn-shop --shell /usr/sbin/nologin revpnshop; fi
install -d -m 755 /opt/revpn-shop
for file in bot.py core.py providers.py delivery.py subscriptions.py mtproto_service.py setup.py config.example.json; do
  if [[ "$src_dir/$file" != "/opt/revpn-shop/$file" ]]; then install -m 644 "$src_dir/$file" "/opt/revpn-shop/$file"; fi
done
install -d -o revpnshop -g revpnshop -m 700 /var/lib/revpn-shop
install -d -m 755 /opt/revpn-shop/vendor
install -m 644 "$src_dir/vendor/mtprotoproxy.py" /opt/revpn-shop/vendor/mtprotoproxy.py
python3 /opt/revpn-shop/setup.py
chown root:revpnshop /etc/revpn-shop /etc/revpn-shop/config.json
chmod 750 /etc/revpn-shop
chmod 640 /etc/revpn-shop/config.json
cat > /usr/local/bin/vpnshop <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
if [[ $EUID -eq 0 ]]; then
  exec runuser -u revpnshop -- python3 /opt/revpn-shop/bot.py "$@"
fi
exec python3 /opt/revpn-shop/bot.py "$@"
WRAPPER
chmod 755 /usr/local/bin/vpnshop
cat > /etc/systemd/system/revpn-shop.service <<'UNIT'
[Unit]
Description=ReVPN Shop Telegram bot (LZT payments)
Wants=network-online.target
After=network-online.target x-ui.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=revpnshop
Group=revpnshop
WorkingDirectory=/opt/revpn-shop
ExecStart=/usr/bin/python3 /opt/revpn-shop/bot.py run
Restart=on-failure
RestartSec=15
TimeoutStopSec=45
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/revpn-shop
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/revpn-subscriptions.service <<'UNIT'
[Unit]
Description=ReVPN Happ subscription endpoint
After=network-online.target
[Service]
User=revpnshop
Group=revpnshop
WorkingDirectory=/opt/revpn-shop
ExecStart=/usr/bin/python3 /opt/revpn-shop/subscriptions.py --config /etc/revpn-shop/config.json --data /var/lib/revpn-shop
Restart=on-failure
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/revpn-shop
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/revpn-mtproto-paid.service <<'UNIT'
[Unit]
Description=ReVPN paid MTProto supervisor
After=network-online.target
[Service]
User=revpnshop
Group=revpnshop
WorkingDirectory=/opt/revpn-shop
ExecStart=/usr/bin/python3 /opt/revpn-shop/mtproto_service.py paid --config /etc/revpn-shop/config.json --data /var/lib/revpn-shop
Restart=on-failure
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/revpn-shop
[Install]
WantedBy=multi-user.target
UNIT
cat > /etc/systemd/system/revpn-mtproto-free.service <<'UNIT'
[Unit]
Description=ReVPN free sponsored MTProto supervisor
After=network-online.target
[Service]
User=revpnshop
Group=revpnshop
WorkingDirectory=/opt/revpn-shop
ExecStart=/usr/bin/python3 /opt/revpn-shop/mtproto_service.py free --config /etc/revpn-shop/config.json --data /var/lib/revpn-shop
Restart=on-failure
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/revpn-shop
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable revpn-shop revpn-subscriptions
systemctl restart revpn-shop revpn-subscriptions
if python3 - <<'PY2'
import json
c=json.load(open('/etc/revpn-shop/config.json'))
raise SystemExit(0 if c.get('mtproto',{}).get('paid',{}).get('enabled') else 1)
PY2
then systemctl enable revpn-mtproto-paid; systemctl restart revpn-mtproto-paid; fi
if python3 - <<'PY3'
import json
c=json.load(open('/etc/revpn-shop/config.json'))
raise SystemExit(0 if c.get('mtproto',{}).get('free',{}).get('enabled') else 1)
PY3
then systemctl enable revpn-mtproto-free; systemctl restart revpn-mtproto-free; fi
# Refresh an already installed optional channel agent without resetting its session.
if [[ -f /opt/revpn-channel/channel_agent.py ]]; then
  channel_was_active=false
  if systemctl is-active --quiet revpn-channel; then
    channel_was_active=true
    systemctl stop revpn-channel
  fi
  install -m 644 "$src_dir/channel_agent.py" "$src_dir/channel_news.py" /opt/revpn-channel/
  if [[ "$channel_was_active" == true ]]; then systemctl start revpn-channel; fi
fi
printf '\nУстановлено. Журнал: journalctl -u revpn-shop -n 50 --no-pager\n'
printf 'Настройки: /etc/revpn-shop/config.json\n'
