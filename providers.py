"""Direct HTTPS APIs; no webhook or browser needed for payment confirmation."""
import http.cookiejar
import ipaddress
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from core import ShopError, description

class APIError(ShopError):
    def __init__(self, service, status=0):
        self.service,self.status=service,status
        # Never expose request URLs (bot tokens) or raw provider responses.
        super().__init__(f'{service}: ошибка API' + (f' HTTP {status}' if status else ''))

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise APIError('redirect')

class HTTP:
    def __init__(self, service, base, token='', ca='', local_tls=False, host_header=''):
        self.service,self.base,self.token=service,base.rstrip('/'),token
        parsed=urllib.parse.urlsplit(base)
        if parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ShopError('Недопустимый URL API.')
        try: loopback=ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError: loopback=parsed.hostname=='localhost'
        if parsed.scheme!='https' and not loopback:
            raise ShopError('HTTP допускается только для локальной панели.')
        context=ssl.create_default_context(cafile=ca or None)
        if local_tls:
            if not loopback or not ca:
                raise ShopError('Для локального TLS нужен публичный сертификат панели.')
            context.check_hostname=False  # Signature/chain still checked.
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),
            urllib.request.HTTPSHandler(context=context),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.host_header=host_header
        self.csrf_token=""

    def call(self,path,method='GET',data=None,query=None,form=False,timeout=30):
        url=self.base+'/'+path.lstrip('/')
        if query: url+='?'+urllib.parse.urlencode(query)
        headers={'Accept':'application/json','User-Agent':'ReVPN-Shop/1.0'}
        if self.token: headers['Authorization']='Bearer '+self.token
        if self.host_header: headers['Host']=self.host_header
        if self.csrf_token and method.upper() not in ('GET','HEAD','OPTIONS'):
            headers['X-CSRF-Token']=self.csrf_token
        body=None
        if data is not None:
            body=(urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
            headers['Content-Type']='application/x-www-form-urlencoded' if form else 'application/json'
        try:
            request=urllib.request.Request(url,body,headers,method=method)
            with self.opener.open(request,timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            raise APIError(self.service,e.code) from None
        except (ValueError,urllib.error.URLError,TimeoutError,OSError):
            raise APIError(self.service) from None

class Lolz:
    def __init__(self,cfg,bot_name):
        self.cfg=cfg
        self.bot_name=bot_name
        self.http=HTTP('Lolz','https://api.lzt.market',cfg['token'])
        self.last_get=0
        self.last_post=0

    def call(self,method,**kwargs):
        attr='last_get' if method=='GET' else 'last_post'
        pause=(0.3 if method=='GET' else 2.2)-(time.monotonic()-getattr(self,attr))
        if pause>0: time.sleep(pause)
        setattr(self,attr,time.monotonic())
        try: result=self.http.call('invoice',method,**kwargs)
        except APIError as e:
            if e.status==429:
                self.last_get=self.last_post=time.monotonic()+60
            raise
        invoice=result.get('invoice')
        if not isinstance(invoice,dict): raise APIError('Lolz format')
        return invoice

    @staticmethod
    def metadata(o):
        return json.dumps({'order':o['id'],'amount_kopecks':o['amount'],'currency':'rub'},sort_keys=True,separators=(',',':'))

    def get_invoice(self,o):
        return self.call('GET',query={'invoice_id':o['invoice_id']} if o['invoice_id'] else {'payment_id':o['id']})

    def ensure_invoice(self,o):
        try: return self.get_invoice(o)
        except APIError as e:
            if e.status!=404: raise
        payload={'currency':'rub','amount':o['amount']/100,'payment_id':o['id'],
            'comment':'ReVPN '+o.get('product','regular')+' '+description(o['hours'],o['gb']), 'merchant_id':self.cfg['merchant_id'],
            'url_success':'https://t.me/'+self.bot_name+'?start=order_'+o['id'],
            'lifetime':self.cfg['invoice_lifetime'], 'required_telegram_id':int(o.get('user_id',0)), 'additional_data':self.metadata(o), 'is_test':self.cfg['test']}
        try: return self.call('POST',data=payload)
        except APIError:
            # A failed POST may already have created the invoice. Never change payment_id.
            try: return self.get_invoice(o)
            except APIError: raise APIError('Lolz invoice uncertain') from None

    def validate(self,i,o,paid_check=False):
        try:
            if str(i['payment_id'])!=o['id'] or int(i['merchant_id'])!=self.cfg['merchant_id']:
                raise ValueError()
            if json.loads(i['additional_data'])!=json.loads(self.metadata(o)):
                raise ValueError()
            if type(i['is_test']) is not bool or i['is_test']!=self.cfg['test']:
                raise ValueError()
            if int(i['invoice_id'])<=0 or int(i['expires_at'])<=0:
                raise ValueError()
            amount=Decimal(str(i['amount']))
            if not amount.is_finite() or amount<=0:
                raise ValueError()
            # API schema omits currency and doesn't document the integer response
            # amount's units. Bind to the authenticated creation response instead
            # of guessing rubles vs kopecks. Request currency is fixed to rub.
            if o.get('invoice_id') and int(i['invoice_id'])!=o['invoice_id']:
                raise ValueError()
            if o.get('provider_amount') is not None and amount!=Decimal(o['provider_amount']):
                raise ValueError()
            if 'currency' in i and i['currency'].lower()!='rub':
                raise ValueError()
            url=urllib.parse.urlsplit(i['url'])
            if url.scheme!='https' or url.hostname not in ('lzt.market','lolz.market') or url.username:
                raise ValueError()
            if i['status']=='paid' and int(i['paid_date'])<=0:
                raise ValueError()
        except (KeyError,ValueError,TypeError,ArithmeticError):
            raise ShopError('Платёж не прошёл проверку реквизитов. Обратись в поддержку.') from None


def obj(value):
    return json.loads(value) if isinstance(value,str) else (value or {})

class Panel:
    def __init__(self,cfg):
        self.cfg=cfg
        self.http=HTTP('3X-UI',cfg['url'],cfg.get('token',''),cfg.get('ca_file',''),cfg.get('local_tls',False),cfg.get('host_header',''))
        self.authenticated=bool(cfg.get('token'))

    def refresh_csrf(self):
        self.http.csrf_token=''
        try:
            r=self.http.call('csrf-token')
        except APIError as exc:
            if exc.status in (404,405): return  # Older panels have no CSRF endpoint.
            raise APIError('3X-UI получение CSRF',exc.status) from None
        token=r.get('obj')
        if r.get('success') is not True or not isinstance(token,str) or not token:
            raise ShopError('3X-UI: неожиданный ответ /csrf-token. Проверь URL панели.')
        self.http.csrf_token=token

    def login(self):
        if not self.cfg.get('token'):
            self.refresh_csrf()
            r=self.http.call('login','POST',data={'username':self.cfg['username'],'password':self.cfg['password']},form=True)
            if r.get('success') is not True:
                raise ShopError('3X-UI отклонила вход: проверь данные панели, 2FA и временную блокировку входа.')
            self.refresh_csrf()
        self.authenticated=True

    def request(self,path,method='GET',data=None,form=False):
        if not self.authenticated: self.login()
        try: r=self.http.call(path,method,data=data,form=form)
        except APIError as e:
            if e.status in (401,403) and not self.cfg.get('token'):
                self.authenticated=False
                self.login()
                r=self.http.call(path,method,data=data,form=form)
            else: raise
        if r.get('success') is not True: raise APIError('3X-UI operation')
        return r.get('obj')

    def inbound(self):
        r=self.request('panel/api/inbounds/get/'+str(self.cfg['inbound_id']))
        self.validate_inbound(r)
        return r

    def validate_inbound(self,r):
        if not r or r.get('protocol')!='vless' or not r.get('enable'):
            raise ShopError('Нужен включённый VLESS inbound.')
        if int(r.get('total',0))!=0 or int(r.get('expiryTime',0))!=0:
            raise ShopError('У общего inbound убери общий лимит и срок. Лимиты задаются клиентам.')
        stream=obj(r['streamSettings'])
        if stream.get('network') not in ('tcp','raw'):
            raise ShopError('Эта версия магазина поддерживает VLESS TCP/RAW.')
        settings=obj(r['settings'])
        if settings.get('decryption','none')!='none':
            raise ShopError('VLESS Encryption пока не поддерживается. Выбери inbound с decryption=none.')
        if stream.get('security','none') not in ('none','tls','reality'):
            raise ShopError('Неизвестный тип защиты.')

    def link(self,o,r):
        stream=obj(r['streamSettings'])
        security=stream.get('security','none')
        params={'encryption':'none','type':'tcp','security':security,'headerType':'none'}
        if security=='tls':
            params.update(sni=self.cfg.get('sni') or self.cfg['public_host'],fp='chrome',flow='xtls-rprx-vision')
        if security=='reality':
            reality=stream.get('realitySettings',{})
            public_key=self.cfg.get('public_key') or reality.get('settings',{}).get('publicKey')
            names=reality.get('serverNames',[])
            shorts=reality.get('shortIds',[])
            sni=self.cfg.get('sni') or (names[0] if names else '')
            if not public_key or not sni or not shorts:
                raise ShopError('Для REALITY укажи public_key, SNI и Short ID в панели/конфиге.')
            params.update(pbk=public_key,sni=sni,sid=shorts[0],fp='chrome',spx='/',flow='xtls-rprx-vision')
        host=self.cfg['public_host']
        if ':' in host: host='['+host+']'
        port=self.cfg.get('public_port') or r['port']
        return 'vless://'+o['uuid']+'@'+host+':'+str(port)+'?'+urllib.parse.urlencode(params)+'#'+urllib.parse.quote('ReVPN-'+o['id'][:8])

    def exists(self,o):
        r=self.inbound()
        return any(c.get('email')==o['email'] or c.get('id')==o['uuid'] for c in obj(r['settings']).get('clients',[]))

    def ensure(self,o):
        r=self.inbound()
        link=self.link(o,r)  # Validate export settings before writing anything.
        clients=obj(r['settings']).get('clients',[])
        existing=next((c for c in clients if c.get('email')==o['email'] or c.get('id')==o['uuid']),None)
        if existing:
            if existing.get('id')!=o['uuid'] or existing.get('email')!=o['email'] or int(existing.get('totalGB',0))!=o.get('quota_bytes',o['gb']*1024**3) or int(existing.get('expiryTime',0))!=o['expiry_ms']:
                raise ShopError('Конфликт клиента в панели. Нужна проверка администратора.')
            return link
        # A prolonged outage before first provision must not consume a paid period.
        # Existing clients are never extended on retries.
        if o['expiry_ms']<=int(time.time())*1000:
            raise ShopError('Срок заказа истёк до выдачи: администратор должен восстановить заказ.')
        flow='' if obj(r['streamSettings']).get('security','none')=='none' else 'xtls-rprx-vision'
        client={'id':o['uuid'],'email':o['email'],'subId':o['sub_id'],'enable':True,'flow':flow,
            'totalGB':o.get('quota_bytes',o['gb']*1024**3),'expiryTime':o['expiry_ms'],'limitIp':0,'tgId':o['user_id'],'reset':0}
        try:
            self.request('panel/api/clients/add','POST',data={'client':client,'inboundIds':[self.cfg['inbound_id']]})
        except APIError as e:
            if e.status not in (404,405): raise
            legacy={**client,'tgId':str(o['user_id'])}
            self.request('panel/api/inbounds/addClient','POST',data={'id':self.cfg['inbound_id'],'settings':json.dumps({'clients':[legacy]})},form=True)
        # Read back; an API success alone is not treated as proof of provisioning.
        r=self.inbound()
        found=next((c for c in obj(r['settings']).get('clients',[]) if c.get('id')==o['uuid']),None)
        if not found or found.get('email')!=o['email'] or int(found.get('totalGB',0))!=o.get('quota_bytes',o['gb']*1024**3) or int(found.get('expiryTime',0))!=o['expiry_ms']:
            raise APIError('3X-UI verification')
        return link

class Telegram:
    def __init__(self,token):
        self.http=HTTP('Telegram','https://api.telegram.org/bot'+token)

    def call(self,method,**data):
        r=self.http.call(method,'POST',data=data,timeout=40)
        if r.get('ok') is not True: raise APIError('Telegram',r.get('error_code',0))
        return r['result']

    def send(self,uid,text,buttons=None):
        data={'chat_id':uid,'text':text,'parse_mode':'HTML','link_preview_options':{'is_disabled':True},'protect_content':True}
        if buttons: data['reply_markup']={'inline_keyboard':buttons}
        return self.call('sendMessage',**data)
