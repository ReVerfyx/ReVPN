"""Supervise pinned upstream MTProto with per-order secrets and time expiry."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import uuid


def paid_users(db,now):
    return {r[0]:uuid.UUID(r[1]).hex for r in db.execute("SELECT id,uuid FROM orders WHERE product='mtproto' AND status IN ('provisioning','active') AND expiry_ms>?",(int(now*1000),))}


def run(cfg,data,kind):
    section=cfg['mtproto'][kind]
    if not section.get('enabled'): return
    child=None; previous=None; running=True
    root=Path(data); state=root/('mtproto-'+kind+'-ready.json')
    config_path=root/('mtproto-'+kind+'.py')
    def stop(*_):
        nonlocal running
        running=False
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    try:
        while running:
            try:
                if kind=='free': users={'free':section['secret']}
                else:
                    with sqlite3.connect('file:'+str(root/'shop.sqlite3')+'?mode=ro',uri=True) as db: users=paid_users(db,time.time())
                # Removal restarts the process to close already established expired sessions.
                if users!=previous or child is None or child.poll() is not None:
                    state.unlink(missing_ok=True)
                    if child and child.poll() is None:
                        child.terminate()
                        try: child.wait(timeout=10)
                        except subprocess.TimeoutExpired: child.kill(); child.wait()
                    config_path.write_text('PORT = '+repr(section['port'])+'\nUSERS = '+repr(users)+'\nMODES = {"classic": False, "secure": True, "tls": False}\nAD_TAG = '+repr(section.get('ad_tag','') if kind=='free' else '')+'\n')
                    os.chmod(config_path,0o600)
                    child=subprocess.Popen([sys.executable,str(Path(__file__).parent/'vendor/mtprotoproxy.py'),str(config_path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    previous=users
                if child.poll() is None:
                    try:
                        with socket.create_connection(('127.0.0.1',section['port']),timeout=1): pass
                        temp=state.with_suffix('.tmp'); temp.write_text(json.dumps({'time':time.time(),'orders':list(users)})); temp.replace(state)
                    except OSError: state.unlink(missing_ok=True)
            except (sqlite3.Error,OSError):
                # Fail closed if the entitlement database is unavailable.
                state.unlink(missing_ok=True)
                if child and child.poll() is None: child.terminate(); child.wait(timeout=10)
                child=None
            time.sleep(2)
    finally:
        state.unlink(missing_ok=True)
        if child and child.poll() is None:
            child.terminate()
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill(); child.wait()

if __name__=='__main__':
    os.umask(0o077)
    p=argparse.ArgumentParser(); p.add_argument('kind',choices=['paid','free']); p.add_argument('--config',default='/etc/revpn-shop/config.json'); p.add_argument('--data',default='/var/lib/revpn-shop'); a=p.parse_args()
    run(json.loads(Path(a.config).read_text()),a.data,a.kind)
