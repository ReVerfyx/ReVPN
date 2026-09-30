import copy
import json
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from core import Store, Engine, ShopError, price
from bot import Bot
from providers import Telegram, APIError
from test_shop import FakePayment, FakePanel

class TG:
    def __init__(self): self.messages=[]
    def send(self,uid,text,buttons=None): self.messages.append((uid,text,buttons)); return {}

class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.cfg=json.loads(Path('config.example.json').read_text())
        self.cfg['lolz']['test']=False
        self.s=Store(':memory:'); self.tg=TG(); self.pay=FakePayment()
        self.e=Engine(self.s,self.pay,FakePanel(),self.cfg)
        self.b=Bot(self.cfg,self.s,self.tg,self.e)
        self.q=self.s.quote(1,720,0,5000)
    def tearDown(self): self.s.db.close()
    def test_progress_before_provider_and_full_url(self):
        original=self.pay.ensure_invoice
        def create(o):
            self.assertIn('Создаём ссылку',self.tg.messages[-1][1])
            return original(o)
        with patch.object(self.pay,'ensure_invoice',side_effect=create): self.b.callback(1,'confirm:'+self.q)
        self.assertIn('https://lzt.market/invoice/123/',self.tg.messages[-1][1])
        self.assertEqual(self.s.mine(1)[0]['invoice_sent'],1)
    def test_creation_does_not_wait_for_second_get(self):
        with patch.object(self.pay,'get_invoice',side_effect=AssertionError('extra request')):
            self.b.callback(1,'confirm:'+self.q)
        self.assertEqual(self.s.mine(1)[0]['status'],'pending')
    def test_background_creation_sends_link_after_failure(self):
        with patch.object(self.pay,'ensure_invoice',side_effect=APIError('LZT',503)):
            self.b.callback(1,'confirm:'+self.q)
        self.assertIn('пока не вернул ссылку',self.tg.messages[-1][1])
        o=self.s.mine(1)[0]; self.s.patch(o['id'],next_check=0)
        self.b.reconcile()
        self.assertIn('https://lzt.market/invoice/123/',self.tg.messages[-1][1])
        n=len(self.tg.messages); self.b.reconcile(); self.assertEqual(len(self.tg.messages),n)
    def test_failed_telegram_delivery_keeps_link_for_retry(self):
        o=self.s.order(self.q,1); self.e.check(o['id'])
        with patch.object(self.tg,'send',side_effect=APIError('Telegram')): self.b.reconcile()
        self.assertEqual(self.s.get(o['id'])['invoice_sent'],0)
        self.b.last_delivery.clear(); self.b.reconcile()
        self.assertEqual(self.s.get(o['id'])['invoice_sent'],1)
    def test_stale_tariff_button_does_not_change_price(self):
        self.b.product(1,'regular'); self.b.durations(1,100)
        old=self.tg.messages[-1][2][0][0]['callback_data']
        self.b.product(1,'regular'); self.b.durations(1,0)
        with self.assertRaises(ShopError): self.b.callback(1,old)
        self.assertEqual(self.s.db.execute('select count(*) from quotes').fetchone()[0],1)
    def test_menu_and_quote_use_config_prices(self):
        self.cfg['pricing']['unlimited_30d_rub']=77
        self.b.catalog(1); self.assertIn('77 ₽',str(self.tg.messages[-1][2]))
        self.b.product(1,'regular'); self.b.durations(1,0)
        key=self.tg.messages[-1][2][4][0]['callback_data'];self.b.callback(1,key)
        self.assertIn('77 ₽',self.tg.messages[-1][1])
        q=self.s.db.execute('select amount from quotes where id!=?',(self.q,)).fetchone()
        self.assertEqual(q[0],7700)
    def test_product_prices(self):
        for key,rub in [('regular',50),('whitelist',100),('bundle',150),('mtproto',25)]:
            self.assertEqual(price(self.cfg['pricing'],720,0,key),rub*100)
    def test_admin_menu_and_callbacks_are_restricted(self):
        self.b.home(1)
        self.assertNotIn('Админ-панель',str(self.tg.messages[-1]))
        count=len(self.tg.messages)
        for action in ('panel','admin:issue','admin:revoke','admin:key:vpn','admin:key:proxy','panel:stats'):
            self.b.callback(1,action)
        self.assertEqual(len(self.tg.messages),count)
        self.b.home(716962014)
        self.assertIn('Админ-панель',str(self.tg.messages[-1]))

    def test_proxy_domain_preserves_access(self):
        from delivery import proxy_link
        from urllib.parse import urlsplit,parse_qs
        self.cfg['mtproto']['public_host']='2.26.85.86'
        for kind in ('paid','free'):
            link=proxy_link(self.cfg,'a'*32,kind)
            q=parse_qs(urlsplit(link).query)
            self.assertEqual(q['server'],['revpn.work.gd'])
            expected=('dd'+'a'*32) if kind=='paid' else ('ee'+'a'*32+'revpn.work.gd'.encode().hex())
            self.assertEqual(q['secret'],[expected])
            self.assertEqual(q['port'],[str(self.cfg['mtproto'][kind]['port'])])

    def test_cancel_admin_prompt(self):
        self.b.admin_target_prompt(716962014,'issue')
        self.b.message(716962014,'/cancel')
        self.assertEqual(self.s.state(716962014),{})

    def test_copy_allowed(self):
        tg=Telegram('123:test')
        with patch.object(tg,'call',return_value={}) as call:
            tg.send(1,'copy me')
            self.assertFalse(call.call_args.kwargs.get('protect_content',False))
    def test_repeat_confirm_keeps_same_invoice(self):
        self.b.callback(1,'confirm:'+self.q);self.b.callback(1,'confirm:'+self.q)
        self.assertEqual(self.pay.created,1)


class AdminAccessTests(CheckoutTests):
    def test_commands_are_silent_for_config_admin_outside_allowlist(self):
        self.cfg['telegram']['admins']=[1]
        self.s.state(1,{'step':'gb'})
        for command in ('/admin','/admin@ReversVPNbot','/panel','/vpn_panelka','/ADMIN ignored'):
            self.b.message(1,command)
        self.assertEqual(self.tg.messages,[])

    def test_direct_mutations_reject_unauthorized_actor(self):
        before=self.s.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        with patch.object(self.e.panel,'ensure',side_effect=AssertionError('must not provision')):
            self.b.admin_issue(1,'regular',2)
            self.b.admin_revoke(1,2)
        self.assertEqual(self.s.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0],before)
        self.assertEqual(self.tg.messages,[])

    def test_admin_aliases_open_panel_for_both_owners(self):
        for uid in (716962014,8319283756):
            for command in ('/admin','/panel','/vpn_panelka@ReversVPNbot'):
                self.b.message(uid,command)
                self.assertIn('Создать ключ VPN',str(self.tg.messages[-1]))

class PublicWebTests(unittest.TestCase):
    def test_pages_work_without_order_database(self):
        import threading
        import urllib.request
        from http.server import HTTPServer
        from subscriptions import handler
        cfg=json.loads(Path('config.example.json').read_text())
        cfg['pricing']['unlimited_30d_rub']=77
        server=HTTPServer(('127.0.0.1',0),handler(Path('/nonexistent/orders.sqlite'),'https://revpn.work.gd','@ReversVPNsupport',cfg))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for route in ('/privacy','/app'):
                with opener.open('http://127.0.0.1:'+str(server.server_port)+route) as response:
                    text=response.read().decode()
                    self.assertEqual(response.status,200)
                    self.assertNotIn(cfg['telegram']['token'],text)
                    self.assertIn('Политика конфиденциальности',text)
                    if route=='/app':
                        self.assertIn('77 ₽',text)
                        self.assertIn('?start=app_regular',text)
                        self.assertIn('https://telegram.org',response.headers['Content-Security-Policy'])
                        self.assertIn('id="app-loader"',text)
                        self.assertIn('EVENT HUB',text)
                        self.assertIn('event-previews',text)
                        self.assertIn('loader-track',text)
                        self.assertIn('reward-pop',text)
                        self.assertIn('Доступные ивенты',text)
        finally:
            server.shutdown();thread.join();server.server_close()
