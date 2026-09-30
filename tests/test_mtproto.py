import pathlib
import tempfile
import unittest

from core import Store
from mtproto_service import paid_snapshot, paid_users
from delivery import proxy_link


class MTProtoPerOrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.temp.name) / 'shop.sqlite3'
        self.store = Store(self.path)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_each_order_gets_its_own_secret(self):
        first = self.store.get(self.store.create_manual_order(1001, 'mtproto', 1, []))
        second = self.store.get(self.store.create_manual_order(1001, 'mtproto', 1, []))

        users = paid_users(self.store.db, first['created'])
        self.assertIn(first['id'], users)
        self.assertIn(second['id'], users)
        self.assertEqual(len(users[first['id']]), 32)
        self.assertEqual(len(users[second['id']]), 32)
        self.assertNotEqual(users[first['id']], users[second['id']])

    def test_one_hour_order_has_one_hour_deadline(self):
        order = self.store.get(self.store.create_manual_order(1002, 'mtproto', 1, []))
        self.assertEqual(order['expiry_ms'] - order['created'] * 1000, 3_600_000)

    def test_secret_disappears_at_expiry_boundary(self):
        order = self.store.get(self.store.create_manual_order(1003, 'mtproto', 1, []))
        expires = order['expiry_ms'] / 1000

        self.assertIn(order['id'], paid_users(self.store.db, expires - 0.001))
        self.assertNotIn(order['id'], paid_users(self.store.db, expires))

    def test_nearest_expiry_is_exposed_for_precise_wakeup(self):
        first = self.store.get(self.store.create_manual_order(1004, 'mtproto', 1, []))
        second = self.store.get(self.store.create_manual_order(1005, 'mtproto', 6, []))
        users, next_expiry = paid_snapshot(self.store.db, first['created'])

        self.assertEqual(set(users), {first['id'], second['id']})
        self.assertEqual(next_expiry, first['expiry_ms'] / 1000)

    def test_free_proxy_link_uses_faketls_by_default(self):
        cfg = {
            'mtproto': {
                'public_host': 'revpn.work.gd',
                'paid': {'port': 2443},
                'free': {'port': 3443},
            }
        }
        link = proxy_link(cfg, '7dc753450bf32b1a213ea71ff0b02abf', 'free')
        self.assertIn('port=3443', link)
        self.assertIn(
            'secret=ee7dc753450bf32b1a213ea71ff0b02abf726576706e2e776f726b2e6764',
            link,
        )

    def test_paid_proxy_link_uses_faketls_on_shared_443(self):
        cfg = {
            'mtproto': {
                'public_host': 'revpn.work.gd',
                'paid': {
                    'port': 2443,
                    'public_port': 443,
                    'transport': 'fake_tls',
                    'tls_domain': 'www.microsoft.com',
                },
                'free': {'port': 3443},
            }
        }
        link = proxy_link(cfg, '0123456789abcdef0123456789abcdef', 'paid')
        self.assertIn('port=443', link)
        self.assertIn(
            'secret=ee0123456789abcdef0123456789abcdef7777772e6d6963726f736f66742e636f6d',
            link,
        )


if __name__ == '__main__':
    unittest.main()
