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



def public_page(path,cfg,support):
    from core import price,rubles
    from delivery import PRODUCTS
    support_url='https://t.me/'+support.lstrip('@')
    bot=cfg.get('telegram',{}).get('bot_username') or 'ReversVPNbot'
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}',bot): bot='ReversVPNbot'
    def link(label,url,cls='button'):
        return '<a class="'+cls+'" href="'+html.escape(url,quote=True)+'">'+html.escape(label)+'</a>'
    privacy=path=='/privacy'
    title='Политика конфиденциальности' if privacy else 'ReVPN — подключайся проще'
    if privacy:
        content='<span class="eyebrow">ReVPN · редакция от 30.09.2026</span><h1>Политика конфиденциальности</h1>\n<p>Эта страница описывает обработку данных в боте ReVPN, его Mini App и сервисе VPN/MTProto. По вопросам обработки данных отвечает команда ReVPN через поддержку ниже.</p>\n<h2>Какие данные обрабатываются</h2><p>Telegram ID, отображаемое имя, выбранный тариф и оператор, состояние диалога с ботом; параметры, суммы, статусы и идентификаторы заказов и счетов. Для предоставления доступа хранятся ключи VPN/прокси, ссылки подписок, срок действия, лимиты и счётчики переданного трафика.</p>\n<p>При создании управляемого бота хранятся ID владельца, ID и username бота, его токен для управления и информация о выдаче пробного доступа. Не передавай ссылки подписок и токены посторонним.</p>\n<h2>Зачем нужны данные</h2><p>Для выдачи и восстановления доступа, проверки оплаты, управления подписками и зеркалами, предотвращения повторной выдачи бонуса, обработки обращений и устранения сбоев.</p>\n<h2>Кому передаются данные</h2><p>Telegram обеспечивает сообщения и работу Mini App. Платёжный сервис Lolzteam Market получает данные для создания и проверки счёта, включая Telegram ID, сумму и идентификатор заказа. Панель VPN получает данные ключа, лимиты и срок действия. Инфраструктура хостинга обрабатывает соединения. У этих сторон есть собственные условия обработки данных. Бот не запрашивает реквизиты банковской карты.</p>\n<h2>Сайт и Mini App</h2><p>Mini App показывает публичный каталог и переводит в бот для покупки и просмотра подписок. Эта версия не отправляет Telegram initData на наш сервер, не использует рекламную аналитику, cookies или локальное хранилище. Подключается официальный скрипт Telegram. Веб-сервер и инфраструктура могут обрабатывать IP-адрес, время запроса, адрес страницы и сведения браузера в технических журналах.</p>\n<h2>Срок хранения и удаление</h2><p>Автоматический срок удаления заказов и аккаунтов в текущей версии не установлен: сведения сохраняются до обработки запроса на удаление или очистки оператором. Для запроса копии, исправления или удаления своих данных напиши в поддержку с того же Telegram-аккаунта. Поддержка уточнит объём удаления, последствия для действующей подписки и применимые ограничения. Резервные копии и журналы могут сохраняться отдельно.</p>\n<h2>Защита и ограничения</h2><p>Административные действия доступны ограниченному списку Telegram ID. Сайт работает через HTTPS при корректной настройке сервера. Мы не обещаем абсолютной анонимности или полного отсутствия технических журналов: их состав зависит от настроек VPN, прокси и хостинга.</p>\n<h2>Контакты и изменения</h2><p>Актуальная редакция публикуется на этой странице. Обращения по персональным данным:</p>'
        content+=link(support,support_url)+link('Вернуться в ReVPN','/app','plain')
    else:
        content='<span class="eyebrow">VPN · TELEGRAM · ReVPN</span><h1>Твоё подключение.<br>В одном месте.</h1><p class="muted">Выбери тариф. Срок, трафик и итоговую сумму подтвердим в боте перед оплатой.</p><div class="grid">'
        for key,label in PRODUCTS.items():
            cost=rubles(price(cfg['pricing'],720,0,key)) if cfg.get('pricing') else '—'
            content+='<article><span class="badge">'+('Telegram' if key=='mtproto' else 'VPN')+'</span><h2>'+html.escape(label)+'</h2><p class="price">'+cost+' ₽ <small>/ 30 дней</small></p>'+link('Выбрать','https://t.me/'+bot+'?start=app_'+key)+'</article>'
        content+='</div><section><h2>Уже подключён?</h2>'+link('Мои подписки','https://t.me/'+bot+'?start=app_account')+link('Бесплатный Telegram-прокси','https://t.me/'+bot+'?start=app_free','plain')+'</section>'
        content+='<section><h2>Помощь рядом</h2><p>После оплаты открой подписку в боте и нажми «Добавить VPN в Happ». Для Telegram-прокси используй кнопку подключения.</p>'+link('Написать в поддержку',support_url,'plain')+link('Политика конфиденциальности','/privacy','plain')+'</section>'
    css="""*{box-sizing:border-box}body{margin:0;background:var(--tg-theme-bg-color,#0c1422);color:var(--tg-theme-text-color,#edf4ff);font:16px/1.6 system-ui}main{max-width:880px;margin:auto;padding:32px 20px 60px}h1{font-size:clamp(30px,7vw,48px);line-height:1.13;letter-spacing:-1px;margin:20px 0}h2{font-size:20px;line-height:1.3}.eyebrow,.muted,small{color:var(--tg-theme-hint-color,#96a8c0)}.eyebrow{font-size:12px;letter-spacing:2px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:14px;margin-top:28px}article,section{background:var(--tg-theme-secondary-bg-color,#162339);padding:22px;border-radius:22px}section{margin-top:18px}.badge{font-size:12px;color:#8bceff}.price{font-size:28px;font-weight:700}small{font-size:14px;font-weight:400}a{color:var(--tg-theme-link-color,#92cfff)}.button{display:block;background:var(--tg-theme-button-color,#9bd7ff);color:var(--tg-theme-button-text-color,#0c1422);border-radius:14px;padding:13px;text-align:center;text-decoration:none;font-weight:650}.plain{display:block;padding:14px 0}a:focus-visible{outline:3px solid #f9ce69;outline-offset:3px}"""
    scripts='' if privacy else """<script src="https://telegram.org/js/telegram-web-app.js"></script><script>const app=window.Telegram?.WebApp;if(app){app.ready();app.expand();document.addEventListener('click',e=>{const a=e.target.closest('a');if(a&&a.href.startsWith('https://t.me/')){e.preventDefault();app.openTelegramLink(a.href);app.close();}});}</script>"""
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+css+'</style></head><body><main>'+content+'</main>'+scripts+'</body></html>').encode()


def handler(db_path,public_base,support,cfg=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass # URLs are credentials; never log subscription tokens.
        def do_GET(self):
            path=urlsplit(self.path).path
            if path in ('/','/app','/privacy'):
                headers={'Content-Type':'text/html; charset=utf-8'}
                if path!='/privacy':
                    headers['Content-Security-Policy']="default-src 'none'; script-src https://telegram.org 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors https://web.telegram.org https://*.telegram.org; base-uri 'none'; form-action 'none'"
                return self.reply(200,public_page(path,cfg or {},support),headers)
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
    server=HTTPServer(('127.0.0.1',sub.get('local_port',8090)),handler(Path(a.data)/'shop.sqlite3',sub['public_base'],cfg['telegram']['support'],cfg))
    server.serve_forever()
