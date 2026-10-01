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
    'domains': 'https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/refs/heads/main/whitelist.txt',
    'cidr': 'https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/refs/heads/main/cidrwhitelist.txt',
    'ips': 'https://raw.githubusercontent.com/hxehex/russia-mobile-internet-whitelist/refs/heads/main/ipwhitelist.txt',
}
MAX_BYTES=2_000_000


def useful_lines(text):
    return [x.strip() for x in text.splitlines() if x.strip() and not x.lstrip().startswith('#')]


def download(url):
    req=urllib.request.Request(url,headers={'User-Agent':'ReVPN-whitelist-reference/1'})
    with urllib.request.urlopen(req,timeout=20) as resp:
        data=resp.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:
        raise RuntimeError('source too large')
    text=data.decode('utf-8','replace')
    if len(useful_lines(text))<3:
        raise RuntimeError('source looks empty')
    return text


def refresh():
    DATA.mkdir(parents=True,exist_ok=True)
    previous={}
    if (DATA/'metadata.json').exists():
        try:
            previous=json.loads((DATA/'metadata.json').read_text())
        except Exception:
            previous={}
    meta={'updated':int(time.time()),'sources':{}}
    ok=0
    failures=[]
    for name,url in SOURCES.items():
        try:
            text=download(url)
            tmp=DATA/(name+'.txt.tmp')
            tmp.write_text(text)
            tmp.replace(DATA/(name+'.txt'))
            useful=useful_lines(text)
            meta['sources'][name]={
                'url':url,
                'lines':len(useful),
                'sha256':hashlib.sha256(text.encode()).hexdigest(),
                'ok':True,
            }
            ok+=1
            print(name+':',len(useful),'entries')
        except Exception as exc:
            failures.append((name,type(exc).__name__,str(exc)))
            old=(previous.get('sources') or {}).get(name,{})
            meta['sources'][name]={
                'url':url,
                'lines':int(old.get('lines',0)),
                'sha256':old.get('sha256',''),
                'ok':False,
                'error':type(exc).__name__+': '+str(exc),
            }
            print(name+': WARNING',type(exc).__name__,str(exc))
    (DATA/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
    print('saved:',DATA)
    if failures:
        print('warnings:',len(failures),'source(s) failed; successful sources were kept')
    if ok==0:
        raise RuntimeError('all whitelist sources failed')


def status():
    p=DATA/'metadata.json'
    if not p.exists():
        print('not refreshed yet')
        return
    meta=json.loads(p.read_text())
    print('updated:',time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(meta['updated'])))
    for name,row in meta.get('sources',{}).items():
        state='ok' if row.get('ok',True) else 'stale/error'
        print(name,state,'lines='+str(row.get('lines',0)),'sha256='+str(row.get('sha256',''))[:12])


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['refresh','status'],nargs='?',default='status')
    a=p.parse_args()
    refresh() if a.action=='refresh' else status()
