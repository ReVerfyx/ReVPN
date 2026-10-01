import unittest

from delivery import OPERATORS, targets
from whitelist_sources import SOURCES


class MobileProfileTests(unittest.TestCase):
    def test_default_operator_catalog_includes_virtual_and_major_carriers(self):
        for key in ('mts','megafon','beeline','t2','yota','tmobile','sber','alfa','rostelecom'):
            self.assertIn(key,OPERATORS)

    def test_operator_specific_nodes_override_generic_whitelist_set(self):
        cfg={
            'supported_operators':['mts'],
            'subscription':{'public_base':'https://revpn.work.gd'},
            'operator_nodes':{'mts':['mts_mobile']},
            'nodes':{
                'regular':{'enabled':True},
                'mts_mobile':{'enabled':True},
                'max':{'enabled':False},
                'yandex':{'enabled':False},
                'disk':{'enabled':False},
                'vk':{'enabled':False},
                'vkvideo':{'enabled':False},
            },
        }
        self.assertEqual(targets(cfg,'whitelist','mts'),['mts_mobile'])
        self.assertEqual(targets(cfg,'bundle','mts'),['regular','mts_mobile'])

    def test_whitelist_reference_sources_are_https_and_do_not_import_proxy_keys(self):
        self.assertEqual(set(SOURCES),{'sni','cidr','domains'})
        for url in SOURCES.values():
            self.assertTrue(url.startswith('https://raw.githubusercontent.com/'))
            self.assertNotIn('Vless-Reality-White-Lists-Rus-Mobile',url)


if __name__=='__main__':
    unittest.main()
