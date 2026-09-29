#!/usr/bin/env python3
"""Single-process Telegram long polling + durable Lolz payment reconciliation."""
import argparse
import fcntl
import html
import json
import logging
import os
from pathlib import Path
import re
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from core import Store, Engine, ShopError, price, rubles, description
from providers import Telegram, Lolz, Panel, APIError
from delivery import Delivery, PRODUCTS, OPERATORS, targets, ready, proxy_link

log=logging.getLogger('revpn-shop')

def button(text,data): return {'text':text,'callback_data':data}
def escaped(value): return html.escape(str(value))

def load_config(path):
    cfg=json.loads(Path(path).read_text())
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]+',cfg['telegram']['token']): raise ShopError('Неверный Telegram token.')
    if not cfg['telegram']['admins'] or any(type(i) is not int or i<=0 for i in cfg['telegram']['admins']): raise ShopError('Нужен числовой admin ID.')
    if not cfg['telegram']['support'].startswith('@'): raise ShopError('Укажи support в формате @username.')
    if not cfg['lolz']['token'] or type(cfg['lolz']['merchant_id']) is not int or cfg['lolz']['merchant_id']<=0: raise ShopError('Нужны Lolz token и merchant_id.')
    if type(cfg['lolz']['test']) is not bool or not 300<=cfg['lolz']['invoice_lifetime']<=43200: raise ShopError('Неверные настройки Lolz.')
    if not 1<=cfg['panel']['inbound_id']: raise ShopError('Нужен inbound ID.')
    sub=cfg.get('subscription',{})
    if not re.fullmatch(r'https://[^/?#]+(?::[0-9]{1,5})?',sub.get('public_base','')): raise ShopError('Нужен HTTPS public_base для подписок.')
    if not 1024<=int(sub.get('local_port',8090))<=65535: raise ShopError('Неверный local_port подписок.')
    if not re.fullmatch(r'[A-Za-z0-9.:-]+',cfg['panel']['public_host']): raise ShopError('Неверный адрес VPN.')
    for k in ('minimum_rub','unlimited_30d_rub','limited_base_30d_rub','per_gb_rub'):
        from decimal import Decimal
        value=Decimal(str(cfg['pricing'][k]))
        if not value.is_finite() or value<0: raise ShopError('Цены должны быть неотрицательными.')
    if cfg['pricing']['minimum_rub']<1: raise ShopError('Минимальная цена — 1 рубль.')
    for h in (1,24,168,720): price(cfg['pricing'],h,0)
    return cfg

class Bot:
    def __init__(self,cfg,store,tg,engine):
        self.cfg,self.s,self.tg,self.engine=cfg,store,tg,engine
        self.limits={}
        self.last_delivery={}
        self.running=True

    def home(self,uid):
        self.s.state(uid,{})
        text='<b>ReVPN 🥶</b>\n\nVPN и Telegram-прокси. Выбери подключение, объём трафика и срок — от одного часа.\n\n<b>Безлимит на 30 дней:</b>'
        rows=[]
        for key,label in PRODUCTS.items():
            cost=rubles(price(self.cfg['pricing'],720,0,key))
            text+='\n'+label+' — <b>'+cost+' ₽</b>'
            rows.append([button(label+' · '+cost+' ₽ / 30 дн.','product:'+key)])
        if self.cfg['lolz']['test']: text+='\n\n<b>Тестовый режим:</b> реальный доступ не выдаётся.'
        rows += [[button('Добавить VPN в Happ','connect'),button('Мои покупки','mine')],
                 [button('Бесплатный Telegram-прокси','free')],[button('Как подключиться','help')]]
        self.tg.send(uid,text,rows)

    def product(self,uid,product):
        if product not in PRODUCTS: raise ShopError('Неизвестный тариф.')
        self.s.state(uid,{'product':product})
        if product in ('whitelist','bundle'):
            return self.tg.send(uid,'Выбери своего мобильного оператора 🥶',
                [[button(label,'operator:'+key)] for key,label in OPERATORS.items()]+[[button('Нет моего оператора','operator:other')]])
        targets(self.cfg,product)
        if product=='mtproto': return self.durations(uid,0)
        return self.traffic(uid)

    def traffic(self,uid):
        state=self.s.state(uid)
        if 'product' not in state: return self.home(uid)
        self.tg.send(uid,'Выбери трафик. В наборе лимит делится поровну между профилями.',
            [[button('Безлимит','gb:0')],[button('100 ГБ','gb:100'),button('500 ГБ','gb:500')],
             [button('Свой объём','customgb')],[button('Главное меню','home')]])

    def durations(self,uid,gb):
        state=self.s.state(uid)
        if 'product' not in state: raise ShopError('Выбор тарифа устарел. Открой /start.')
        product=state['product']
        selection=uuid.uuid4().hex[:12]
        self.s.state(uid,{**state,'gb':gb,'step':'duration','selection':selection})
        rows=[]
        for h,label in ((1,'1 час'),(6,'6 часов'),(24,'1 день'),(168,'1 неделя'),(720,'30 дней'),(2160,'90 дней')):
            if h<=self.cfg['pricing']['max_hours']:
                cost=rubles(price(self.cfg['pricing'],h,gb,product))
                rows.append([button(label+' — '+cost+' ₽',f'time:{selection}:{h}')])
        rows.extend([[button('Свой срок','customtime')],[button('Назад','buy')]])
        self.tg.send(uid,'<b>'+PRODUCTS[product]+'</b>\n'+('Безлимитный трафик' if not gb else str(gb)+' ГБ на весь срок')+'\n\nВыбери срок — на кнопке итоговая цена:',rows)

    def quote(self,uid,hours,gb):
        state=self.s.state(uid)
        if 'product' not in state: raise ShopError('Выбор тарифа устарел. Открой /start.')
        product=state['product']; operator=state.get('operator','')
        selected=targets(self.cfg,product,operator)
        amount=price(self.cfg['pricing'],hours,gb,product)
        qid=self.s.quote(uid,hours,gb,amount,product,operator,selected)
        self.s.state(uid,{})
        extra='\nЛимит делится поровну между '+str(len(selected))+' профилями.' if gb and len(selected)>1 else ''
        self.tg.send(uid,f'<b>{PRODUCTS[product]} · {description(hours,gb)}</b>\nК оплате: <b>{rubles(amount)} ₽</b>.\nСрок начинается при выдаче доступа. Автосписаний нет.'+extra,
            [[button('Перейти к оплате · '+rubles(amount)+' ₽','confirm:'+qid)],[button('Изменить тариф','buy')]])

    def show_order(self,uid,o):
        if o['user_id']!=uid: raise ShopError('Это чужой заказ.')
        title=f"Заказ <code>{o['id']}</code>\n{description(o['hours'],o['gb'])} — {rubles(o['amount'])} ₽\n"
        if o['status']=='active' and o['expiry_ms']<=time.time()*1000:
            return self.tg.send(uid,'<b>Срок подписки закончился</b>\nВыбери новый срок, чтобы снова подключиться.',[[button('Купить подписку','buy')]])
        if o['status']=='active':
            dt=datetime.fromtimestamp(o['expiry_ms']/1000,timezone.utc).strftime('%d.%m.%Y %H:%M UTC')
            name=escaped(o.get('display_name') or 'Друг')
            text=f'<b>Готово, {name}! Твой ReVPN уже морозит 🥶</b>\nДо {dt}.'
            if o.get('product')=='mtproto':
                rows=[[{'text':'Подключить Telegram-прокси 🥶','url':o['link']}]]
            else:
                text+='\nВсе оплаченные профили — в одной подписке.'
                rows=[[{'text':'Добавить VPN в Happ 🥶','url':o['link'].replace('/sub/','/connect/')}],
                      [{'text':'Скопировать ссылку подписки','copy_text':{'text':o['link']}}]]
                text+='\n\nСсылка подписки для ручного импорта:\n<code>'+escaped(o['link'])+'</code>'
            self.tg.send(uid,text,rows+[[button('Мои подписки','mine')]])
            self.s.patch(o['id'],delivered=1)
        elif o['status']=='test_paid':
            self.tg.send(uid,title+'Тестовая оплата подтверждена. Реальный VPN не создавался.')
            self.s.patch(o['id'],delivered=1)
        elif o['status']=='pending':
            text='<b>Ссылка на оплату готова</b>\n\n'+title
            if self.cfg['lolz']['test']: text+='\n<b>Тестовый счёт — доступ не выдаётся.</b>\n'
            text+='\n'+escaped(o['invoice_url'])+'\n\nПосле оплаты подписка придёт сюда автоматически.'
            self.tg.send(uid,text,
                [[{'text':'Оплатить '+rubles(o['amount'])+' ₽','url':o['invoice_url']}],
                 [{'text':'Скопировать ссылку оплаты','copy_text':{'text':o['invoice_url']}}],
                 [button('Проверить оплату','check:'+o['id'])],[button('Главное меню','home')]])
            self.s.patch(o['id'],invoice_sent=1)
        elif o['status'] in ('paid','provisioning'):
            self.tg.send(uid,title+'Оплата подтверждена. Готовим ключ; при сбое повторим автоматически.',[[button('Проверить','check:'+o['id'])]])
        elif o['status']=='expired':
            self.tg.send(uid,title+'Срок оплаты истёк. Если уже оплатил — нажми «Проверить».',[[button('Проверить','check:'+o['id'])],[button('Новый заказ','buy')]])
        elif o['status']=='review':
            self.tg.send(uid,title+'Нужна проверка платежа поддержкой: '+escaped(self.cfg['telegram']['support']))
        else:
            self.tg.send(uid,title+'Создаём счёт. Заказ сохранён; при сбое повторим автоматически.',[[button('Проверить','check:'+o['id'])]])

    def mine(self,uid):
        orders=self.s.mine(uid)
        if not orders:
            self.tg.send(uid,'Покупок пока нет.',[[button('Купить VPN','buy')]])
            return
        labels={'active':'Выдан','pending':'Ждёт оплаты','creating':'Создание счёта','expired':'Счёт истёк','paid':'Оплачен','provisioning':'Выдача','test_paid':'Тест оплачен','review':'Проверка'}
        self.tg.send(uid,'Последние покупки:',[[button(labels.get(o['status'],o['status'])+' · '+description(o['hours'],o['gb']), 'view:'+o['id'])] for o in orders])

    def help(self,uid):
        self.tg.send(uid,'После оплаты нажми «Добавить подписку в Happ». Она содержит все купленные профили.\n'
          'Срок и трафик указаны перед оплатой. Повторная покупка выдаёт новый ключ.\n'
          'Проверка платежа выполняется через Lolz API; чек или сообщение не подтверждают оплату.\n'
          'Поддержка и возвраты: '+escaped(self.cfg['telegram']['support'])+'\n'
          'При проблеме пришли поддержке номер заказа из «Мои покупки».\n'
          'Храним Telegram ID, параметры заказов и ключи для повторной выдачи. Банковские данные бот не получает.',[[button('Главное меню','home')]])

    def process_order(self,uid,oid):
        self.s.get(oid,uid)
        try: self.engine.check(oid)
        except ShopError as exc:
            self.engine.retry_later(oid,type(exc).__name__)
            log.warning('order=%s action=check failed=%s',oid,type(exc).__name__)
        o=self.s.get(oid,uid)
        if o['status']=='creating' and o.get('error'):
            return self.tg.send(uid,'<b>Платёжный сервис пока не вернул ссылку</b>\nЗаказ сохранён. Повторим запрос автоматически и пришлём ссылку сюда.\nЗаказ: <code>'+o['id']+'</code>',[[button('Повторить проверку','check:'+oid)],[button('Помощь','help')]])
        self.show_order(uid,o)

    def callback(self,uid,data):
        if data=='home': return self.home(uid)
        if data=='buy': return self.home(uid)
        if data.startswith('product:'): return self.product(uid,data.split(':',1)[1])
        if data.startswith('operator:'):
            operator=data.split(':',1)[1]; state=self.s.state(uid)
            if operator=='other' or operator not in self.cfg.get('supported_operators',[]):
                self.s.state(uid,{})
                return self.tg.send(uid,'Пока не можем помочь с твоим оператором 🥶 Когда появится поддержка, он будет доступен здесь.',[[button('Главное меню','home')]])
            if state.get('product') not in ('whitelist','bundle'): return self.home(uid)
            targets(self.cfg,state['product'],operator)
            self.s.state(uid,{**state,'operator':operator})
            return self.traffic(uid)
        if data=='free':
            free=self.cfg.get('mtproto',{}).get('free',{})
            if not free.get('enabled') or not free.get('ad_tag') or not ready(self.engine.panel.data,'free'):
                raise ShopError('Бесплатный прокси пока недоступен.')
            return self.tg.send(uid,'Бесплатный Telegram-прокси 🥶\nВ списке чатов может отображаться спонсорский канал.',[[{'text':'Подключить бесплатно','url':proxy_link(self.cfg,free['secret'],'free')}]])
        if data=='connect':
            orders=[o for o in self.s.mine(uid) if o['status']=='active' and o['product']!='mtproto' and o['expiry_ms']>time.time()*1000]
            if not orders: return self.tg.send(uid,'<b>Добавить VPN в Happ</b>\nПосле покупки здесь появится твоя подписка. Если уже оплатил, открой «Мои покупки».',[[button('Выбрать VPN','buy')],[button('Мои покупки','mine')]])
            return self.tg.send(uid,'<b>Выбери подписку для подключения</b>',[[button(PRODUCTS.get(o['product'],'VPN')+' · до '+datetime.fromtimestamp(o['expiry_ms']/1000,timezone.utc).strftime('%d.%m.%Y'),'view:'+o['id'])] for o in orders])
        if data=='mine': return self.mine(uid)
        if data=='help': return self.help(uid)
        if data=='customgb':
            self.s.state(uid,{**self.s.state(uid),'step':'gb'})
            return self.tg.send(uid,'Введи объём в ГБ целым числом, например: <code>250</code>')
        if data.startswith('gb:'):
            gb=int(data.split(':')[1]); price(self.cfg['pricing'],1,gb)
            return self.durations(uid,gb)
        if data=='customtime':
            state=self.s.state(uid)
            if 'gb' not in state: return self.traffic(uid)
            self.s.state(uid,{**state,'step':'time'})
            return self.tg.send(uid,'Введи срок, например <code>3 часа</code> или <code>12 дней</code>. Минимум — 1 час.')
        if data.startswith('time:'):
            _,selection,hours=data.split(':')
            state=self.s.state(uid)
            if state.get('step')!='duration' or state.get('selection')!=selection:
                raise ShopError('Эти кнопки устарели. Выбери тариф заново в /start.')
            return self.quote(uid,int(hours),state['gb'])
        if data.startswith('confirm:'):
            if self.cfg['lolz']['test'] and uid not in self.cfg['telegram']['admins']:
                raise ShopError('Магазин тестируется. Покупки пока доступны только администратору.')
            o=self.s.order(data.split(':')[1],uid)
            if o['status']=='creating':
                self.tg.send(uid,'<b>Создаём ссылку на оплату…</b>\nЭто может занять несколько секунд. Ссылка появится в этом чате.')
            return self.process_order(uid,o['id'])
        if data.startswith(('check:','view:')):
            action,oid=data.split(':',1)
            if action=='view': return self.show_order(uid,self.s.get(oid,uid))
            o=self.s.get(oid,uid)
            # Button spam cannot exceed reconciliation/provider limits.
            if time.time()<o['next_check'] and o['status'] not in ('active','test_paid'):
                return self.show_order(uid,o)
            return self.process_order(uid,oid)
        raise ShopError('Кнопка устарела. Нажми /start.')

    def message(self,uid,text):
        if text.startswith('/start order_'):
            oid=text.split('order_',1)[1].strip()
            return self.process_order(uid,oid)
        if text.split(' ',1)[0] in ('/start','/menu','/cancel'): return self.home(uid)
        if text in ('/help','/paysupport','/support','/privacy'): return self.help(uid)
        if text in ('/my','/orders'): return self.mine(uid)
        if text=='/id': return self.tg.send(uid,f'Твой Telegram ID: <code>{uid}</code>')
        if text.startswith('/admin') and uid in self.cfg['telegram']['admins']:
            counts=list(self.s.db.execute('SELECT status,COUNT(*) FROM orders GROUP BY status'))
            return self.tg.send(uid,'Заказы:\n'+'\n'.join(escaped(k)+': '+str(v) for k,v in counts))
        state=self.s.state(uid)
        if state.get('step')=='gb':
            if not re.fullmatch(r'\d{1,6}',text): raise ShopError('Введи целое число ГБ, например 100.')
            gb=int(text)
            if gb==0: raise ShopError('Для безлимита выбери соответствующую кнопку в /start.')
            price(self.cfg['pricing'],1,gb)
            return self.durations(uid,gb)
        if state.get('step')=='time':
            match=re.fullmatch(r'(\d{1,5})\s*(ч|час|часа|часов|h|д|день|дня|дней|дн|d)',text.lower().strip())
            if not match: raise ShopError('Пример: 3 часа или 12 дней.')
            hours=int(match[1])*(24 if match[2].startswith(('д','d')) else 1)
            return self.quote(uid,hours,state['gb'])
        return self.home(uid)

    def update(self,u):
        cb=u.get('callback_query')
        msg=cb.get('message') if cb else u.get('message')
        if not msg or msg.get('chat',{}).get('type')!='private': return
        uid=(cb['from'] if cb else msg['from'])['id']
        if msg['chat']['id']!=uid: return
        self.s.display_name(uid,(cb['from'] if cb else msg['from']).get('first_name','Друг'))
        if cb:
            try: self.tg.call('answerCallbackQuery',callback_query_id=cb['id'])
            except APIError: pass
        now=time.monotonic()
        if now-self.limits.get(uid,0)<0.25: return
        self.limits[uid]=now
        if len(self.limits)>10000: self.limits={k:v for k,v in self.limits.items() if now-v<120}
        try:
            if cb: self.callback(uid,cb.get('data',''))
            elif 'text' in msg: self.message(uid,msg['text'].strip())
        except (ShopError,ValueError) as exc:
            text=str(exc) if isinstance(exc,ShopError) else 'Неверный ввод. Начни с /start.'
            self.tg.send(uid,escaped(text))

    def reconcile(self):
        for o in self.s.due():
            try: self.engine.check(o['id'])
            except Exception as exc:
                self.engine.retry_later(o['id'],type(exc).__name__)
                log.warning('order=%s reconcile=%s',o['id'],type(exc).__name__)
        for o in self.s.unsent_invoices()+self.s.undelivered():
            if time.time()-self.last_delivery.get(o['id'],0)<120: continue
            self.last_delivery[o['id']]=time.time()
            try: self.show_order(o['user_id'],o)
            except APIError: pass
        # Alert admins once when payment is stuck or invoice requires review.
        for row in self.s.db.execute("SELECT * FROM orders WHERE notified=0 AND (status='review' OR (attempts>=3 AND status IN ('paid','provisioning'))) LIMIT 5").fetchall():
            o=dict(row)
            try:
                for admin in self.cfg['telegram']['admins']:
                    self.tg.send(admin,'Нужна проверка заказа <code>'+o['id']+'</code>.\nСтатус: '+o['status']+'\nДанные: vpnshop order '+o['id'])
                self.s.patch(o['id'],notified=1)
            except APIError: pass

    def loop(self):
        offset=int(self.s.meta('offset'))
        last_check=0
        while self.running:
            try:
                updates=self.tg.call('getUpdates',offset=offset,timeout=5,limit=20,allowed_updates=['message','callback_query'])
                for u in updates:
                    try: self.update(u)
                    except Exception as exc: log.error('update=%s error=%s',u['update_id'],type(exc).__name__)
                    # Financial mutations precede offset commit and are idempotent.
                    offset=u['update_id']+1
                    self.s.setmeta('offset',offset)
                if time.monotonic()-last_check>=10:
                    self.reconcile(); last_check=time.monotonic()
            except Exception as exc:
                log.error('worker error=%s',type(exc).__name__)
                time.sleep(5)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default='/etc/revpn-shop/config.json')
    parser.add_argument('--data',default='/var/lib/revpn-shop')
    parser.add_argument('action',nargs='?',default='run',choices=['run','check','order','retry','backup'])
    parser.add_argument('value',nargs='?')
    args=parser.parse_args()
    cfg=load_config(args.config)
    root=Path(args.data); root.mkdir(parents=True,exist_ok=True)
    os.umask(0o077)
    # Administrative recovery must run with the service stopped.
    lock=(root/'worker.lock').open('a')
    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: raise ShopError('Сначала останови сервис: systemctl stop revpn-shop')
    store=Store(root/'shop.sqlite3')
    if args.action=='backup':
        if not args.value: raise ShopError('Укажи путь для резервной копии.')
        store.backup(args.value); print('Резервная копия создана.'); return
    if args.action=='order':
        o=store.get(args.value)
        print(json.dumps({k:v for k,v in o.items() if k not in ('uuid','sub_id','link','invoice_url')},ensure_ascii=False,indent=2)); return
    if args.action=='retry':
        o=store.get(args.value)
        if o['status']=='review': raise ShopError('Платёж не прошёл проверку. Автоматическое снятие review запрещено; проверь реквизиты.')
        store.patch(o['id'],next_check=0,attempts=0,error=None,notified=0)
        print('Повторная проверка назначена. Запусти сервис.'); return
    tg=Telegram(cfg['telegram']['token'])
    me=tg.call('getMe'); bot_name=me['username']
    webhook=tg.call('getWebhookInfo')
    if webhook.get('url'): raise ShopError('На боте настроен webhook. Используй отдельного бота или сначала отключи старый webhook.')
    payment=Lolz(cfg['lolz'],bot_name)
    if args.action=='check':
        panel=Panel(cfg['panel']); inbound=panel.inbound()
        panel.link({'uuid':'00000000-0000-4000-8000-000000000001','id':'preflight'},inbound)
        # Explicit diagnostics only: provider outages must not block the menu.
        payment.http.call('invoice/list',query={'page':1})
        print('Проверено: Telegram @'+bot_name+', API Lolz, VLESS inbound '+str(cfg['panel']['inbound_id']),flush=True)
        return
    print('Запущен Telegram @'+bot_name+'. Платежи проверяются при обработке заказов.',flush=True)
    engine=Engine(store,payment,Delivery(cfg,store,root),cfg)
    bot=Bot(cfg,store,tg,engine)
    def stop(*_): bot.running=False
    signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
    bot.loop()

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    try: main()
    except Exception as exc:
        # Trusted local config errors may be descriptive; provider errors are sanitized.
        print(str(exc) if isinstance(exc,ShopError) else 'Ошибка запуска: '+type(exc).__name__,file=sys.stderr)
        sys.exit(1)
