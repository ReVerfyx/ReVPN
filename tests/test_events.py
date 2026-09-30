"""Tests for Telegram Mini App event rewards."""
import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from events import (
    EVENT_CYCLE_SECONDS, EventAuthError, EventService,
    event_clock, event_definition, validate_init_data,
)


TOKEN="123456:TEST_TOKEN"


def init_data(uid, now):
    fields={
        "auth_date":str(int(now)),
        "query_id":"AAE-test",
        "user":json.dumps({"id":uid,"first_name":"Tester"},separators=(",",":")),
    }
    check="\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret=hmac.new(b"WebAppData",TOKEN.encode(),hashlib.sha256).digest()
    fields["hash"]=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    return urlencode(fields)


class FakeDelivery:
    def __init__(self,cfg,store,data):
        self.store=store
        self.base=cfg["subscription"]["public_base"].rstrip("/")

    def sync_expiry(self,o):
        link="vless://event-test#ReVPN"
        self.store.db.execute(
            """INSERT INTO allocations(order_id,node_id,link,quota)
               VALUES(?,?,?,0)
               ON CONFLICT(order_id,node_id) DO UPDATE SET link=excluded.link""",
            (o["id"],"regular",link),
        )
        return self.base+"/sub/"+o["sub_id"]


class EventTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"shop.sqlite3"
        self.cfg={
            "telegram":{"token":TOKEN},
            "subscription":{"public_base":"https://revpn.example"},
        }
        self.service=EventService(self.db,self.cfg,self.tmp.name,delivery_factory=FakeDelivery)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_catalog_has_1000_unique_buttons(self):
        buttons={event_definition(i)["button"] for i in range(1000)}
        self.assertEqual(len(buttons),1000)

    def test_clock_is_one_hour_then_ten_minute_break(self):
        base=123*EVENT_CYCLE_SECONDS
        active=event_clock(base+3599)
        self.assertTrue(active["active"])
        self.assertEqual(active["seconds_left"],1)
        pause=event_clock(base+3600)
        self.assertFalse(pause["active"])
        self.assertEqual(pause["seconds_left"],600)
        nxt=event_clock(base+EVENT_CYCLE_SECONDS)
        self.assertNotEqual(active["event_id"],nxt["event_id"])

    def test_init_data_signature_and_tamper(self):
        now=2_000_000_000
        data=init_data(42,now)
        self.assertEqual(validate_init_data(data,TOKEN,now)[0],42)
        with self.assertRaises(EventAuthError):
            validate_init_data(data.replace("Tester","Hacker"),TOKEN,now)

    def test_tap_gives_exactly_one_second_and_rate_limit_rejects_fast_tap(self):
        now=2_000_000_000
        data=init_data(42,now)
        state=self.service.state(data,now)
        first=self.service.tap(data,state["clock"]["event_id"],state["user"]["nonce"],now+0.20)
        self.assertTrue(first["accepted"])
        self.assertEqual(first["user"]["balance_seconds"],1)
        second=self.service.tap(data,first["clock"]["event_id"],first["user"]["nonce"],now+0.25)
        self.assertFalse(second["accepted"])
        self.assertEqual(second["user"]["balance_seconds"],1)

    def test_claim_reuses_single_bonus_order(self):
        now=2_000_000_000
        data=init_data(77,now)
        state=self.service.state(data,now)
        t=now+0.20
        def earn(count):
            nonlocal state,t
            # Intentionally use a human-ish non-uniform rhythm. A perfectly
            # periodic 200 ms loop is exactly what the anti-autoclicker should reject.
            rhythm=(0.17,0.24,0.19,0.28,0.21,0.25,0.18,0.27)
            for i in range(count):
                challenge=state["user"].get("challenge")
                if challenge:
                    target=challenge["prompt"].rsplit(" ",1)[-1]
                    choice=next(o["id"] for o in challenge["options"] if o["label"]==target)
                    state=self.service.challenge(data,state["user"]["nonce"],choice,t)
                    t+=0.31
                state=self.service.tap(data,state["clock"]["event_id"],state["user"]["nonce"],t)
                self.assertTrue(state["accepted"],state.get("message"))
                t+=rhythm[i % len(rhythm)]
        earn(30)
        claimed=self.service.claim(data,t+0.20)
        self.assertEqual(claimed["user"]["balance_seconds"],0)
        self.assertIsNotNone(claimed["user"]["bonus"])
        first_order=self.service.db.execute(
            "SELECT bonus_order_id FROM event_users WHERE user_id=77"
        ).fetchone()[0]
        order=self.service.store.get(first_order,77)
        first_expiry=order["expiry_ms"]
        self.assertTrue(order["quote_id"].startswith("event-"))
        self.assertEqual(order["delivered"],1)
        self.assertEqual(
            self.service.db.execute("SELECT COUNT(*) FROM allocations WHERE order_id=?",(first_order,)).fetchone()[0],
            1,
        )

        # Earn another claim; the same order/client must be extended, not duplicated.
        state=self.service.state(data,t+1)
        t+=1.2
        earn(30)
        self.service.claim(data,t+0.20)
        second_order=self.service.db.execute(
            "SELECT bonus_order_id FROM event_users WHERE user_id=77"
        ).fetchone()[0]
        self.assertEqual(first_order,second_order)
        self.assertGreater(self.service.store.get(second_order,77)["expiry_ms"],first_expiry)


if __name__=="__main__":
    unittest.main()
