"""Product selection and idempotent, multi-node delivery."""
import json
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from core import ShopError
from providers import Panel

PRODUCTS={'regular':'Обычный VPN','whitelist':'Белые списки · 5 профилей','bundle':'Обычный + белые списки','mtproto':'MTProto для Telegram'}
OPERATORS={'mts':'МТС','megafon':'МегаФон','beeline':'Билайн','t2':'T2','yota':'Yota'}
WHITELIST=('max','yandex','disk','vk','vkvideo')

def nodes(cfg):
    return cfg.get('nodes',{'regular':{'label':'Обычный','enabled':True,'panel':cfg['panel']}})

def targets(cfg,product,operator=''):
    if product=='mtproto':
        if not cfg.get('mtproto',{}).get('paid',{}).get('enabled'): raise ShopError('Продажа MTProto пока недоступна.')
        return []
    if product not in PRODUCTS: raise ShopError('Неизвестный тариф.')
    if product!='regular':
        if operator not in OPERATORS or operator not in cfg.get('supported_operators',[]):
            raise ShopError('Пока не можем помочь с этим оператором 🥶 Счёт не создан.')
    selected=(['regular'] if product in ('regular','bundle') else [])+(list(WHITELIST) if product in ('whitelist','bundle') else [])
    catalog=nodes(cfg)
    if any(not catalog.get(n,{}).get('enabled') for n in selected):
        raise ShopError('Этот тариф ещё настраивается. Покупка пока недоступна.')
    base=cfg.get('subscription',{}).get('public_base','')
    parsed=urlsplit(base)
    if parsed.scheme!='https' or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
        raise ShopError('Ссылка подписки ещё не настроена.')
    return selected

def proxy_link(cfg,secret,kind='paid'):
    section=cfg['mtproto'][kind]
    host=cfg['mtproto'].get('public_host','')
    # Migrate this installation's legacy address; preserve other deployments.
    if host=='2.26.85.86': host='revpn.work.gd'
    return 'https://t.me/proxy?'+urlencode({'server':host,'port':section['port'],'secret':'dd'+secret})

def ready(data,kind,oid=None):
    try:
        state=json.loads((Path(data)/('mtproto-'+kind+'-ready.json')).read_text())
        return time.time()-state['time']<15 and (oid is None or oid in state['orders'])
    except (OSError,ValueError,KeyError): return False

class Delivery:
    def __init__(self,cfg,store,data,panel_factory=Panel):
        self.cfg,self.s,self.data=cfg,store,Path(data)
        self.panels={key:panel_factory(value['panel']) for key,value in nodes(cfg).items() if value.get('enabled')}

    def selected(self,o):
        return json.loads(o['targets']) or ['regular']

    def child(self,o,node):
        chosen=self.selected(o)
        index=chosen.index(node)
        total=o['gb']*1024**3
        quota=total//len(chosen)+(1 if index<total%len(chosen) else 0)
        # Stable per-node identity; retries cannot create a second paid client.
        return {**o,'uuid':str(uuid.uuid5(uuid.UUID(o['uuid']),node)),
                'email':o['email']+'-'+node,'quota_bytes':quota}

    def exists(self,o):
        if o['product']=='mtproto': return ready(self.data,'paid',o['id'])
        if self.s.db.execute('SELECT 1 FROM allocations WHERE order_id=? LIMIT 1',(o['id'],)).fetchone(): return True
        return any(self.panels[n].exists(self.child(o,n)) for n in self.selected(o))

    def ensure(self,o):
        if o['product']=='mtproto':
            if not ready(self.data,'paid',o['id']): raise ShopError('Прокси запускается. Повторим выдачу автоматически.')
            return proxy_link(self.cfg,uuid.UUID(o['uuid']).hex)
        selected=self.selected(o)
        for n in selected:
            if n not in self.panels: raise ShopError('Узел недоступен: '+n)
            self.panels[n].inbound()  # Check all endpoints before first write.
        for n in selected:
            child=self.child(o,n)
            link=self.panels[n].ensure(child)
            label=nodes(self.cfg)[n]['label']
            link=link.split('#',1)[0]+'#'+quote(label+' 🥶ReVPN')
            self.s.db.execute('INSERT INTO allocations(order_id,node_id,link,quota) VALUES(?,?,?,?) ON CONFLICT(order_id,node_id) DO UPDATE SET link=excluded.link',
                             (o['id'],n,link,child['quota_bytes']))
        return self.cfg['subscription']['public_base'].rstrip('/')+'/sub/'+o['sub_id']

    def sync_expiry(self,o):
        """Idempotently provision or update an order to its stored expiry."""
        if o['product']=='mtproto':
            raise ShopError('Ивенты не продлевают MTProto.')
        selected=self.selected(o)
        for n in selected:
            if n not in self.panels: raise ShopError('Узел недоступен: '+n)
            self.panels[n].inbound()
        for n in selected:
            child=self.child(o,n)
            panel=self.panels[n]
            link=panel.update_expiry(child,o['expiry_ms']) if panel.exists(child) else panel.ensure(child)
            label=nodes(self.cfg)[n]['label']
            link=link.split('#',1)[0]+'#'+quote(label+' 🥶ReVPN')
            self.s.db.execute('INSERT INTO allocations(order_id,node_id,link,quota) VALUES(?,?,?,?) ON CONFLICT(order_id,node_id) DO UPDATE SET link=excluded.link',
                              (o['id'],n,link,child['quota_bytes']))
        return self.cfg['subscription']['public_base'].rstrip('/')+'/sub/'+o['sub_id']

    def revoke(self,o):
        if o.get('product')=='mtproto': return
        for n in self.selected(o):
            panel=self.panels.get(n)
            if panel:
                try: panel.remove(self.child(o,n))
                except Exception: pass
        self.s.db.execute('DELETE FROM allocations WHERE order_id=?',(o['id'],))
