#!/usr/bin/env python3
"""Interactive local installer configuration. No secret values in argv/logs."""
import getpass
import copy
import re
import secrets
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import urllib.parse
from providers import Panel, Telegram, obj

DEST=Path('/etc/revpn-shop')

def ask(label,default=''):
    return input(label+(' ['+str(default)+']' if default!='' else '')+': ').strip() or default

def free(port):
    try:
        with socket.socket() as s: s.bind(('0.0.0.0',port))
        return True
    except OSError: return False

def firewall(port):
    def run(args): return subprocess.run(args,text=True,capture_output=True,env={**os.environ,'LC_ALL':'C'})
    if shutil.which('ufw') and 'Status: active' in run(['ufw','status']).stdout:
        r=run(['ufw','allow',str(port)+'/tcp'])
        if r.returncode: raise RuntimeError('Не удалось открыть порт в UFW.')
        print('TCP-порт открыт в UFW.')
    elif shutil.which('firewall-cmd') and run(['firewall-cmd','--state']).returncode==0:
        for args in (['--permanent','--add-port='+str(port)+'/tcp'],['--add-port='+str(port)+'/tcp']):
            if run(['firewall-cmd']+args).returncode: raise RuntimeError('Не удалось открыть порт в firewalld.')
        print('TCP-порт открыт в firewalld.')
    else:
        print('UFW/firewalld не активны. Отдельные nftables/iptables и firewall хостинга не изменены.')
    print('Если у хостинга есть отдельный firewall, разреши входящий TCP '+str(port)+'.')

def main():
    if os.geteuid()!=0: raise RuntimeError('Нужен root.')
    os.umask(0o077)
    DEST.mkdir(mode=0o750,parents=True,exist_ok=True)
    path=DEST/'config.json'
    if path.exists():
        print('Настройки уже есть. Изменение вручную: nano '+str(path))
        return
    cfg=json.loads((Path(__file__).parent/'config.example.json').read_text())
    print('Секреты вводятся здесь, не отправляй их в чат. Пароли при вводе не видны.')
    cfg['telegram']['token']=getpass.getpass('Токен Telegram от @BotFather: ').strip()
    admin_id=ask('Твой числовой Telegram ID (Enter — узнать через своего бота)')
    if not admin_id:
        tg=Telegram(cfg['telegram']['token'])
        me=tg.call('getMe')
        input('Открой https://t.me/'+me['username']+', отправь /start и нажми Enter здесь: ')
        updates=tg.call('getUpdates',timeout=5,limit=100,allowed_updates=['message'])
        seen={}
        for update in updates:
            message=update.get('message',{})
            if message.get('chat',{}).get('type')=='private' and message.get('from'):
                who=message['from']; seen[who['id']]=who.get('username','без username')
        for ident,name in seen.items(): print('ID:',ident,'| @'+name)
        admin_id=ask('Введи свой ID из списка выше')
    cfg['telegram']['admins']=[int(admin_id)]
    cfg['telegram']['support']=ask('Твой Telegram username для поддержки (@...)')
    cfg['lolz']['token']=getpass.getpass('Access Token LZT с правом invoice: ').strip()
    cfg['lolz']['merchant_id']=int(ask('merchant_id магазина LZT'))
    cfg['lolz']['test']=ask('Начать с тестовых счетов без выдачи VPN? y/n','y').lower()!='n'
    dbpath=Path('/etc/x-ui/x-ui.db')
    panel=cfg['panel']
    if dbpath.exists():
        db=sqlite3.connect('file:'+str(dbpath)+'?mode=ro',uri=True)
        try: settings=dict(db.execute('SELECT key,value FROM settings'))
        finally: db.close()
        scheme='https' if settings.get('webCertFile') and settings.get('webKeyFile') else 'http'
        listen=settings.get('webListen') or '127.0.0.1'
        if listen in ('0.0.0.0','::','[::]'): listen='127.0.0.1'
        if listen!='127.0.0.1' and listen!='::1':
            print('Панель слушает отдельный IP. Укажи её HTTPS URL ниже.')
            panel['url']=ask('HTTPS URL панели с портом и полным путём')
        else:
            panel['url']=scheme+'://'+('['+listen+']' if ':' in listen else listen)+':'+str(settings.get('webPort',2053))+('/'+settings.get('webBasePath','/').strip('/')).rstrip('/')+'/'
            if scheme=='https':
                shutil.copyfile(settings['webCertFile'],DEST/'panel-ca.pem')
                os.chmod(DEST/'panel-ca.pem',0o644)
                panel['ca_file']=str(DEST/'panel-ca.pem')
                panel['local_tls']=True
            panel['host_header']=settings.get('webDomain','')
    else:
        panel['url']=ask('URL панели: https://домен:порт/путь/')
    panel['url']=ask('URL панели (Enter — найденный автоматически)',panel['url'])
    panel['url']=panel['url'].rstrip('/')
    if panel['url'].endswith('/panel'): panel['url']=panel['url'][:-6]
    panel['url']+='/'
    panel['token']=getpass.getpass('API-токен 3X-UI (Enter — логин и пароль): ').strip()
    if panel['token']:
        panel['username']=panel['password']=''
    else:
        panel['username']=ask('Логин 3X-UI')
        panel['password']=getpass.getpass('Пароль 3X-UI: ')
        print('Если у панели включена 2FA, используй API-токен; пароль с 2FA не подходит для фонового бота.')
    panel['public_host']=ask('Публичный IP или домен VPN','2.26.85.86')
    api=Panel(panel)
    rows=api.request('panel/api/inbounds/list') or []
    for r in rows:
        print('ID',r['id'],'|',r['protocol'],'| порт',r['port'],'|',r.get('remark',''))
    print('Можно использовать существующий VLESS TCP/RAW inbound или создать отдельный.')
    ident=int(ask('ID подключения; 0 — создать новое','0'))
    if ident==0:
        # Reuse a previously created dedicated inbound after an interrupted setup.
        prior=next((r for r in rows if r.get('remark')=='ReVPN-Shop'),None)
        if prior:
            ident=prior['id']; print('Найден ранее созданный ReVPN-Shop; используется ID',ident)
        else:
            print('Будет создан VLESS/TCP без TLS/REALITY. Это не шифрует сам туннель.')
            port=int(ask('Порт VPN','21146'))
            if not 1024<=port<=65535 or any(int(r['port'])==port for r in rows) or not free(port):
                raise RuntimeError('Порт занят или недопустим. Повтори настройку с другим портом.')
            api.request('panel/api/inbounds/add','POST',data={
                'remark':'ReVPN-Shop','enable':'true','listen':'','port':port,'protocol':'vless','total':0,'up':0,'down':0,'expiryTime':0,
                'settings':json.dumps({'clients':[],'decryption':'none','encryption':'none','fallbacks':[]}),
                'streamSettings':json.dumps({'network':'tcp','security':'none','tcpSettings':{'header':{'type':'none'}}}),
                'sniffing':json.dumps({'enabled':False,'destOverride':['http','tls']})},form=True)
            rows=api.request('panel/api/inbounds/list')
            match=next((r for r in rows if r.get('remark')=='ReVPN-Shop' and int(r['port'])==port),None)
            if not match: raise RuntimeError('Не удалось подтвердить создание подключения. Проверь панель перед повтором.')
            ident=match['id']
    panel['inbound_id']=int(ident)
    inbound=api.inbound()
    security=obj(inbound['streamSettings']).get('security','none')
    if security in ('tls','reality'):
        panel['sni']=ask('SNI (Enter — из настроек/домен VPN)','')
    if security=='reality':
        panel['public_key']=ask('REALITY public key (Enter — из панели)','')
    api.link({'uuid':'00000000-0000-4000-8000-000000000001','id':'setup'},inbound)
    firewall(int(inbound['port']))
    cfg['pricing']['unlimited_30d_rub']=int(ask('Цена безлимита на 30 дней, ₽','50'))
    print('Пакеты с лимитом: пример формулы 20 ₽ за 30 дней + 0.05 ₽ за ГБ. Всё меняется в config.json.')
    cfg['nodes']['regular']['panel']=copy.deepcopy(panel)
    cfg['subscription']['public_base']=ask('HTTPS адрес подписок (домен должен указывать на этот сервер), например https://sub.example.com:8443')
    parsed=urllib.parse.urlsplit(cfg['subscription']['public_base'])
    if parsed.scheme!='https' or not parsed.hostname or parsed.path not in ('','/') or parsed.query or parsed.fragment or parsed.username:
        raise RuntimeError('Нужен HTTPS адрес без пути, логина и параметров.')
    if ask('Настроить пять реально проверенных профилей белых списков? y/n','n').lower()=='y':
        for key in ('max','yandex','disk','vk','vkvideo'):
            node=cfg['nodes'][key]; print('Профиль:',node['label'])
            remote=copy.deepcopy(panel)
            remote['url']=ask('URL 3X-UI этого профиля',panel['url'])
            if remote['url']!=panel['url']:
                remote.update(token=getpass.getpass('API-токен этой панели: ').strip(),username='',password='',ca_file='',local_tls=False,host_header='')
            remote['inbound_id']=int(ask('ID VLESS TCP/RAW inbound'))
            remote['public_host']=ask('Публичный адрес профиля')
            remote['public_port']=int(ask('Публичный порт; 0 = порт inbound','0'))
            remote['sni']=ask('SNI; Enter = настройки inbound')
            remote['public_key']=ask('REALITY public key; Enter = настройки inbound')
            api_node=Panel(remote); inbound_node=api_node.inbound()
            api_node.link({'uuid':'00000000-0000-4000-8000-000000000001','id':'setup'},inbound_node)
            node.update(enabled=True,panel=remote)
            print('Открой TCP-порт профиля на его сервере и в firewall хостинга:',remote['public_port'] or inbound_node['port'])
        print('Поддержка определяется реальными тестами на мобильной сети, не названием профиля.')
        ops=ask('Проверенные операторы через запятую: mts,megafon,beeline,t2,yota (Enter = пока никого)')
        cfg['supported_operators']=[v.strip() for v in ops.split(',') if v.strip()]
        if set(cfg['supported_operators'])-{'mts','megafon','beeline','t2','yota'}: raise RuntimeError('Неизвестный оператор.')
    cfg['mtproto']['public_host']=ask('Публичный адрес MTProto',panel['public_host'])
    for kind,label in (('paid','платный'),('free','бесплатный со спонсорским каналом')):
        section=cfg['mtproto'][kind]
        if ask('Включить '+label+' MTProto? y/n','n').lower()!='y': continue
        section['port']=int(ask('TCP-порт MTProto',str(section['port'])))
        if not 1024<=section['port']<=65535 or not free(section['port']): raise RuntimeError('Порт занят или недопустим.')
        if kind=='free':
            section['secret']=secrets.token_hex(16)
            print('Зарегистрируй прокси у https://t.me/MTProxyBot через /newproxy.')
            print('Адрес:',cfg['mtproto']['public_host'],'порт:',section['port'],'secret:',section['secret'])
            section['ad_tag']=ask('Полученный sponsor tag (32 hex)')
            if not re.fullmatch('[a-fA-F0-9]{32}',section['ad_tag']): raise RuntimeError('Некорректный sponsor tag.')
        section['enabled']=True; firewall(section['port'])
    tmp=DEST/'config.tmp'
    tmp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
    os.chmod(tmp,0o640); tmp.replace(path)
    print('Настройки сохранены. Установщик сейчас проверит доступ к API.')

if __name__=='__main__':
    try: main()
    except Exception as e:
        print('Настройка не завершена:',str(e))
        raise SystemExit(1)
