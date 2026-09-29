"""HTTP contract smoke test against a local fake, without real tokens/payments."""
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
import unittest
from providers import HTTP,Lolz,APIError

class HTTPTests(unittest.TestCase):
    def test_invoice_timeout_recovery_and_request_contract(self):
        class Handler(BaseHTTPRequestHandler):
            invoice=None
            posts=0
            def log_message(self,*args): pass
            def respond(self,status,data):
                self.send_response(status); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(json.dumps(data).encode())
            def do_GET(self):
                if not self.path.startswith('/invoice?'): return self.respond(404,{})
                if Handler.invoice is None: return self.respond(404,{})
                self.respond(200,{'invoice':Handler.invoice})
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert self.headers['Authorization']=='Bearer TEST_ONLY'
                assert body['currency']=='rub' and body['amount']==50 and body['merchant_id']==17
                assert body['url_success']=='https://t.me/TestBot?start=order_abc'
                Handler.posts+=1
                Handler.invoice={'invoice_id':1,'merchant_id':17,'payment_id':'abc','amount':5000,
                    'additional_data':body['additional_data'],'is_test':False,'expires_at':9999999999,
                    'url':'https://lzt.market/invoice/1/','status':'not_paid','paid_date':0}
                # Simulate provider committing the invoice but returning an error.
                self.respond(503,{})
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            p=Lolz({'token':'TEST_ONLY','merchant_id':17,'test':False,'invoice_lifetime':3600},'TestBot')
            p.http=HTTP('test','http://127.0.0.1:'+str(server.server_port),'TEST_ONLY')
            o={'id':'abc','amount':5000,'hours':720,'gb':0,'invoice_id':None}
            invoice=p.ensure_invoice(o);p.validate(invoice,o)
            self.assertEqual(invoice['invoice_id'],1)
            p.ensure_invoice(o)
            self.assertEqual(Handler.posts,1)
        finally: server.shutdown();server.server_close();thread.join()

if __name__=='__main__': unittest.main()
