#!/usr/bin/env python3
"""Prepare and optionally activate a low-latency VLESS+REALITY mobile profile.

prepare: create a separate test inbound and a temporary test client without
changing the production regular node.
status: show the prepared test inbound.
activate: point the regular ReVPN node at the prepared inbound and migrate
active regular allocations. The old inbound is intentionally left running as
fallback.
"""
import argparse
import copy
import json
import os
import secrets
import socket
import subprocess
import time
import uuid
from pathlib import Path

from core import Store
from delivery import Delivery
from providers import Panel, obj

CONFIG=Path('/etc/revpn-shop/config.json')
DATA=Path('/var/lib/revpn-shop')
DB=DATA/'shop.sqlite3'
STATE=DATA/'mobile-reality.json'
REMARK='ReVPN-Mobile-Reality'
DEFAULT_PORT=8443
DEFAULT_SNI='ya.ru'


def load_cfg():
    return json.loads(CONFIG.read_text())


def regular_panel(cfg):
    return copy.deepcopy(cfg.get('nodes',{}).get('regular',{}).get('panel') or cfg['panel'])


def free_local(port):
    try:
        with socket.socket() as s:
            s.bind(('0.0.0.0',port))
        return True
    except OSError:
        return False


def reality_stream(private_key,public_key,sni,short_id):
    # Keep the legacy "dest" field used by older 3x-ui/Xray while also storing
    # the client-side public fields 3x-ui exposes in current versions.
    return {
        'network':'tcp',
        'security':'reality',
        'tcpSettings':{'acceptProxyProtocol':False,'header':{'type':'none'}},
        'realitySettings':{
            'show':False,
            'xver':0,
            'dest':sni+':443',
            'serverNames':[sni],
            'privateKey':private_key,
            'shortIds':[short_id],
            'settings':{
                'publicKey':public_key,
                'fingerprint':'chrome',
                'serverName':sni,
                'spiderX':'/',
            },
        },
    }


def allow_firewall(port):
    if subprocess.run(['sh','-lc','command -v ufw >/dev/null 2>&1'],check=False).returncode==0:
        subprocess.run(['ufw','allow',str(port)+'/tcp'],check=False,stdout=subprocess.DEVNULL)
    if subprocess.run(['sh','-lc','command -v firewall-cmd >/dev/null 2>&1'],check=False).returncode==0:
        subprocess.run(['firewall-cmd','--permanent','--add-port='+str(port)+'/tcp'],check=False,stdout=subprocess.DEVNULL)
        subprocess.run(['firewall-cmd','--reload'],check=False,stdout=subprocess.DEVNULL)


def keypair(api):
    pair=api.request('panel/api/server/getNewX25519Cert')
    if not isinstance(pair,dict) or not pair.get('privateKey') or not pair.get('publicKey'):
        raise RuntimeError('3X-UI did not return an X25519 keypair')
    return pair['privateKey'],pair['publicKey']


def list_inbounds(api):
    return api.request('panel/api/inbounds/list') or []


def existing_mobile(rows):
    return next((r for r in rows if r.get('remark')==REMARK),None)


def create_inbound(api,base_panel,port,sni):
    rows=list_inbounds(api)
    prior=existing_mobile(rows)
    if prior:
        stream=obj(prior.get('streamSettings',{}))
        reality=obj(stream.get('realitySettings',{}))
        pub=obj(reality.get('settings',{})).get('publicKey')
        if not pub:
            raise RuntimeError('Existing mobile Reality inbound has no public key in panel data')
        return prior,pub

    if any(int(r.get('port',0) or 0)==port for r in rows) or not free_local(port):
        raise RuntimeError('TCP port %d is already occupied' % port)

    private_key,public_key=keypair(api)
    short_id=secrets.token_hex(8)
    stream=reality_stream(private_key,public_key,sni,short_id)
    api.request('panel/api/inbounds/add','POST',data={
        'remark':REMARK,
        'enable':'true',
        'listen':'',
        'port':port,
        'protocol':'vless',
        'total':0,
        'up':0,
        'down':0,
        'expiryTime':0,
        'settings':json.dumps({'clients':[],'decryption':'none','encryption':'none','fallbacks':[]}),
        'streamSettings':json.dumps(stream),
        'sniffing':json.dumps({'enabled':False,'destOverride':['http','tls','quic']}),
    },form=True)
    rows=list_inbounds(api)
    inbound=existing_mobile(rows)
    if not inbound:
        raise RuntimeError('3X-UI did not confirm the new Reality inbound')
    return inbound,public_key


def test_client(panel_cfg,inbound_id,public_key,sni,port):
    p=copy.deepcopy(panel_cfg)
    p.update(inbound_id=int(inbound_id),public_port=int(port),sni=sni,public_key=public_key)
    panel=Panel(p)
    test_uuid=str(uuid.uuid4())
    now=int(time.time()*1000)
    order={
        'id':'mobile-test-'+uuid.uuid4().hex[:10],
        'uuid':test_uuid,
        'email':'revpn-mobile-test-'+uuid.uuid4().hex[:8],
        'sub_id':secrets.token_hex(8),
        'gb':0,
        'quota_bytes':0,
        'user_id':0,
        'expiry_ms':now+2*60*60*1000,
    }
    link=panel.ensure(order)
    return order,link


def prepare(args):
    cfg=load_cfg()
    base=regular_panel(cfg)
    api=Panel(base)
    current=api.inbound()
    stream=obj(current.get('streamSettings',{}))
    print('current:',stream.get('network','tcp'),'+',stream.get('security','none'),'port',base.get('public_port') or current.get('port'))

    inbound,pub=create_inbound(api,base,args.port,args.sni)
    allow_firewall(int(inbound['port']))
    order,link=test_client(base,inbound['id'],pub,args.sni,int(inbound['port']))
    state={
        'created':int(time.time()),
        'inbound_id':int(inbound['id']),
        'port':int(inbound['port']),
        'sni':args.sni,
        'public_key':pub,
        'test_uuid':order['uuid'],
        'test_email':order['email'],
        'test_expiry_ms':order['expiry_ms'],
        'link':link,
    }
    tmp=STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    os.chmod(tmp,0o600)
    tmp.replace(STATE)
    print('prepared inbound:',state['inbound_id'],'port',state['port'],'SNI',state['sni'])
    print('old regular inbound remains unchanged')
    print()
    print('TEST LINK (valid about 2 hours):')
    print(link)
    print()
    print('Import this link into Happ and compare mobile ping with the old profile.')
    print('If it is clearly better, run: sudo revpn-mobile-reality activate')


def status(_args):
    if not STATE.exists():
        print('not prepared')
        return
    st=json.loads(STATE.read_text())
    left=max(0,(int(st.get('test_expiry_ms',0))-int(time.time()*1000))//1000)
    print('inbound_id:',st.get('inbound_id'))
    print('port:',st.get('port'))
    print('sni:',st.get('sni'))
    print('test_seconds_left:',left)
    print('production_switched:',load_cfg().get('nodes',{}).get('regular',{}).get('panel',{}).get('inbound_id')==st.get('inbound_id'))


def activate(_args):
    if not STATE.exists():
        raise RuntimeError('Run prepare first')
    st=json.loads(STATE.read_text())
    cfg=load_cfg()
    old=regular_panel(cfg)
    new=copy.deepcopy(old)
    new.update(
        inbound_id=int(st['inbound_id']),
        public_port=int(st['port']),
        sni=st['sni'],
        public_key=st['public_key'],
    )
    Panel(new).inbound()

    backup=CONFIG.with_name('config.json.before-mobile-reality-'+time.strftime('%Y%m%d-%H%M%S'))
    backup.write_bytes(CONFIG.read_bytes())

    cfg.setdefault('nodes',{}).setdefault('regular',{}).update(enabled=True,panel=new)
    cfg['panel']=copy.deepcopy(new)
    tmp=CONFIG.with_suffix('.tmp')
    tmp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
    os.chmod(tmp,0o640)
    tmp.replace(CONFIG)

    store=Store(DB)
    delivery=Delivery(cfg,store,DATA)
    migrated=0
    failed=[]
    now=int(time.time()*1000)
    rows=store.db.execute("SELECT * FROM orders WHERE status='active' AND product!='mtproto' AND expiry_ms>?",(now,)).fetchall()
    for row in rows:
        order=dict(row)
        try:
            targets=json.loads(order.get('targets') or '[]') or ['regular']
        except Exception:
            targets=['regular']
        if 'regular' not in targets:
            continue
        try:
            delivery.sync_expiry(order)
            migrated+=1
        except Exception as exc:
            failed.append((order['id'],type(exc).__name__))
    store.db.close()

    subprocess.run(['systemctl','restart','revpn-shop','revpn-subscriptions'],check=False)
    print('production regular node switched to Reality inbound',st['inbound_id'],'port',st['port'])
    print('active regular subscriptions migrated:',migrated)
    if failed:
        print('migration warnings:',','.join(i+':'+e for i,e in failed))
        print('Their previous allocations remain usable on the old inbound.')
    print('old inbound was NOT deleted; config backup:',backup)


def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('prepare')
    a.add_argument('--port',type=int,default=DEFAULT_PORT)
    a.add_argument('--sni',default=DEFAULT_SNI)
    sub.add_parser('status')
    sub.add_parser('activate')
    args=p.parse_args()
    if os.geteuid()!=0:
        raise SystemExit('Run with sudo/root')
    {'prepare':prepare,'status':status,'activate':activate}[args.cmd](args)


if __name__=='__main__':
    main()
