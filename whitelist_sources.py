#!/usr/bin/env python3
"""Refresh public mobile-whitelist reference lists without importing third-party VPN keys."""
import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path

DATA=Path('/var/lib/revpn-shop/whitelist-sources')
SOURCES={
    'sni': 'https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-SNI-RU-all.txt',
    'cidr': 'https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/WHITE-CIDR-RU-checked.txt',
    'domains': 'https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/refs/heads/main/whitelist.txt',
}
MAX_BYTES=2_000_000


def download(url):
    req=urllib.request.Request(url,headers={'User-Agent':'ReVPN-whitelist-reference/1'})
    with urllib.request.urlopen(req,timeout=15) as resp:
        data=resp.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:
        raise RuntimeError('source too large')
    text=data.decode('utf-8','replace')
    if len([x for x in text.splitlines() if x.strip() and not x.lstrip().startswith('#')])<5:
        raise RuntimeError('source looks empty')
    return text


def refresh():
    DATA.mkdir(parents=True,exist_ok=True)
    meta={'updated':int(time.time()),'sources':{}}
    for name,url in SOURCES.items():
        text=download(url)
        tmp=DATA/(name+'.txt.tmp')
        tmp.write_text(text)
        tmp.replace(DATA/(name+'.txt'))
        useful=[x.strip() for x in text.splitlines() if x.strip() and not x.lstrip().startswith('#')]
        meta['sources'][name]={
            'url':url,
            'lines':len(useful),
            'sha256':hashlib.sha256(text.encode()).hexdigest(),
        }
        print(name+':',len(useful),'entries')
    (DATA/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    print('saved:',DATA)


def status():
    p=DATA/'metadata.json'
    if not p.exists():
        print('not refreshed yet')
        return
    meta=json.loads(p.read_text())
    print('updated:',time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(meta['updated'])))
    for name,row in meta.get('sources',{}).items():
        print(name,'lines='+str(row.get('lines',0)),'sha256='+str(row.get('sha256',''))[:12])


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['refresh','status'],nargs='?',default='status')
    a=p.parse_args()
    refresh() if a.action=='refresh' else status()
