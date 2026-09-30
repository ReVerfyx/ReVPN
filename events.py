"""Server-side Telegram Mini App games and event rewards for ReVPN."""
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qsl

from core import Store
from delivery import Delivery

EVENT_ACTIVE_SECONDS = 3600
EVENT_BREAK_SECONDS = 600
EVENT_CYCLE_SECONDS = EVENT_ACTIVE_SECONDS + EVENT_BREAK_SECONDS
EVENT_COUNT = 1000
INIT_DATA_MAX_AGE = 24 * 3600
MIN_TAP_MS = 110
WINDOW_MS = 1000
WINDOW_LIMIT = 7
STRIKE_LIMIT = 5
COOLDOWN_MS = 20_000
UNIFORM_LIMIT = 12
MIN_CLAIM_SECONDS = 30

_VERBS = (
    ("Ледяной разгон", "Разогнать"),
    ("Импульс сети", "Импульс"),
    ("Морозный буст", "Буст"),
    ("Пульс туннеля", "Пульс"),
    ("Снежный заряд", "Заряд"),
    ("Крио-тап", "Крио-тап"),
    ("Сигнал ReVPN", "Сигнал"),
    ("Холодный клик", "Клик"),
    ("Ускорение", "Ускорить"),
    ("Энергия сети", "Энергия"),
)
_OBJECTS = (
    ("сервер", "сервер"),
    ("туннель", "туннель"),
    ("узел", "узел"),
    ("канал", "канал"),
    ("маршрут", "маршрут"),
    ("пакет", "пакет"),
    ("ледник", "ледник"),
    ("шлюз", "шлюз"),
    ("сигнал", "сигнал"),
    ("ядро", "ядро"),
)
_MARKS = ("🧊", "⚡", "❄️", "🔹", "💠", "🌨️", "🌀", "🔷", "☃️", "🥶")
_CHALLENGE = ("🧊", "⚡", "❄️")
_GAMES = (
    ("tap_rush", "Тап-гонка"),
    ("snow_catch", "Поймай снежинку"),
    ("reaction", "Ледяная реакция"),
    ("ice_break", "Разбей кристалл"),
)


class EventError(Exception):
    def __init__(self, message, status=400, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


class EventAuthError(EventError):
    def __init__(self, message="Открой Mini App из Telegram."):
        super().__init__(message, 401)


def _reward_definition(event_id):
    mode = (event_id * 7 + event_id // 10) % 3
    if mode == 0:
        return {
            "kind": "seconds",
            "unit_seconds": 1,
            "unit_kopecks": 0,
            "cap_seconds": 3600,
            "cap_kopecks": 0,
            "label": "+1 сек VPN",
        }
    if mode == 1:
        return {
            "kind": "rubles",
            "unit_seconds": 0,
            "unit_kopecks": 5,
            "cap_seconds": 0,
            "cap_kopecks": 500,
            "label": "+0.05 ₽",
        }
    return {
        "kind": "mixed",
        "unit_seconds": 1,
        "unit_kopecks": 2,
        "cap_seconds": 900,
        "cap_kopecks": 200,
        "label": "+1 сек · +0.02 ₽",
    }


def event_definition(event_id):
    if not 0 <= int(event_id) < EVENT_COUNT:
        raise ValueError("event id")
    event_id = int(event_id)
    a, b, c = event_id // 100, (event_id // 10) % 10, event_id % 10
    verb, action = _VERBS[a]
    obj, target = _OBJECTS[b]
    mark = _MARKS[c]
    game, game_title = _GAMES[(a + b + c) % len(_GAMES)]
    reward = _reward_definition(event_id)
    game_text = {
        "tap_rush": "Лови движущуюся кнопку и держи живой ритм.",
        "snow_catch": "Снежинки падают быстро — успевай ловить их до земли.",
        "reaction": "Жди вспышку сигнала и нажимай только после неё.",
        "ice_break": "Разбивай ледяной кристалл точными ударами.",
    }[game]
    return {
        "id": event_id,
        "title": f"{game_title}: {verb.lower()}",
        "subtitle": f"{obj.capitalize()} · {mark}",
        "description": f"{game_text} Награда: {reward['label']}.",
        "button": f"{action} {target} {mark}",
        "mark": mark,
        "accent": c % 6,
        "game": game,
        "game_title": game_title,
        "reward": reward,
    }


def event_clock(now=None):
    now = time.time() if now is None else float(now)
    whole = int(now)
    cycle = whole // EVENT_CYCLE_SECONDS
    phase = whole % EVENT_CYCLE_SECONDS
    event_id = (cycle * 137 + 509) % EVENT_COUNT
    start = cycle * EVENT_CYCLE_SECONDS
    active = phase < EVENT_ACTIVE_SECONDS
    return {
        "active": active,
        "event_id": event_id,
        "event_no": cycle % EVENT_COUNT + 1,
        "started_at": start,
        "ends_at": start + EVENT_ACTIVE_SECONDS,
        "next_at": start + EVENT_CYCLE_SECONDS,
        "server_time": whole,
        "seconds_left": (EVENT_ACTIVE_SECONDS - phase) if active else (EVENT_CYCLE_SECONDS - phase),
    }


def validate_init_data(init_data, bot_token, now=None):
    if not isinstance(init_data, str) or not init_data or len(init_data) > 16384:
        raise EventAuthError()
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        supplied = pairs.pop("hash")
        check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise EventAuthError("Telegram-подпись Mini App не прошла проверку.")
        auth_date = int(pairs["auth_date"])
        current = int(time.time() if now is None else now)
        if auth_date > current + 60 or current - auth_date > INIT_DATA_MAX_AGE:
            raise EventAuthError("Сессия Mini App устарела. Закрой и открой её заново.")
        user = json.loads(pairs["user"])
        uid = int(user["id"])
        if uid <= 0:
            raise ValueError
        name = str(user.get("first_name") or user.get("username") or "Друг")[:80]
        return uid, name
    except EventAuthError:
        raise
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        raise EventAuthError("Некорректные данные Telegram Mini App.") from None


def _challenge_after(uid, taps, nonce):
    digest = hashlib.sha256(f"{uid}:{taps}:{nonce}".encode()).digest()
    return taps + 45 + digest[0] % 36


def _slot(nonce):
    return hashlib.sha256(nonce.encode()).digest()[0] % 9


def _reaction_delay(nonce):
    return 700 + hashlib.sha256(nonce.encode()).digest()[2] % 1200


class EventService:
    def __init__(self, db_path, cfg, data_dir=None, delivery_factory=Delivery):
        self.cfg = cfg
        token = cfg.get("telegram", {}).get("token", "")
        if not token:
            raise ValueError("telegram token is required for Mini App events")
        self.bot_token = token
        self.public_base = cfg.get("subscription", {}).get("public_base", "").rstrip("/")
        self.store = Store(str(db_path))
        self.db = self.store.db
        self.delivery = delivery_factory(cfg, self.store, data_dir or Path(db_path).parent)
        self._schema()

    def close(self):
        try:
            self.db.close()
        except Exception:
            pass

    def _schema(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS event_users(
          user_id INTEGER PRIMARY KEY,
          balance_seconds INTEGER NOT NULL DEFAULT 0,
          lifetime_seconds INTEGER NOT NULL DEFAULT 0,
          accepted_taps INTEGER NOT NULL DEFAULT 0,
          last_tap_ms INTEGER NOT NULL DEFAULT 0,
          window_start_ms INTEGER NOT NULL DEFAULT 0,
          window_taps INTEGER NOT NULL DEFAULT 0,
          fast_strikes INTEGER NOT NULL DEFAULT 0,
          last_delta_ms INTEGER NOT NULL DEFAULT 0,
          uniform_hits INTEGER NOT NULL DEFAULT 0,
          cooldown_until_ms INTEGER NOT NULL DEFAULT 0,
          nonce TEXT NOT NULL DEFAULT '',
          next_challenge_at INTEGER NOT NULL DEFAULT 0,
          challenge_answer INTEGER NOT NULL DEFAULT -1,
          bonus_order_id TEXT NOT NULL DEFAULT '',
          pending_sync INTEGER NOT NULL DEFAULT 0,
          action_ready_ms INTEGER NOT NULL DEFAULT 0,
          updated INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS event_progress(
          user_id INTEGER NOT NULL,
          event_id INTEGER NOT NULL,
          taps INTEGER NOT NULL DEFAULT 0,
          reward_seconds INTEGER NOT NULL DEFAULT 0,
          reward_kopecks INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(user_id,event_id)
        );
        """)
        for table, fields in {
            "event_users": {"action_ready_ms": "INTEGER NOT NULL DEFAULT 0"},
            "event_progress": {
                "reward_seconds": "INTEGER NOT NULL DEFAULT 0",
                "reward_kopecks": "INTEGER NOT NULL DEFAULT 0",
            },
        }.items():
            existing = {r[1] for r in self.db.execute("PRAGMA table_info(" + table + ")")}
            for key, typ in fields.items():
                if key not in existing:
                    self.db.execute("ALTER TABLE " + table + " ADD COLUMN " + key + " " + typ)

    def _auth(self, init_data, now=None):
        uid, name = validate_init_data(init_data, self.bot_token, now)
        current = self.db.execute("SELECT display_name FROM users WHERE id=?", (uid,)).fetchone()
        if current is None or current[0] != name:
            self.store.display_name(uid, name)
        return uid

    def _ensure_user(self, uid, now_ms):
        row = self.db.execute("SELECT * FROM event_users WHERE user_id=?", (uid,)).fetchone()
        if row:
            return row
        nonce = secrets.token_hex(16)
        self.db.execute(
            """INSERT INTO event_users(user_id,nonce,next_challenge_at,updated)
               VALUES(?,?,?,?)""",
            (uid, nonce, _challenge_after(uid, 0, nonce), now_ms // 1000),
        )
        return self.db.execute("SELECT * FROM event_users WHERE user_id=?", (uid,)).fetchone()

    def _prime_game(self, uid, now_ms, event):
        row = self.db.execute("SELECT nonce,action_ready_ms FROM event_users WHERE user_id=?", (uid,)).fetchone()
        if event["game"] == "reaction" and row and int(row["action_ready_ms"]) <= 0:
            ready = now_ms + _reaction_delay(row["nonce"])
            self.db.execute("UPDATE event_users SET action_ready_ms=? WHERE user_id=?", (ready, uid))

    def _challenge_payload(self, row):
        answer = int(row["challenge_answer"])
        if answer < 0:
            return None
        return {
            "required": True,
            "prompt": "Проверка от автокликера: нажми " + _CHALLENGE[answer],
            "options": [{"id": i, "label": label} for i, label in enumerate(_CHALLENGE)],
        }

    def _response(self, uid, now=None):
        current = time.time() if now is None else float(now)
        clock = event_clock(current)
        event = event_definition(clock["event_id"])
        row = self.db.execute("SELECT * FROM event_users WHERE user_id=?", (uid,)).fetchone()
        progress = self.db.execute(
            "SELECT * FROM event_progress WHERE user_id=? AND event_id=?",
            (uid, clock["event_id"]),
        ).fetchone()
        wallet = self.db.execute("SELECT bonus_kopecks FROM users WHERE id=?", (uid,)).fetchone()
        bonus = None
        if row and row["bonus_order_id"]:
            try:
                order = self.store.get(row["bonus_order_id"], uid)
                bonus = {
                    "expiry_ms": order.get("expiry_ms") or 0,
                    "connect_url": self.public_base + "/connect/" + order["sub_id"],
                    "syncing": bool(row["pending_sync"]),
                }
            except Exception:
                bonus = None
        now_ms = int(current * 1000)
        return {
            "ok": True,
            "clock": clock,
            "event": event,
            "user": {
                "balance_seconds": int(row["balance_seconds"]) if row else 0,
                "bonus_kopecks": int(wallet[0]) if wallet else 0,
                "lifetime_seconds": int(row["lifetime_seconds"]) if row else 0,
                "event_taps": int(progress["taps"]) if progress else 0,
                "event_reward_seconds": int(progress["reward_seconds"]) if progress else 0,
                "event_reward_kopecks": int(progress["reward_kopecks"]) if progress else 0,
                "cooldown_ms": max(0, int(row["cooldown_until_ms"]) - now_ms) if row else 0,
                "ready_in_ms": max(0, int(row["action_ready_ms"]) - now_ms) if row and event["game"] == "reaction" else 0,
                "nonce": row["nonce"] if row else "",
                "slot": _slot(row["nonce"]) if row else 4,
                "challenge": self._challenge_payload(row) if row else None,
                "bonus": bonus,
                "min_claim_seconds": MIN_CLAIM_SECONDS,
            },
        }

    def state(self, init_data, now=None):
        uid = self._auth(init_data, now)
        current = time.time() if now is None else float(now)
        now_ms = int(current * 1000)
        clock = event_clock(current)
        event = event_definition(clock["event_id"])
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._ensure_user(uid, now_ms)
            self._prime_game(uid, now_ms, event)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return self._response(uid, current)

    def _reward(self, uid, event, progress):
        reward = event["reward"]
        old_sec = int(progress["reward_seconds"]) if progress else 0
        old_kop = int(progress["reward_kopecks"]) if progress else 0
        add_sec = min(int(reward["unit_seconds"]), max(0, int(reward["cap_seconds"]) - old_sec))
        add_kop = min(int(reward["unit_kopecks"]), max(0, int(reward["cap_kopecks"]) - old_kop))
        if add_kop:
            self.store.add_bonus(uid, add_kop)
        return add_sec, add_kop

    def play(self, init_data, event_id, nonce, now=None):
        uid = self._auth(init_data, now)
        current = time.time() if now is None else float(now)
        now_ms = int(current * 1000)
        clock = event_clock(current)
        if not clock["active"] or int(event_id) != clock["event_id"]:
            raise EventError("Этот ивент уже закончился.", 409)
        event = event_definition(clock["event_id"])

        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self._ensure_user(uid, now_ms)
            self._prime_game(uid, now_ms, event)
            row = self.db.execute("SELECT * FROM event_users WHERE user_id=?", (uid,)).fetchone()
            if not hmac.compare_digest(str(nonce), str(row["nonce"])):
                raise EventError("Действие устарело. Обновляю игру.", 409)
            if int(row["challenge_answer"]) >= 0:
                raise EventError("Сначала пройди короткую проверку.", 409, {"challenge": self._challenge_payload(row)})
            if event["game"] == "reaction" and int(row["action_ready_ms"]) > now_ms:
                self.db.execute("COMMIT")
                payload = self._response(uid, current)
                payload["accepted"] = False
                payload["message"] = "Рано — дождись вспышки."
                return payload

            new_nonce = secrets.token_hex(16)
            cooldown = int(row["cooldown_until_ms"])
            if cooldown > now_ms:
                self.db.execute("UPDATE event_users SET nonce=?,updated=? WHERE user_id=?", (new_nonce, now_ms // 1000, uid))
                self.db.execute("COMMIT")
                payload = self._response(uid, current)
                payload["user"]["cooldown_ms"] = cooldown - now_ms
                return payload

            last = int(row["last_tap_ms"])
            delta = now_ms - last if last else 9999
            ws = int(row["window_start_ms"])
            wt = int(row["window_taps"])
            if not ws or now_ms - ws >= WINDOW_MS:
                ws, wt = now_ms, 0

            min_gap = 150 if event["game"] == "snow_catch" else MIN_TAP_MS
            violation = (last and delta < min_gap) or wt >= WINDOW_LIMIT
            strikes = int(row["fast_strikes"])
            if violation:
                strikes += 1
                until = now_ms + COOLDOWN_MS if strikes >= STRIKE_LIMIT else 0
                if until:
                    strikes = 0
                self.db.execute(
                    """UPDATE event_users SET nonce=?,fast_strikes=?,cooldown_until_ms=?,
                       updated=? WHERE user_id=?""",
                    (new_nonce, strikes, until, now_ms // 1000, uid),
                )
                self.db.execute("COMMIT")
                payload = self._response(uid, current)
                payload["accepted"] = False
                payload["message"] = "Слишком быстро. Действие не засчитано."
                return payload

            last_delta = int(row["last_delta_ms"])
            uniform = int(row["uniform_hits"])
            uniform = uniform + 1 if last and abs(delta - last_delta) <= 4 else 0
            if uniform >= UNIFORM_LIMIT:
                self.db.execute(
                    """UPDATE event_users SET nonce=?,uniform_hits=0,cooldown_until_ms=?,
                       fast_strikes=0,updated=? WHERE user_id=?""",
                    (new_nonce, now_ms + COOLDOWN_MS, now_ms // 1000, uid),
                )
                self.db.execute("COMMIT")
                payload = self._response(uid, current)
                payload["accepted"] = False
                payload["message"] = "Слишком ровный ритм. Похоже на автокликер."
                return payload

            progress = self.db.execute(
                "SELECT * FROM event_progress WHERE user_id=? AND event_id=?",
                (uid, clock["event_id"]),
            ).fetchone()
            add_sec, add_kop = self._reward(uid, event, progress)
            total = int(row["accepted_taps"]) + 1
            balance = int(row["balance_seconds"]) + add_sec
            lifetime = int(row["lifetime_seconds"]) + add_sec
            next_challenge = int(row["next_challenge_at"]) or _challenge_after(uid, total, new_nonce)
            challenge_answer = -1
            if total >= next_challenge:
                challenge_answer = hashlib.sha256(new_nonce.encode()).digest()[1] % len(_CHALLENGE)
                next_challenge = 0
            ready_at = now_ms + _reaction_delay(new_nonce) if event["game"] == "reaction" else 0

            self.db.execute(
                """UPDATE event_users SET balance_seconds=?,lifetime_seconds=?,accepted_taps=?,
                   last_tap_ms=?,window_start_ms=?,window_taps=?,fast_strikes=?,
                   last_delta_ms=?,uniform_hits=?,nonce=?,next_challenge_at=?,
                   challenge_answer=?,action_ready_ms=?,updated=? WHERE user_id=?""",
                (balance, lifetime, total, now_ms, ws, wt + 1, max(0, strikes - 1),
                 delta, uniform, new_nonce, next_challenge, challenge_answer, ready_at,
                 now_ms // 1000, uid),
            )
            self.db.execute(
                """INSERT INTO event_progress(user_id,event_id,taps,reward_seconds,reward_kopecks)
                   VALUES(?,?,1,?,?)
                   ON CONFLICT(user_id,event_id) DO UPDATE SET
                     taps=taps+1,
                     reward_seconds=reward_seconds+excluded.reward_seconds,
                     reward_kopecks=reward_kopecks+excluded.reward_kopecks""",
                (uid, clock["event_id"], add_sec, add_kop),
            )
            self.db.execute("COMMIT")
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

        payload = self._response(uid, current)
        payload["accepted"] = True
        payload["reward"] = {"seconds": add_sec, "kopecks": add_kop}
        if add_sec or add_kop:
            bits = []
            if add_sec:
                bits.append("+" + str(add_sec) + " сек")
            if add_kop:
                bits.append("+" + ("%.2f" % (add_kop / 100)) + " ₽")
            payload["message"] = " · ".join(bits)
        else:
            payload["message"] = "Лимит награды этого ивента достигнут."
        payload["move_button"] = event["game"] in ("tap_rush", "ice_break")
        return payload

    def tap(self, init_data, event_id, nonce, now=None):
        return self.play(init_data, event_id, nonce, now)

    def challenge(self, init_data, nonce, choice, now=None):
        uid = self._auth(init_data, now)
        current = time.time() if now is None else float(now)
        now_ms = int(current * 1000)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self._ensure_user(uid, now_ms)
            if not hmac.compare_digest(str(nonce), str(row["nonce"])):
                raise EventError("Проверка устарела.", 409)
            cooldown = int(row["cooldown_until_ms"])
            if cooldown > now_ms:
                self.db.execute("COMMIT")
                payload = self._response(uid, current)
                payload["message"] = "Подожди окончания короткой паузы."
                return payload
            answer = int(row["challenge_answer"])
            if answer < 0:
                raise EventError("Проверка уже пройдена.", 409)
            new_nonce = secrets.token_hex(16)
            if int(choice) != answer:
                self.db.execute(
                    "UPDATE event_users SET nonce=?,cooldown_until_ms=?,updated=? WHERE user_id=?",
                    (new_nonce, now_ms + 5000, now_ms // 1000, uid),
                )
                self.db.execute("COMMIT")
                payload = self._response(uid, current)
                payload["message"] = "Не та кнопка. Попробуй после короткой паузы."
                return payload
            taps = int(row["accepted_taps"])
            self.db.execute(
                """UPDATE event_users SET nonce=?,challenge_answer=-1,next_challenge_at=?,
                   uniform_hits=0,fast_strikes=0,action_ready_ms=0,updated=? WHERE user_id=?""",
                (new_nonce, _challenge_after(uid, taps, new_nonce), now_ms // 1000, uid),
            )
            event = event_definition(event_clock(current)["event_id"])
            self._prime_game(uid, now_ms, event)
            self.db.execute("COMMIT")
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        payload = self._response(uid, current)
        payload["message"] = "Проверка пройдена."
        return payload

    def claim(self, init_data, now=None):
        uid = self._auth(init_data, now)
        current = time.time() if now is None else float(now)
        now_ms = int(current * 1000)

        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self._ensure_user(uid, now_ms)
            balance = int(row["balance_seconds"])
            pending = bool(row["pending_sync"])
            oid = str(row["bonus_order_id"] or "")
            if balance and balance < MIN_CLAIM_SECONDS and not pending:
                raise EventError(f"Накопи хотя бы {MIN_CLAIM_SECONDS} секунд, чтобы активировать VPN.", 409)
            if not balance and not pending:
                self.db.execute("COMMIT")
                payload = self._response(uid, current)
                payload["message"] = "Новых секунд для активации пока нет."
                return payload

            if not oid:
                oid = self.store.create_event_order(uid, now_ms + balance * 1000)
            else:
                order = self.store.get(oid, uid)
                target = max(now_ms, int(order.get("expiry_ms") or 0)) + balance * 1000
                if balance:
                    self.store.patch(oid, expiry_ms=target)
            self.db.execute(
                """UPDATE event_users SET balance_seconds=0,bonus_order_id=?,
                   pending_sync=1,updated=? WHERE user_id=?""",
                (oid, now_ms // 1000, uid),
            )
            self.db.execute("COMMIT")
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

        try:
            order = self.store.get(oid, uid)
            link = self.delivery.sync_expiry(order)
            self.store.patch(oid, link=link, delivered=1)
            self.db.execute(
                "UPDATE event_users SET pending_sync=0,updated=? WHERE user_id=?",
                (int(time.time()), uid),
            )
        except Exception as exc:
            raise EventError(
                "Секунды сохранены, но VPN пока не синхронизировался. Нажми «Активировать» ещё раз.",
                503,
                {"pending": True, "detail": type(exc).__name__},
            ) from None

        payload = self._response(uid, current)
        payload["message"] = "Секунды применены к бонусному VPN."
        payload["claimed_seconds"] = balance
        return payload
