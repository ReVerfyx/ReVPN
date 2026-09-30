import unittest

from edge443 import client_hello_sni
from edge443_setup import patch_text


def hello(host):
    name=host.encode()
    server_name=(len(name)+3).to_bytes(2,'big')+b'\x00'+len(name).to_bytes(2,'big')+name
    ext=b'\x00\x00'+len(server_name).to_bytes(2,'big')+server_name
    body=(
        b'\x03\x03'+b'R'*32+
        b'\x00'+
        b'\x00\x02\x13\x01'+
        b'\x01\x00'+
        len(ext).to_bytes(2,'big')+ext
    )
    hs=b'\x01'+len(body).to_bytes(3,'big')+body
    return b'\x16\x03\x01'+len(hs).to_bytes(2,'big')+hs


class Edge443Tests(unittest.TestCase):
    def test_extracts_sni(self):
        self.assertEqual(client_hello_sni(hello('www.cloudflare.com')),'www.cloudflare.com')
        self.assertEqual(client_hello_sni(hello('www.microsoft.com')),'www.microsoft.com')

    def test_nginx_tcp_listener_moves_but_quic_stays(self):
        source='''server {
    listen 443 ssl http2;
    listen [::]:443 ssl;
    listen 443 quic reuseport;
}
'''
        patched,changed=patch_text(source,4443)
        self.assertTrue(changed)
        self.assertIn('listen 127.0.0.1:4443 ssl http2;',patched)
        self.assertIn('listen [::1]:4443 ssl;',patched)
        self.assertIn('listen 443 quic reuseport;',patched)


if __name__=='__main__':
    unittest.main()
