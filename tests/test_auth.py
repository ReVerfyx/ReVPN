import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from providers import Panel

class AuthTests(unittest.TestCase):
    def test_csrf_cookie_login_and_mutation(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a): pass
            def reply(self,obj,cookie=None):
                self.send_response(200)
                if cookie: self.send_header('Set-Cookie',cookie+'; Path=/secret/; HttpOnly')
                self.end_headers(); self.wfile.write(json.dumps(obj).encode())
            def do_GET(self):
                calls.append(self.path)
                if self.path!='/secret/csrf-token': self.send_error(404);return
                logged='session=logged' in self.headers.get('Cookie','')
                self.reply({'success':True,'obj':'after-login' if logged else 'before-login'},None if logged else 'session=initial')
            def do_POST(self):
                calls.append(self.path)
                self.rfile.read(int(self.headers.get('Content-Length',0)))
                login=self.path=='/secret/login'
                expected='before-login' if login else 'after-login'
                cookie='session=initial' if login else 'session=logged'
                if self.headers.get('X-CSRF-Token')!=expected or cookie not in self.headers.get('Cookie',''):
                    self.send_error(403);return
                self.reply({'success':True,'obj':'created'},'session=logged' if login else None)
        server=HTTPServer(('127.0.0.1',0),Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        try:
            p=Panel({'url':f'http://127.0.0.1:{server.server_port}/secret/','username':'root','password':'test-only'})
            self.assertEqual(p.request('panel/api/clients/add','POST',data={}), 'created')
            self.assertEqual(calls,['/secret/csrf-token','/secret/login','/secret/csrf-token','/secret/panel/api/clients/add'])
        finally: server.shutdown();server.server_close();t.join()
