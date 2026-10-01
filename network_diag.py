#!/usr/bin/env python3
"""Sanitized ReVPN network diagnostic: no secrets or private keys are printed."""
import json
import platform
import socket
import subprocess
import time
from pathlib import Path

from providers import Panel, obj


CONFIG=Path('/etc/revpn-shop/config.json')


def sh(*args):
    try:
        return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT,timeout=5).strip()
    except Exception as exc:
        return 'ERR:'+type(exc).__name__


def connect_ms(host,port,attempts=3):
    out=[]
    for _ in range(attempts):
        started=time.perf_counter()
        try:
            with socket.create_connection((host,port),2):
                out.append(round((time.perf_counter()-started)*1000))
        except OSError:
            out.append('ERR')
    return out


def main():
    cfg=json.loads(CONFIG.read_text())
    regular=cfg.get('nodes',{}).get('regular',{}).get('panel') or cfg.get('panel',{})
    print('ReVPN network diagnostic')
    print('kernel:',platform.release())
    print('qdisc:',sh('sysctl','-n','net.core.default_qdisc'))
    print('tcp_cc:',sh('sysctl','-n','net.ipv4.tcp_congestion_control'))
    print('tcp_available_cc:',sh('sysctl','-n','net.ipv4.tcp_available_congestion_control'))
    print('mtu_probing:',sh('sysctl','-n','net.ipv4.tcp_mtu_probing'))
    print()
    try:
        inbound=Panel(regular).inbound()
        stream=obj(inbound.get('streamSettings',{}))
        reality=obj(stream.get('realitySettings',{}))
        tls=obj(stream.get('tlsSettings',{}))
        names=reality.get('serverNames') or []
        print('regular_inbound_id:',regular.get('inbound_id'))
        print('regular_public_host:',regular.get('public_host'))
        print('regular_public_port:',regular.get('public_port') or inbound.get('port'))
        print('regular_network:',stream.get('network','tcp'))
        print('regular_security:',stream.get('security','none'))
        print('regular_sni:',regular.get('sni') or (names[0] if names else tls.get('serverName','')))
        print('regular_enabled:',bool(inbound.get('enable')))
        print('regular_clients:',len(obj(inbound.get('settings',{})).get('clients',[])))
        network=stream.get('network','tcp')
        security=stream.get('security','none')
        if network in ('tcp','raw') and security=='none':
            print('WARNING: regular VPN is raw VLESS without TLS/REALITY; mobile DPI may identify/throttle it.')
        elif network in ('tcp','raw'):
            print('note: RAW is lowest-overhead, but XHTTP can be more stable on filtered mobile networks.')
        elif network=='xhttp':
            xh=obj(stream.get('xhttpSettings',{}))
            print('xhttp_mode:',xh.get('mode','auto'))
            print('xhttp_path:',xh.get('path','/'))
    except Exception as exc:
        print('regular_inbound: ERROR',type(exc).__name__,str(exc))

    print()
    for host in ('1.1.1.1','8.8.8.8','vk.com','ya.ru'):
        print('server_to_'+host+':',connect_ms(host,443))


if __name__=='__main__':
    main()
