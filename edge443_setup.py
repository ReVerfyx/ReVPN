#!/usr/bin/env python3
"""Move nginx HTTPS TCP listeners behind ReVPN edge443, safely and idempotently."""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time


CANDIDATES = (
    Path("/etc/nginx/nginx.conf"),
    Path("/etc/nginx/sites-enabled"),
    Path("/etc/nginx/conf.d"),
)


def nginx_files():
    seen=set()
    for base in CANDIDATES:
        if base.is_file():
            items=[base]
        elif base.is_dir():
            items=[p for p in base.rglob("*") if p.is_file() or p.is_symlink()]
        else:
            continue
        for p in items:
            try:
                real=p.resolve()
            except OSError:
                continue
            if real in seen or not real.is_file():
                continue
            seen.add(real)
            yield real


LISTEN_RE = re.compile(
    r"^(?P<indent>\s*)listen\s+(?P<addr>443|(?:\[[^\]]+\]|[^\s:]+):443)(?P<rest>\s+[^;]*)?;\s*$"
)
BACKEND_RE = re.compile(
    r"^(?P<indent>\s*)listen\s+(?P<addr>127\.0\.0\.1|\[::1\]):(?P<port>\d+)(?P<rest>\s+[^;]*)?;\s*$"
)


def patch_text(text, backend_port):
    changed=False
    out=[]
    for line in text.splitlines(True):
        raw=line.rstrip("\r\n")
        m=LISTEN_RE.match(raw)
        if not m or "quic" in (m.group("rest") or "").lower():
            out.append(line)
            continue
        rest=m.group("rest") or ""
        addr=m.group("addr")
        if addr.startswith("["):
            newaddr=f"[::1]:{backend_port}"
        else:
            newaddr=f"127.0.0.1:{backend_port}"
        ending="\r\n" if line.endswith("\r\n") else "\n"
        out.append(f"{m.group('indent')}listen {newaddr}{rest};{ending}")
        changed=True
    return "".join(out),changed


def restore_text(text, backend_port):
    changed=False
    out=[]
    for line in text.splitlines(True):
        raw=line.rstrip("\r\n")
        m=BACKEND_RE.match(raw)
        if not m or int(m.group("port"))!=int(backend_port):
            out.append(line)
            continue
        rest=m.group("rest") or ""
        if "ssl" not in rest.lower():
            out.append(line)
            continue
        newaddr="443" if m.group("addr")=="127.0.0.1" else "[::]:443"
        ending="\r\n" if line.endswith("\r\n") else "\n"
        out.append(f"{m.group('indent')}listen {newaddr}{rest};{ending}")
        changed=True
    return "".join(out),changed


def restore_nginx(backend_port):
    subprocess.run(["systemctl","stop","revpn-edge443.service"],check=False)
    touched=[]
    backups={}
    backup_root=Path("/etc/revpn-shop/nginx-edge443-backups")
    backup_root.mkdir(parents=True,exist_ok=True)
    for path in nginx_files():
        try:
            old=path.read_text()
        except (OSError,UnicodeDecodeError):
            continue
        new,changed=restore_text(old,backend_port)
        if not changed:
            continue
        stamp=str(int(time.time()))
        backup=backup_root/(path.name+"."+stamp+".restore.bak")
        shutil.copy2(path,backup)
        backups[path]=backup
        path.write_text(new)
        touched.append(path)
    test=subprocess.run(["nginx","-t"],text=True,capture_output=True)
    if test.returncode:
        for path,backup in backups.items():
            shutil.copy2(backup,path)
        sys.stderr.write(test.stdout+test.stderr)
        raise SystemExit("nginx restore failed; restored backups")
    subprocess.run(["systemctl","restart","nginx"],check=True)
    if touched:
        print("Website restored directly to nginx TCP/443.")
        for p in touched:
            print(" -",p)
    else:
        print("Website already uses nginx TCP/443 directly.")


def can_connect(port):
    try:
        with socket.create_connection(("127.0.0.1",port),2):
            return True
    except OSError:
        return False


def can_bind_public(port):
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0",port))
        return True
    except OSError:
        return False


def main():
    if os.geteuid()!=0:
        raise SystemExit("edge443 setup requires root")
    cfg=json.loads(Path("/etc/revpn-shop/config.json").read_text())
    edge=cfg.get("edge443",{})
    if not edge.get("enabled"):
        if not shutil.which("nginx"):
            raise SystemExit("nginx not found; cannot restore HTTPS on port 443")
        restore_nginx(int(edge.get("web_backend_port",4443)))
        return
    if not shutil.which("nginx"):
        raise SystemExit("nginx not found; cannot preserve HTTPS on port 443")

    backend=int(edge.get("web_backend_port",4443))
    backup_root=Path("/etc/revpn-shop/nginx-edge443-backups")
    backup_root.mkdir(parents=True,exist_ok=True)
    touched=[]
    backups={}

    for path in nginx_files():
        try:
            old=path.read_text()
        except (OSError,UnicodeDecodeError):
            continue
        new,changed=patch_text(old,backend)
        if not changed:
            continue
        stamp=str(int(time.time()))
        backup=backup_root/(path.name+"."+stamp+".bak")
        shutil.copy2(path,backup)
        backups[path]=backup
        path.write_text(new)
        touched.append(path)

    test=subprocess.run(["nginx","-t"],text=True,capture_output=True)
    if test.returncode:
        for path,backup in backups.items():
            shutil.copy2(backup,path)
        sys.stderr.write(test.stdout+test.stderr)
        raise SystemExit("nginx config failed after edge443 migration; restored backups")

    subprocess.run(["systemctl","restart","nginx"],check=True)
    edge_running=subprocess.run(
        ["systemctl","is-active","--quiet","revpn-edge443.service"]
    ).returncode==0
    public_port=int(edge.get("listen_port",443))
    if not edge_running and not can_bind_public(public_port):
        for path,backup in backups.items():
            shutil.copy2(backup,path)
        subprocess.run(["nginx","-t"],check=True)
        subprocess.run(["systemctl","restart","nginx"],check=True)
        raise SystemExit(f"TCP {public_port} is still occupied after nginx migration; restored backups")
    if not can_connect(backend):
        for path,backup in backups.items():
            shutil.copy2(backup,path)
        subprocess.run(["nginx","-t"],check=True)
        subprocess.run(["systemctl","restart","nginx"],check=True)
        raise SystemExit(f"nginx did not come up on local TLS backend {backend}; restored backups")

    print("edge443 nginx backend ready on 127.0.0.1:%d" % backend)
    if touched:
        print("Patched nginx files:")
        for p in touched:
            print(" -",p)
    else:
        print("No new nginx listener changes were needed.")


if __name__=="__main__":
    main()
