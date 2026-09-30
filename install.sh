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
for name in ('bot.py','core.py','providers.py','delivery.py','subscriptions.py','events.py','mtproto_service.py','edge443.py','edge443_setup.py','setup.py'):
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
for file in bot.py core.py providers.py delivery.py subscriptions.py events.py mtproto_service.py edge443.py edge443_setup.py setup.py config.example.json; do
  if [[ "$src_dir/$file" != "/opt/revpn-shop/$file" ]]; then install -m 644 "$src_dir/$file" "/opt/revpn-shop/$file"; fi
done
install -d -o revpnshop -g revpnshop -m 700 /var/lib/revpn-shop
install -d -m 755 /opt/revpn-shop/vendor
install -m 644 "$src_dir/vendor/mtprotoproxy.py" /opt/revpn-shop/vendor/mtprotoproxy.py
python3 /opt/revpn-shop/setup.py
edge443_ready=0
if python3 - <<'PYEDGE'
import json
c=json.load(open('/etc/revpn-shop/config.json'))
raise SystemExit(0 if c.get('edge443',{}).get('enabled') else 1)
PYEDGE
then
  if python3 /opt/revpn-shop/edge443_setup.py; then
    edge443_ready=1
  else
    echo
    echo 'ВНИМАНИЕ: TCP 443 занят другим сервисом. Обновление ReVPN продолжится без edge443.'
    echo 'Сайт, бот и Mini App будут обновлены; MTProto временно останется на своих старых портах.'
    if command -v ss >/dev/null; then
      echo 'Кто сейчас держит 443:'
      ss -ltnp 'sport = :443' || true
    fi
    python3 - <<'PYFALLBACK'
import json, os
p='/etc/revpn-shop/config.json'
c=json.load(open(p))
edge=c.setdefault('edge443',{})
edge['enabled']=False
for kind in ('paid','free'):
    sec=c.get('mtproto',{}).get(kind,{})
    if sec.get('port'):
        sec['public_port']=sec['port']
tmp=p+'.tmp'
with open(tmp,'w') as f:
    json.dump(c,f,ensure_ascii=False,indent=2)
    f.write('\n')
os.chmod(tmp,0o640)
os.replace(tmp,p)
PYFALLBACK
  fi
fi
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
cat > /etc/systemd/system/revpn-edge443.service <<'UNIT'
[Unit]
Description=ReVPN TCP 443 SNI edge for HTTPS and MTProto
Wants=network-online.target
After=network-online.target nginx.service revpn-mtproto-paid.service revpn-mtproto-free.service
[Service]
User=revpnshop
Group=revpnshop
WorkingDirectory=/opt/revpn-shop
ExecStart=/usr/bin/python3 /opt/revpn-shop/edge443.py --config /etc/revpn-shop/config.json
Restart=on-failure
RestartSec=2
UMask=0077
NoNewPrivileges=true
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
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
if [[ "$edge443_ready" == "1" ]]; then
  systemctl enable revpn-edge443
  systemctl restart revpn-edge443
else
  systemctl disable --now revpn-edge443 2>/dev/null || true
fi
# Refresh the optional publisher, including token and old Telethon service migration.
if [[ -f /opt/revpn-channel/channel_agent.py ]]; then
  bash "$src_dir/install-channel.sh" --update
fi
printf '\nУстановлено. Журнал: journalctl -u revpn-shop -n 50 --no-pager\n'
printf 'Настройки: /etc/revpn-shop/config.json\n'
