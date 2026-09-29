import contextlib
import copy
import io
import json
import pathlib
import tempfile
import time
import unittest
from unittest.mock import patch

from core import Store,Engine,ShopError,price
from providers import Lolz,Panel,APIError
from bot import Bot

PRICING={'unlimited_30d_rub':50,'limited_base_30d_rub':20,'per_gb_rub':'0.05','minimum_rub':1,'max_hours':8760,'max_gb':100000}
CFG={'pricing':PRICING,'lolz':{'test':False},'telegram':{'admins':[1],'support':'@support'}}

class FakePayment:
    def __init__(self):
        self.cfg={'merchant_id':17,'test':False,'token':'test'}
        self.invoice=None
        self.created=0
        self.validator=Lolz(self.cfg,'TestBot')
    def ensure_invoice(self,o):
        if self.invoice is None:
            self.created+=1
            self.invoice={'invoice_id':123,'merchant_id':17,'payment_id':o['id'],'amount':o['amount'],
                'additional_data':Lolz.metadata(o),'is_test':False,'expires_at':int(time.time())+3600,
                'url':'https://lzt.market/invoice/123/','status':'not_paid','paid_date':0}
        return self.invoice.copy()
    def get_invoice(self,o): return self.invoice.copy()
    def validate(self,*a,**kw): return self.validator.validate(*a,**kw)
    def pay(self): self.invoice.update(status='paid',paid_date=int(time.time()))

class FakePanel:
    def __init__(self): self.clients={}; self.writes=0; self.fail_after_write=False
    def exists(self,o): return o['uuid'] in self.clients
    def ensure(self,o):
        if not self.exists(o):
            self.clients[o['uuid']]=o.copy(); self.writes+=1
            if self.fail_after_write:
                self.fail_after_write=False
                raise APIError('simulated lost response')
        assert self.clients[o['uuid']]['expiry_ms']==o['expiry_ms']
        return 'vless://'+o['uuid']+'@192.0.2.1:21146?security=none&type=tcp'

class ShopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=pathlib.Path(self.temp.name)/'db'
        self.s=Store(self.path); self.pay=FakePayment(); self.panel=FakePanel()
        self.e=Engine(self.s,self.pay,self.panel,CFG)
        self.q=self.s.quote(1,720,0,5000)
        self.o=self.s.order(self.q,1)
    def tearDown(self): self.s.db.close(); self.temp.cleanup()
    def test_price_month(self): self.assertEqual(price(PRICING,720,0),5000)
    def test_price_hour(self): self.assertEqual(price(PRICING,1,0),100)
    def test_price_limited(self):
        self.assertEqual(price(PRICING,720,100),2500)
        self.assertEqual(price(PRICING,720,500),4500)
    def test_bad_input(self):
        for h,g in [(0,0),(-1,0),(1,-1),(True,1),(8761,0),(1,100001)]:
            with self.assertRaises(ShopError): price(PRICING,h,g)
    def test_repeat_confirmation_same_order(self):
        self.assertEqual(self.s.order(self.q,1)['id'],self.o['id'])
        self.assertEqual(self.s.db.execute('select count(*) from orders').fetchone()[0],1)
    def test_other_user_quote_and_order(self):
        with self.assertRaises(ShopError): self.s.order(self.q,2)
        with self.assertRaises(ShopError): self.s.get(self.o['id'],2)
    def test_pending_no_access(self):
        self.e.check(self.o['id']); self.assertEqual(self.panel.writes,0)
    def test_paid_and_repeat_once(self):
        self.e.check(self.o['id']); self.pay.pay()
        self.e.check(self.o['id']); self.e.check(self.o['id'])
        self.assertEqual(self.panel.writes,1)
        self.assertEqual(self.s.get(self.o['id'])['status'],'active')
    def test_panel_timeout_after_write(self):
        self.e.check(self.o['id']); self.pay.pay(); self.panel.fail_after_write=True
        with self.assertRaises(APIError): self.e.check(self.o['id'])
        expiry=self.s.get(self.o['id'])['expiry_ms']
        self.e.check(self.o['id'])
        self.assertEqual(self.panel.writes,1)
        self.assertEqual(self.s.get(self.o['id'])['expiry_ms'],expiry)
    def test_crash_restart_keeps_order(self):
        self.e.check(self.o['id']); self.s.db.close(); self.s=Store(self.path)
        self.e=Engine(self.s,self.pay,self.panel,CFG); self.pay.pay(); self.e.check(self.o['id'])
        self.assertEqual(self.panel.writes,1)
    def test_wrong_amount(self):
        self.e.check(self.o['id']); self.pay.pay(); self.pay.invoice['amount']-=1
        with self.assertRaises(ShopError): self.e.check(self.o['id'])
        self.assertEqual(self.panel.writes,0); self.assertEqual(self.s.get(self.o['id'])['status'],'review')
    def test_wrong_merchant(self):
        self.e.check(self.o['id']); self.pay.pay(); self.pay.invoice['merchant_id']=999
        with self.assertRaises(ShopError): self.e.check(self.o['id'])
        self.assertEqual(self.panel.writes,0)
    def test_wrong_invoice(self):
        self.e.check(self.o['id']); self.pay.pay(); self.pay.invoice['invoice_id']=999
        with self.assertRaises(ShopError): self.e.check(self.o['id'])
    def test_wrong_payment_id(self):
        self.e.check(self.o['id']); self.pay.pay(); self.pay.invoice['payment_id']='other'
        with self.assertRaises(ShopError): self.e.check(self.o['id'])
    def test_wrong_currency(self):
        self.e.check(self.o['id']); self.pay.pay(); self.pay.invoice['currency']='usd'
        with self.assertRaises(ShopError): self.e.check(self.o['id'])
    def test_metadata_tamper(self):
        self.e.check(self.o['id']); self.pay.pay(); self.pay.invoice['additional_data']='{}'
        with self.assertRaises(ShopError): self.e.check(self.o['id'])
    def test_test_invoice_rejected_in_live(self):
        self.e.check(self.o['id']); self.pay.pay(); self.pay.invoice['is_test']=True
        with self.assertRaises(ShopError): self.e.check(self.o['id'])
        self.assertEqual(self.panel.writes,0)
    def test_test_paid_never_provisions(self):
        self.pay.cfg['test']=True; self.pay.ensure_invoice(self.o); self.pay.invoice['is_test']=True
        cfg=copy.deepcopy(CFG); cfg['lolz']['test']=True; self.e=Engine(self.s,self.pay,self.panel,cfg)
        self.e.check(self.o['id']); self.pay.pay(); self.e.check(self.o['id'])
        self.assertEqual(self.s.get(self.o['id'])['status'],'test_paid'); self.assertEqual(self.panel.writes,0)
    def test_late_confirmation_of_paid_invoice(self):
        self.e.check(self.o['id']); self.s.patch(self.o['id'],status='expired')
        self.pay.pay(); self.e.check(self.o['id']); self.assertEqual(self.panel.writes,1)
    def test_expired_never_paid_no_access(self):
        self.e.check(self.o['id']); self.s.patch(self.o['id'],invoice_expiry=1)
        self.e.check(self.o['id']); self.assertEqual(self.panel.writes,0)
        self.assertEqual(self.s.get(self.o['id'])['status'],'expired')
    def test_limit_three_pending(self):
        for _ in range(2): self.s.order(self.s.quote(1,1,0,100),1)
        with self.assertRaises(ShopError): self.s.order(self.s.quote(1,1,0,100),1)
    def test_quote_expiry(self):
        q=self.s.quote(1,1,0,100); self.s.db.execute('update quotes set created=0 where id=?',(q,))
        with self.assertRaises(ShopError): self.s.order(q,1)
    def test_no_fake_payment_from_start_link(self):
        class TG:
            def send(self,*a,**k): pass
        b=Bot(CFG,self.s,TG(),self.e)
        b.message(1,'/start order_'+self.o['id'])
        self.assertEqual(self.panel.writes,0)
    def test_new_expiry_if_previous_attempt_never_created(self):
        self.e.check(self.o['id']); self.pay.pay()
        self.s.patch(self.o['id'],status='provisioning',expiry_ms=1)
        self.e.check(self.o['id'])
        self.assertGreater(self.s.get(self.o['id'])['expiry_ms'],int(time.time()*1000))

class PanelTests(unittest.TestCase):
    def setUp(self):
        self.panel=Panel({'url':'http://127.0.0.1:8080','token':'test','inbound_id':1,'public_host':'vpn.example.org'})
        self.o={'id':'abc','uuid':'00000000-0000-4000-8000-000000000001','email':'shop-abc','sub_id':'secret','gb':100,'user_id':1,'expiry_ms':int(time.time()+3600)*1000}
        self.inbound={'id':1,'protocol':'vless','enable':True,'total':0,'expiryTime':0,'port':21146,
            'settings':{'clients':[],'decryption':'none'},'streamSettings':{'network':'tcp','security':'none'}}
    def fake_request(self,path,method='GET',data=None,form=False):
        if path.startswith('panel/api/inbounds/get/'): return self.inbound
        if path=='panel/api/clients/add':
            self.assertEqual(data['inboundIds'],[1]); self.inbound['settings']['clients'].append(data['client']); return None
        raise AssertionError(path)
    def test_modern_api_and_link(self):
        with patch.object(self.panel,'request',side_effect=self.fake_request):
            link=self.panel.ensure(self.o)
            self.assertIn('@vpn.example.org:21146',link)
            self.assertEqual(self.inbound['settings']['clients'][0]['totalGB'],100*1024**3)
            self.panel.ensure(self.o)
            self.assertEqual(len(self.inbound['settings']['clients']),1)
    def test_legacy_api(self):
        def legacy(path,method='GET',data=None,form=False):
            if path=='panel/api/clients/add': raise APIError('panel',404)
            if path=='panel/api/inbounds/addClient':
                self.assertTrue(form); self.inbound['settings']['clients'].extend(json.loads(data['settings'])['clients']); return None
            return self.fake_request(path,method,data,form)
        with patch.object(self.panel,'request',side_effect=legacy): self.panel.ensure(self.o)
    def test_no_fallback_on_500(self):
        def broken(path,method='GET',data=None,form=False):
            if path=='panel/api/clients/add': raise APIError('panel',500)
            return self.fake_request(path,method,data,form)
        with patch.object(self.panel,'request',side_effect=broken):
            with self.assertRaises(APIError): self.panel.ensure(self.o)
    def test_reality_exports_public_only(self):
        self.inbound['streamSettings'].update(security='reality',realitySettings={'privateKey':'PRIVATE_DO_NOT_EXPORT','shortIds':['abcd'],'serverNames':['example.org'],'settings':{'publicKey':'PUBLIC'}})
        link=self.panel.link(self.o,self.inbound)
        self.assertIn('pbk=PUBLIC',link); self.assertNotIn('PRIVATE',link)
    def test_shared_limit_rejected(self):
        self.inbound['total']=1
        with self.assertRaises(ShopError): self.panel.validate_inbound(self.inbound)

if __name__=='__main__': unittest.main()
