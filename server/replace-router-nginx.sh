#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash server/replace-router-nginx.sh"
  exit 1
fi

CLIENT=/root/revpn-client.json
[[ -f "$CLIENT" ]] || { echo "$CLIENT not found"; exit 1; }

DEBIAN_FRONTEND=noninteractive apt-get update >/dev/null
DEBIAN_FRONTEND=noninteractive apt-get install -y nginx libnginx-mod-stream jq >/dev/null

STANDARD_SNI="$(jq -r '.servers[0].masks[] | select(.id=="standard") | .serverName' "$CLIENT")"
MAX_SNI="$(jq -r '.servers[0].masks[] | select(.id=="max") | .serverName' "$CLIENT")"
VK_SNI="$(jq -r '.servers[0].masks[] | select(.id=="vk") | .serverName' "$CLIENT")"
VKVIDEO_SNI="$(jq -r '.servers[0].masks[] | select(.id=="vkvideo") | .serverName' "$CLIENT")"
YADISK_SNI="$(jq -r '.servers[0].masks[] | select(.id=="yadisk") | .serverName' "$CLIENT")"

for v in STANDARD_SNI MAX_SNI VK_SNI VKVIDEO_SNI YADISK_SNI; do
  [[ -n "${!v}" && "${!v}" != "null" ]] || { echo "Missing $v"; exit 1; }
done

if [[ -f /etc/nginx/nginx.conf ]]; then
  cp -a /etc/nginx/nginx.conf "/etc/nginx/nginx.conf.bak.$(date +%s)"
fi

systemctl stop haproxy 2>/dev/null || true
systemctl disable haproxy 2>/dev/null || true
systemctl stop nginx 2>/dev/null || true

cat >/etc/nginx/nginx.conf <<'NGINX_EOF'
user www-data;
worker_processes auto;
pid /run/nginx.pid;
include /etc/nginx/modules-enabled/*.conf;

events {
    worker_connections 4096;
    multi_accept on;
}

http {
    access_log off;
    error_log /var/log/nginx/error.log warn;
    server {
        listen 127.0.0.1:8080;
        location /healthz { return 204; }
    }
}

stream {
    log_format revpn '$remote_addr $ssl_preread_server_name -> $upstream_addr';
    access_log /var/log/nginx/revpn-stream.log revpn;

    map $ssl_preread_server_name $revpn_backend {
        __STANDARD_SNI__ 127.0.0.1:11000;
        __MAX_SNI__      127.0.0.1:11001;
        __VK_SNI__       127.0.0.1:11002;
        __VKVIDEO_SNI__  127.0.0.1:11003;
        __YADISK_SNI__   127.0.0.1:11004;
        default          127.0.0.1:11000;
    }

    server {
        listen 0.0.0.0:443 reuseport;
        proxy_pass $revpn_backend;
        ssl_preread on;
        proxy_connect_timeout 5s;
        proxy_timeout 2m;
    }
}
NGINX_EOF

sed -i \
  -e "s|__STANDARD_SNI__|$STANDARD_SNI|g" \
  -e "s|__MAX_SNI__|$MAX_SNI|g" \
  -e "s|__VK_SNI__|$VK_SNI|g" \
  -e "s|__VKVIDEO_SNI__|$VKVIDEO_SNI|g" \
  -e "s|__YADISK_SNI__|$YADISK_SNI|g" \
  /etc/nginx/nginx.conf

nginx -t
systemctl enable nginx >/dev/null
systemctl restart nginx

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  ufw allow 443/tcp >/dev/null
fi

echo
echo "=== router status ==="
systemctl is-active xray
systemctl is-active nginx
ss -ltnp | grep -E ':443|:1100[0-4]' || true
echo
echo "HAProxy disabled; nginx stream ssl_preread now routes REALITY SNI."
echo "Running repeated stability test..."
bash "$(dirname "$0")/test-stability.sh"
