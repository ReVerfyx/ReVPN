# ReVPN server

Target OS: Ubuntu 24.04.

The installer sets up:

- Xray-core
- VLESS + XTLS Vision + REALITY
- HAProxy on TCP/443
- four selectable REALITY/SNI profiles: MAX, VK, VK Video and Yandex Disk
- a generated client file at `/root/revpn-client.json`

## Install

```bash
git clone https://github.com/ReVerfyx/ReVPN.git
cd ReVPN
sudo bash server/install.sh
```

Optional metadata:

```bash
sudo SERVER_NAME="NL #1" COUNTRY="Нидерланды" CITY="Амстердам" PUBLIC_HOST="1.2.3.4" bash server/install.sh
```

After installation copy the contents of `/root/revpn-client.json` and paste it in ReVPN -> Settings -> Import configuration.

## Important limitation

REALITY changes the TLS appearance and SNI, but it does not change the destination IP. If a network uses a strict destination-IP allowlist, an arbitrary VPS IP can still be blocked.
