"""Tests for Telegram Mini App event rewards and mini-games."""
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


def find_time(game=None,reward=None):
    base=2_000_000_000-(2_000_000_000 % EVENT_CYCLE_SECONDS)
    for i in range(1200):
        now=base+i*EVENT_CYCLE_SECONDS+20
        event=event_definition(event_clock(now)["event_id"])
        if game and event["game"]!=game:
            continue
        if reward and event["reward"]["kind"]!=reward:
            continue
        return float(now)
    raise AssertionError("matching event not found")


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

    def test_catalog_has_1000_unique_buttons_and_all_game_types(self):
        events=[event_definition(i) for i in range(1000)]
        self.assertEqual(len({e["button"] for e in events}),1000)
        self.assertEqual({e["game"] for e in events},{"tap_rush","snow_catch","reaction","ice_break"})
        self.assertEqual({e["reward"]["kind"] for e in events},{"seconds","rubles","mixed"})

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

    def test_seconds_event_gives_one_second_and_rate_limit_rejects_fast_action(self):
        now=find_time(game="tap_rush",reward="seconds")
        data=init_data(42,now)
        state=self.service.state(data,now)
        first=self.service.play(data,state["clock"]["event_id"],state["user"]["nonce"],now+0.20)
        self.assertTrue(first["accepted"])
        self.assertEqual(first["user"]["balance_seconds"],1)
        second=self.service.play(data,first["clock"]["event_id"],first["user"]["nonce"],now+0.25)
        self.assertFalse(second["accepted"])
        self.assertEqual(second["user"]["balance_seconds"],1)

    def test_ruble_event_credits_bonus_wallet(self):
        now=find_time(game="snow_catch",reward="rubles")
        data=init_data(88,now)
        state=self.service.state(data,now)
        t=now+0.25
        for step in (0.21,0.27,0.19,0.31,0.23):
            state=self.service.play(data,state["clock"]["event_id"],state["user"]["nonce"],t)
            self.assertTrue(state["accepted"],state.get("message"))
            t+=step
        self.assertEqual(state["user"]["bonus_kopecks"],25)
        self.assertEqual(state["user"]["balance_seconds"],0)
        self.assertEqual(state["user"]["event_reward_kopecks"],25)

    def test_reaction_event_rejects_early_action(self):
        now=find_time(game="reaction")
        data=init_data(90,now)
        state=self.service.state(data,now)
        self.assertGreater(state["user"]["ready_in_ms"],0)
        early=self.service.play(data,state["clock"]["event_id"],state["user"]["nonce"],now+0.05)
        self.assertFalse(early["accepted"])
        ready=now+(state["user"]["ready_in_ms"]/1000)+0.05
        later=self.service.play(data,early["clock"]["event_id"],early["user"]["nonce"],ready)
        self.assertTrue(later["accepted"])

    def test_challenge_respects_cooldown(self):
        now=find_time(game="tap_rush")
        data=init_data(55,now)
        state=self.service.state(data,now)
        nonce=state["user"]["nonce"]
        self.service.db.execute(
            "UPDATE event_users SET challenge_answer=1,cooldown_until_ms=? WHERE user_id=55",
            (int((now+5)*1000),),
        )
        blocked=self.service.challenge(data,nonce,1,now+1)
        self.assertIsNotNone(blocked["user"]["challenge"])
        self.assertGreater(blocked["user"]["cooldown_ms"],0)
        passed=self.service.challenge(data,blocked["user"]["nonce"],1,now+6)
        self.assertIsNone(passed["user"]["challenge"])

    def test_claim_reuses_single_bonus_order(self):
        now=find_time(game="tap_rush",reward="seconds")
        data=init_data(77,now)
        state=self.service.state(data,now)
        t=now+0.20
        def earn(count):
            nonlocal state,t
            rhythm=(0.17,0.24,0.19,0.28,0.21,0.25,0.18,0.27)
            for i in range(count):
                challenge=state["user"].get("challenge")
                if challenge:
                    target=challenge["prompt"].rsplit(" ",1)[-1]
                    choice=next(o["id"] for o in challenge["options"] if o["label"]==target)
                    state=self.service.challenge(data,state["user"]["nonce"],choice,t)
                    t+=0.31
                state=self.service.play(data,state["clock"]["event_id"],state["user"]["nonce"],t)
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

class TrafficTests(unittest.TestCase):
    def test_usage_is_scoped_and_failed_sync_preserves_snapshot(self):
        from subscriptions import account_usage, sync_traffic
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            service=EventService(Path(tmp)/'db',{'telegram':{'token':TOKEN},'subscription':{'public_base':'https://example.org'}},tmp,delivery_factory=FakeDelivery)
            now=2_000_000_000
            try:
                oid=service.store.create_manual_order(7,'regular',24,['regular'])
                other=service.store.create_manual_order(8,'regular',24,['regular'])
                service.db.execute('UPDATE orders SET expiry_ms=?,gb=1',( (now+3600)*1000,))
                for order in (oid,other):
                    service.db.execute('INSERT INTO allocations(order_id,node_id,link,quota) VALUES(?,?,?,?)',(order,'regular','private-link',1024**3))
                result=account_usage(service,init_data(7,now),now)['subscriptions']
                self.assertEqual(len(result),1)
                self.assertIsNone(result[0]['used_bytes'])
                email=service.store.get(oid)['email']+'-regular'
                class Panel:
                    def inbound(self): return {'clientStats':[{'email':email,'up':100,'down':200}]}
                delivery=SimpleNamespace(s=service.store,panels={'regular':Panel()})
                sync_traffic(delivery,now)
                sub=account_usage(service,init_data(7,now),now)['subscriptions'][0]
                self.assertEqual(sub['used_bytes'],300)
                self.assertEqual(sub['remaining_bytes'],1024**3-300)
                self.assertFalse(sub['stale'])
                delivery.panels={}
                sync_traffic(delivery,now+200)
                sub=account_usage(service,init_data(7,now+200),now+200)['subscriptions'][0]
                self.assertEqual(sub['used_bytes'],300)
                self.assertTrue(sub['stale'])
                service.db.execute('UPDATE orders SET gb=0 WHERE id=?',(oid,))
                sub=account_usage(service,init_data(7,now),now)['subscriptions'][0]
                self.assertTrue(sub['unlimited'])
                self.assertIsNone(sub['remaining_bytes'])
                with self.assertRaises(EventAuthError): account_usage(service,'user=7',now)
            finally: service.close()

    def test_bundle_remaining_respects_each_node_quota(self):
        from subscriptions import account_usage
        with tempfile.TemporaryDirectory() as tmp:
            service=EventService(Path(tmp)/'db',{'telegram':{'token':TOKEN},'subscription':{'public_base':'https://example.org'}},tmp,delivery_factory=FakeDelivery)
            now=2_000_000_000
            try:
                oid=service.store.create_manual_order(7,'bundle',24,['regular','vk'])
                service.db.execute('UPDATE orders SET expiry_ms=?,gb=1 WHERE id=?',((now+3600)*1000,oid))
                for node,used in [('regular',150),('vk',20)]:
                    service.db.execute('INSERT INTO allocations(order_id,node_id,link,quota,upload,updated) VALUES(?,?,?,?,?,?)',(oid,node,'private',100,used,now))
                sub=account_usage(service,init_data(7,now),now)['subscriptions'][0]
                self.assertEqual(sub['used_bytes'],170)
                self.assertEqual(sub['remaining_bytes'],80)
                service.db.execute('UPDATE orders SET expiry_ms=? WHERE id=?',(now*1000,oid))
                self.assertEqual(account_usage(service,init_data(7,now),now)['subscriptions'],[])
            finally: service.close()
