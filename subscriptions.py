"""Private-token subscription endpoint; run behind an HTTPS reverse proxy."""
import argparse
import base64
from datetime import datetime, timezone
import html
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit


def profile_title(name,expiry):
    date=datetime.fromtimestamp(expiry/1000,timezone.utc).strftime('%d.%m.%y')
    suffix='🥶ReVPN · '+date
    name=''.join(c for c in name if c.isprintable()).strip() or 'Друг'
    return name[:max(1,25-len(suffix))]+suffix


def subscription(db,token,now=None):
    now=time.time() if now is None else now
    db.row_factory=sqlite3.Row
    order=db.execute("SELECT * FROM orders WHERE sub_id=? AND status='active' AND product!='mtproto'",(token,)).fetchone()
    if order is None: return None
    rows=db.execute('SELECT * FROM allocations WHERE order_id=? ORDER BY node_id',(order['id'],)).fetchall()
    # Never expose a partially delivered bundle.
    if len(rows)!=len(json.loads(order['targets']) or ['regular']): return None
    title=profile_title(order['display_name'],order['expiry_ms'])
    links='\n'.join(r['link'] for r in rows) if order['expiry_ms']>now*1000 else ''
    headers={'profile-title':'base64:'+base64.b64encode(title.encode()).decode(),
             'profile-update-interval':'1',
             'subscription-userinfo':f"upload={sum(r['upload'] for r in rows)}; download={sum(r['download'] for r in rows)}; total={order['gb']*1024**3}; expire={order['expiry_ms']//1000}"}
    return base64.b64encode(links.encode()),headers,order


def handler(db_path,public_base,support):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass # URLs are credentials; never log subscription tokens.
        def do_GET(self):
            path=urlsplit(self.path).path
            match=re.fullmatch(r'/(sub|connect)/([a-f0-9]{32})',path)
            if not match: return self.reply(404,b'Not found')
            try:
                with sqlite3.connect('file:'+str(db_path)+'?mode=ro',uri=True,timeout=5) as db:
                    result=subscription(db,match[2])
            except sqlite3.Error: return self.reply(503,b'Try later')
            if not result: return self.reply(404,b'Not found')
            body,headers,order=result
            if match[1]=='sub':
                headers['support-url']='https://t.me/'+support.lstrip('@')
                return self.reply(200,body,headers)
            url=public_base.rstrip('/')+'/sub/'+match[2]
            title=html.escape(profile_title(order['display_name'],order['expiry_ms']))
            body=f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ReVPN</title><style>body{{background:#081526;color:#eefaff;font:18px system-ui;max-width:520px;margin:12vh auto;padding:24px}}a{{display:block;background:#8ce8ff;color:#081526;padding:18px;border-radius:16px;text-align:center;text-decoration:none;font-weight:bold}}input{{width:100%;box-sizing:border-box;padding:14px;margin-top:16px;background:#142a41;color:white;border:0;border-radius:12px}}p{{line-height:1.6}}</style><h1>Очень холодно 🥶</h1><p>{title}</p><a href="{html.escape('happ://add/'+url,quote=True)}">Добавить подписку в Happ</a><p>Если Happ не открылся, скопируй ссылку ниже и добавь её через «+» → «Из буфера обмена».</p><input readonly aria-label="Ссылка подписки" value="{html.escape(url,quote=True)}"><p>Подписка добавляет все оплаченные профили.</p></html>'''.encode()
            self.reply(200,body,{'Content-Type':'text/html; charset=utf-8'})
        def reply(self,status,body,headers=None):
            self.send_response(status)
            fields={'Content-Type':'text/plain; charset=utf-8','Content-Length':str(len(body)),'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"}
            fields.update(headers or {})
            for k,v in fields.items(): self.send_header(k,v)
            self.end_headers(); self.wfile.write(body)
    return Handler

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--config',default='/etc/revpn-shop/config.json'); p.add_argument('--data',default='/var/lib/revpn-shop'); a=p.parse_args()
    cfg=json.loads(Path(a.config).read_text()); sub=cfg['subscription']
    server=HTTPServer(('127.0.0.1',sub.get('local_port',8090)),handler(Path(a.data)/'shop.sqlite3',sub['public_base'],cfg['telegram']['support']))
    server.serve_forever()
