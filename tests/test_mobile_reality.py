import unittest

from mobile_reality import reality_stream


class MobileRealityTests(unittest.TestCase):
    def test_reality_stream_uses_tcp_reality_and_matching_sni(self):
        s=reality_stream('PRIVATE','PUBLIC','ya.ru','aabbccdd')
        self.assertEqual(s['network'],'tcp')
        self.assertEqual(s['security'],'reality')
        r=s['realitySettings']
        self.assertEqual(r['dest'],'ya.ru:443')
        self.assertEqual(r['serverNames'],['ya.ru'])
        self.assertEqual(r['shortIds'],['aabbccdd'])
        self.assertEqual(r['privateKey'],'PRIVATE')
        self.assertEqual(r['settings']['publicKey'],'PUBLIC')
        self.assertEqual(r['settings']['fingerprint'],'chrome')
        self.assertEqual(r['settings']['serverName'],'ya.ru')

    def test_reality_stream_does_not_embed_public_key_as_private(self):
        s=reality_stream('PRIV','PUB','example.org','01234567')
        self.assertNotEqual(s['realitySettings']['privateKey'],s['realitySettings']['settings']['publicKey'])


if __name__=='__main__':
    unittest.main()
