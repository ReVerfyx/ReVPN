"""Persistent orders and pricing. All money is integer kopecks internally."""
import json
import math
import sqlite3
import time
import uuid
from decimal import Decimal, ROUND_CEILING

class ShopError(Exception):
    pass


def price(config, hours, gb, product="regular"):
    if type(hours) is not int or not 1 <= hours <= config['max_hours']:
        raise ShopError('Срок должен быть от 1 часа до %s часов.' % config['max_hours'])
    if type(gb) is not int or not 0 <= gb <= config['max_gb']:
        raise ShopError('Недопустимый объём трафика.')
    d = Decimal
    if product == 'mtproto':
        if gb: raise ShopError('MTProto продаётся по сроку, без пакетов ГБ.')
        rub = d(str(config.get('mtproto_30d_rub', 25))) * hours / 720
        return int(max(d(str(config['minimum_rub'])),rub).to_integral_value(rounding=ROUND_CEILING))*100
    if product not in ('regular','whitelist','bundle'): raise ShopError('Неизвестный тариф.')
    monthly = config['unlimited_30d_rub'] if product=='regular' else config.get(product+'_30d_rub',100 if product=='whitelist' else 150)
    if gb == 0:
        rub = d(str(monthly)) * hours / 720
    else:
        rub = (d(str(config['limited_base_30d_rub'])) + max(d(0), d(str(monthly))-d(str(config['unlimited_30d_rub'])))) * hours / 720 + d(str(config['per_gb_rub'])) * gb
    return int(max(d(str(config['minimum_rub'])), rub).to_integral_value(rounding=ROUND_CEILING))*100


def rubles(kopecks):
    return f'{kopecks//100}' if kopecks % 100 == 0 else f'{kopecks/100:.2f}'


def description(hours, gb):
    duration = f'{hours//24} дн.' if hours % 24 == 0 else f'{hours} ч.'
    return duration + ' / ' + ('безлимит' if gb == 0 else f'{gb} ГБ')


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,state TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS quotes(
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, hours INTEGER NOT NULL,
          gb INTEGER NOT NULL, amount INTEGER NOT NULL, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS orders(
          id TEXT PRIMARY KEY, quote_id TEXT NOT NULL UNIQUE, user_id INTEGER NOT NULL,
          hours INTEGER NOT NULL, gb INTEGER NOT NULL, amount INTEGER NOT NULL,
          status TEXT NOT NULL, created INTEGER NOT NULL, invoice_id INTEGER UNIQUE,
          invoice_url TEXT, provider_amount TEXT, invoice_expiry INTEGER,
          next_check INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
          uuid TEXT NOT NULL UNIQUE, sub_id TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE,
          expiry_ms INTEGER, link TEXT, delivered INTEGER NOT NULL DEFAULT 0,
          notified INTEGER NOT NULL DEFAULT 0, error TEXT);
        CREATE INDEX IF NOT EXISTS orders_poll ON orders(status,next_check);
        CREATE INDEX IF NOT EXISTS orders_owner ON orders(user_id,created);
        ''')

        # Additive migration from v1, keeping previously paid orders intact.
        for table, fields in {
            'users': {'display_name': "TEXT NOT NULL DEFAULT ''", 'bonus_kopecks': 'INTEGER NOT NULL DEFAULT 0'},
            'quotes': {'product': "TEXT NOT NULL DEFAULT 'regular'", 'operator': "TEXT NOT NULL DEFAULT ''", 'targets': "TEXT NOT NULL DEFAULT '[]'", 'base_amount': 'INTEGER NOT NULL DEFAULT 0', 'bonus_used': 'INTEGER NOT NULL DEFAULT 0'},
            'orders': {'product': "TEXT NOT NULL DEFAULT 'regular'", 'operator': "TEXT NOT NULL DEFAULT ''", 'targets': "TEXT NOT NULL DEFAULT '[]'", 'display_name': "TEXT NOT NULL DEFAULT ''", 'invoice_sent': 'INTEGER NOT NULL DEFAULT 0', 'migration_notified': 'INTEGER NOT NULL DEFAULT 0', 'base_amount': 'INTEGER NOT NULL DEFAULT 0', 'bonus_used': 'INTEGER NOT NULL DEFAULT 0'}
        }.items():
            existing={r[1] for r in self.db.execute('PRAGMA table_info('+table+')')}
            for key, typ in fields.items():
                if key not in existing: self.db.execute('ALTER TABLE '+table+' ADD COLUMN '+key+' '+typ)
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS allocations(order_id TEXT NOT NULL,node_id TEXT NOT NULL,
          link TEXT NOT NULL,quota INTEGER NOT NULL,upload INTEGER NOT NULL DEFAULT 0,
          download INTEGER NOT NULL DEFAULT 0,updated INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(order_id,node_id));
        CREATE TABLE IF NOT EXISTS mirrors(
          token TEXT PRIMARY KEY, owner_id INTEGER NOT NULL, created INTEGER NOT NULL,
          trial_order_ids TEXT NOT NULL DEFAULT '[]');
        CREATE TABLE IF NOT EXISTS trial_grants(
          user_id INTEGER PRIMARY KEY, created INTEGER NOT NULL, mirror_token TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS managed_bots(
          bot_id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL, username TEXT NOT NULL DEFAULT '',
          token TEXT NOT NULL, created INTEGER NOT NULL);
        """)

    def display_name(self, uid, name=None):
        if name is not None:
            self.db.execute("INSERT INTO users(id,state,display_name) VALUES(?,'{}',?) ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name",(uid,name[:80]))
        r=self.db.execute('SELECT display_name FROM users WHERE id=?',(uid,)).fetchone()
        return r[0] if r and r[0] else 'Друг'

    def get(self, oid, uid=None):
        r = self.db.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone()
        if r is None or (uid is not None and r['user_id'] != uid):
            raise ShopError('Заказ не найден.')
        return dict(r)

    def patch(self, oid, **values):
        allowed = {'status','invoice_id','invoice_url','provider_amount','invoice_expiry','next_check','attempts','expiry_ms','link','delivered','notified','error','invoice_sent','migration_notified'}
        assert values and set(values) <= allowed
        self.db.execute('UPDATE orders SET '+','.join(k+'=?' for k in values)+' WHERE id=?', (*values.values(),oid))

    def meta(self, key, default='0'):
        r = self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return r[0] if r else default

    def setmeta(self, key, value):
        self.db.execute('INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,str(value)))

    def state(self, uid, value=None):
        if value is not None:
            self.db.execute('INSERT INTO users(id,state) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state',(uid,json.dumps(value)))
            return value
        r = self.db.execute('SELECT state FROM users WHERE id=?',(uid,)).fetchone()
        return json.loads(r[0]) if r else {}

    def _release_stale_bonus_locked(self, uid):
        cutoff=int(time.time())-900
        rows=self.db.execute(
            """SELECT q.id,q.bonus_used FROM quotes q
               LEFT JOIN orders o ON o.quote_id=q.id
               WHERE q.user_id=? AND q.created<? AND q.bonus_used>0 AND o.id IS NULL""",
            (uid,cutoff),
        ).fetchall()
        amount=sum(int(r['bonus_used']) for r in rows)
        if amount:
            self.db.execute("INSERT INTO users(id,state,bonus_kopecks) VALUES(?,'{}',?) ON CONFLICT(id) DO UPDATE SET bonus_kopecks=bonus_kopecks+excluded.bonus_kopecks",(uid,amount))
            self.db.executemany('UPDATE quotes SET bonus_used=0 WHERE id=?',[(r['id'],) for r in rows])
        return amount

    def bonus_balance(self, uid):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self._release_stale_bonus_locked(uid)
            self.db.execute("INSERT OR IGNORE INTO users(id,state) VALUES(?,'{}')",(uid,))
            row=self.db.execute('SELECT bonus_kopecks FROM users WHERE id=?',(uid,)).fetchone()
            self.db.execute('COMMIT')
            return int(row[0] if row else 0)
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def add_bonus(self, uid, kopecks):
        kopecks=int(kopecks)
        if kopecks<0: raise ShopError('Бонус не может быть отрицательным.')
        self.db.execute("INSERT INTO users(id,state,bonus_kopecks) VALUES(?,'{}',?) ON CONFLICT(id) DO UPDATE SET bonus_kopecks=bonus_kopecks+excluded.bonus_kopecks",(uid,kopecks))
        return self.bonus_balance(uid)

    def quote(self, uid, hours, gb, amount, product="regular", operator="", targets=None, min_cash=100):
        amount=int(amount); min_cash=max(0,int(min_cash)); qid=uuid.uuid4().hex
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self._release_stale_bonus_locked(uid)
            self.db.execute("INSERT OR IGNORE INTO users(id,state) VALUES(?,'{}')",(uid,))
            balance=int(self.db.execute('SELECT bonus_kopecks FROM users WHERE id=?',(uid,)).fetchone()[0])
            bonus=min(balance,max(0,amount-min_cash))
            payable=amount-bonus
            self.db.execute('UPDATE users SET bonus_kopecks=bonus_kopecks-? WHERE id=?',(bonus,uid))
            self.db.execute(
                'INSERT INTO quotes(id,user_id,hours,gb,amount,created,product,operator,targets,base_amount,bonus_used) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (qid,uid,hours,gb,payable,int(time.time()),product,operator,json.dumps(targets or []),amount,bonus),
            )
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise
        return qid

    def order(self, qid, uid):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            q = self.db.execute('SELECT * FROM quotes WHERE id=? AND user_id=?',(qid,uid)).fetchone()
            if q is None:
                raise ShopError('Расчёт не найден.')
            existing = self.db.execute('SELECT id FROM orders WHERE quote_id=?',(qid,)).fetchone()
            if existing:
                oid = existing[0]
            else:
                if time.time()-q['created'] > 900:
                    raise ShopError('Цена устарела. Выбери тариф заново.')
                count = self.db.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status IN ('creating','pending')",(uid,)).fetchone()[0]
                if count >= 3:
                    raise ShopError('Уже есть 3 неоплаченных заказа. Открой «Мои покупки» или дождись истечения счетов.')
                oid = uuid.uuid4().hex
                self.db.execute('''INSERT INTO orders
                (id,quote_id,user_id,hours,gb,amount,status,created,uuid,sub_id,email,base_amount,bonus_used)
                VALUES(?,?,?,?,?,?,'creating',?,?,?,?,?,?)''',
                (oid,qid,uid,q['hours'],q['gb'],q['amount'],int(time.time()),str(uuid.uuid4()),uuid.uuid4().hex,'shop-'+oid,
                 int(q['base_amount'] or q['amount']),int(q['bonus_used'] or 0)))
                self.db.execute('UPDATE orders SET product=?,operator=?,targets=?,display_name=? WHERE id=?',
                    (q['product'],q['operator'],q['targets'],self.display_name(uid),oid))
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise
        return self.get(oid)

    def mine(self, uid):
        return [dict(r) for r in self.db.execute("SELECT * FROM orders WHERE user_id=? AND quote_id NOT LIKE 'event-%' ORDER BY created DESC LIMIT 20",(uid,))]

    def create_mirror(self, uid):
        token=uuid.uuid4().hex[:16]
        self.db.execute('INSERT INTO mirrors(token,owner_id,created) VALUES(?,?,?)',(token,uid,int(time.time())))
        return token

    def grant_trial(self, uid, order_ids, mirror_token=''):
        now=int(time.time())
        self.db.execute('INSERT OR IGNORE INTO trial_grants(user_id,created,mirror_token) VALUES(?,?,?)',(uid,now,mirror_token))
        self.db.execute('UPDATE mirrors SET trial_order_ids=? WHERE token=?',(json.dumps(order_ids),mirror_token)) if mirror_token else None

    def has_trial(self, uid):
        return self.db.execute('SELECT 1 FROM trial_grants WHERE user_id=?',(uid,)).fetchone() is not None

    def add_managed_bot(self, bot_id, owner_id, username, token):
        self.db.execute('INSERT OR REPLACE INTO managed_bots(bot_id,owner_id,username,token,created) VALUES(?,?,?,?,?)',
                        (bot_id,owner_id,username,token,int(time.time())))

    def create_event_order(self, uid, expiry_ms):
        now=int(time.time()); oid=uuid.uuid4().hex
        expiry_ms=int(expiry_ms)
        if expiry_ms<=now*1000:
            raise ShopError('Бонусный срок уже истёк.')
        self.db.execute('''INSERT INTO orders
          (id,quote_id,user_id,hours,gb,amount,status,created,uuid,sub_id,email,expiry_ms,product,operator,targets,display_name,delivered,migration_notified)
          VALUES(?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,1,1)''',
          (oid,'event-'+oid,uid,1,0,0,now,str(uuid.uuid4()),uuid.uuid4().hex,'event-'+oid,
           expiry_ms,'regular','',json.dumps(['regular']),self.display_name(uid)))
        return oid

    def create_manual_order(self, uid, product='regular', hours=720, targets=None):
        now=int(time.time()); oid=uuid.uuid4().hex
        self.db.execute('''INSERT INTO orders
          (id,quote_id,user_id,hours,gb,amount,status,created,uuid,sub_id,email,expiry_ms,product,operator,targets,display_name,delivered)
          VALUES(?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,0)''',
          (oid,'manual-'+oid,uid,hours,0,0,now,str(uuid.uuid4()),uuid.uuid4().hex,'manual-'+oid,
           (now+hours*3600)*1000,product,'',json.dumps(targets or (['regular'] if product=='regular' else [])),self.display_name(uid)))
        return oid

    def create_trial_orders(self, uid, hours=72, operator=''):
        if self.has_trial(uid):
            return []
        now=int(time.time()); expiry=(now+hours*3600)*1000; ids=[]
        for product,targets in (('regular',['regular']),('whitelist',['max','yandex','disk','vk','vkvideo']),('mtproto',[])):
            oid=uuid.uuid4().hex; qid='trial-'+oid
            self.db.execute('''INSERT INTO orders
              (id,quote_id,user_id,hours,gb,amount,status,created,uuid,sub_id,email,expiry_ms,product,operator,targets,display_name,delivered)
              VALUES(?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,0)''',
              (oid,qid,uid,hours,0,0,now,str(uuid.uuid4()),uuid.uuid4().hex,'trial-'+oid,expiry,product,operator,json.dumps(targets),self.display_name(uid)))
            ids.append(oid)
        self.grant_trial(uid,ids)
        return ids

    def due(self, limit=5):
        return [dict(r) for r in self.db.execute("""SELECT * FROM orders WHERE
        status IN ('creating','pending','paid','provisioning','expired') AND next_check<=?
        ORDER BY next_check,created LIMIT ?""",(int(time.time()),limit))]

    def unsent_invoices(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM orders WHERE status='pending' AND invoice_sent=0 LIMIT 10")]

    def undelivered(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM orders WHERE status IN ('active','test_paid') AND delivered=0 LIMIT 10")]

    def backup(self, path):
        target=sqlite3.connect(path)
        self.db.backup(target)
        target.close()


class Engine:
    def __init__(self, store, payment, panel, cfg):
        self.s, self.payment, self.panel, self.cfg = store, payment, panel, cfg

    def check(self, oid):
        o=self.s.get(oid)
        if o['status'] in ('active','test_paid','review'):
            return o
        if o['status'] == 'creating':
            # Provider payment_id is stable across timeouts/restarts.
            invoice=self.payment.ensure_invoice(o)
            try:
                self.payment.validate(invoice,o)
            except ShopError:
                self.s.patch(oid,status='review',error='invoice_validation')
                raise
            self.s.patch(oid,status='pending',invoice_id=int(invoice['invoice_id']),
                         invoice_url=invoice['url'],provider_amount=str(invoice['amount']),
                         invoice_expiry=int(invoice['expires_at']),attempts=0,error=None)
            # Deliver the new payment URL before doing another provider request.
            if invoice.get('status') != 'paid':
                # Check shortly after the buyer returns from LZT.  The provider
                # may still be processing the payment, so keep the durable
                # order and retry instead of making the user press anything.
                self.s.patch(oid,next_check=int(time.time())+10)
                return self.s.get(oid)
            o=self.s.get(oid)
        if o['status'] in ('pending','expired'):
            inv=self.payment.get_invoice(o)
            try:
                self.payment.validate(inv,o,paid_check=True)
            except ShopError:
                self.s.patch(oid,status='review',error='invoice_validation')
                raise
            if inv['status'] != 'paid':
                now=int(time.time())
                expired=now > o['invoice_expiry']
                # Retain late-payment reconciliation. Expired orders checked daily
                # after 7 days; never silently abandon a paid invoice.
                gap=86400 if now-o['created']>7*86400 else (600 if expired else 10)
                self.s.patch(oid,status='expired' if expired else 'pending',next_check=now+gap,attempts=0)
                return self.s.get(oid)
            if inv['is_test']:
                self.s.patch(oid,status='review',error='unexpected_test_invoice')
                raise ShopError('Тестовый платёж не может выдать реальный доступ.')
            self.s.patch(oid,status='paid',attempts=0,error=None)
            o=self.s.get(oid)
        if o['status'] in ('paid','provisioning'):
            if not self.panel.exists(o):
                self.s.patch(oid,status='provisioning',expiry_ms=(int(time.time())+o['hours']*3600)*1000)
                o=self.s.get(oid)
            # Retry always uses the stored UUID, email, subId and deadline.
            # If response was lost after creation, panel.ensure detects that client.
            link=self.panel.ensure(o)
            self.s.patch(oid,status='active',link=link,error=None,attempts=0)
        return self.s.get(oid)

    def retry_later(self, oid, kind):
        o=self.s.get(oid)
        attempts=o['attempts']+1
        self.s.patch(oid,attempts=attempts,next_check=int(time.time())+min(3600,15*2**min(attempts,8)),error=kind)

