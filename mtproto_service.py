"""Supervise pinned upstream MTProto with per-order secrets and hard time expiry."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import uuid


POLL_SECONDS = 1.0
MIN_EXPIRY_SLEEP = 0.05


def paid_snapshot(db, now):
    """Return active per-order secrets and the nearest paid expiry timestamp."""
    now_ms = int(now * 1000)
    rows = db.execute(
        "SELECT id,uuid,expiry_ms FROM orders "
        "WHERE product='mtproto' AND status IN ('provisioning','active') AND expiry_ms>?",
        (now_ms,),
    ).fetchall()
    users = {row[0]: uuid.UUID(row[1]).hex for row in rows}
    next_expiry = min((row[2] for row in rows), default=None)
    return users, (next_expiry / 1000 if next_expiry is not None else None)


def paid_users(db, now):
    # Kept as a small public helper for tests/tools that only need the secret map.
    return paid_snapshot(db, now)[0]


def run(cfg, data, kind):
    section = cfg['mtproto'][kind]
    if not section.get('enabled'):
        return

    child = None
    previous = None
    running = True
    root = Path(data)
    state = root / ('mtproto-' + kind + '-ready.json')
    config_path = root / ('mtproto-' + kind + '.py')

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while running:
            next_expiry = None
            try:
                if kind == 'free':
                    users = {'free': section['secret']}
                else:
                    with sqlite3.connect(
                        'file:' + str(root / 'shop.sqlite3') + '?mode=ro', uri=True
                    ) as db:
                        users, next_expiry = paid_snapshot(db, time.time())

                # Each paid order is a separate 32-hex MTProto secret. When one
                # expires, rebuild the upstream user map and restart it so even
                # already-established sessions for that secret are disconnected.
                if users != previous or child is None or child.poll() is not None:
                    state.unlink(missing_ok=True)
                    if child and child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()

                    config_path.write_text(
                        'PORT = ' + repr(section['port']) + '\n'
                        'USERS = ' + repr(users) + '\n'
                        'MODES = {"classic": False, "secure": True, "tls": False}\n'
                        'AD_TAG = ' + repr(section.get('ad_tag', '') if kind == 'free' else '') + '\n'
                    )
                    os.chmod(config_path, 0o600)
                    child = subprocess.Popen(
                        [
                            sys.executable,
                            str(Path(__file__).parent / 'vendor/mtprotoproxy.py'),
                            str(config_path),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    previous = users

                if child.poll() is None:
                    try:
                        with socket.create_connection(
                            ('127.0.0.1', section['port']), timeout=1
                        ):
                            pass
                        temp = state.with_suffix('.tmp')
                        temp.write_text(
                            json.dumps({'time': time.time(), 'orders': list(users)})
                        )
                        temp.replace(state)
                    except OSError:
                        state.unlink(missing_ok=True)
            except (sqlite3.Error, OSError):
                # Fail closed if the entitlement database is unavailable.
                state.unlink(missing_ok=True)
                if child and child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)
                child = None

            # Poll normally once per second, but wake exactly around the nearest
            # paid expiry instead of leaving a 1-hour key alive for another poll.
            delay = POLL_SECONDS
            if kind == 'paid' and next_expiry is not None:
                delay = max(
                    MIN_EXPIRY_SLEEP,
                    min(POLL_SECONDS, next_expiry - time.time()),
                )
            time.sleep(delay)
    finally:
        state.unlink(missing_ok=True)
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == '__main__':
    os.umask(0o077)
    p = argparse.ArgumentParser()
    p.add_argument('kind', choices=['paid', 'free'])
    p.add_argument('--config', default='/etc/revpn-shop/config.json')
    p.add_argument('--data', default='/var/lib/revpn-shop')
    a = p.parse_args()
    run(json.loads(Path(a.config).read_text()), a.data, a.kind)
