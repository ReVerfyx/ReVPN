#!/usr/bin/env python3
"""TCP 443 SNI router for HTTPS + free/paid FakeTLS MTProto."""
import argparse
import asyncio
import json
from pathlib import Path


MAX_HELLO = 65540
HELLO_TIMEOUT = 4.0


def client_hello_sni(data):
    """Return lower-case SNI from a TLS ClientHello, or '' when unavailable."""
    try:
        if len(data) < 5 or data[0] != 0x16:
            return ""
        record_len = int.from_bytes(data[3:5], "big")
        if len(data) < 5 + record_len:
            return ""
        p = 5
        if data[p] != 0x01:
            return ""
        p += 4  # handshake type + 3-byte length
        p += 2 + 32  # version + random
        sid = data[p]
        p += 1 + sid
        suites = int.from_bytes(data[p:p+2], "big")
        p += 2 + suites
        comp = data[p]
        p += 1 + comp
        ext_total = int.from_bytes(data[p:p+2], "big")
        p += 2
        end = min(len(data), p + ext_total)
        while p + 4 <= end:
            typ = int.from_bytes(data[p:p+2], "big")
            size = int.from_bytes(data[p+2:p+4], "big")
            p += 4
            payload = data[p:p+size]
            p += size
            if typ != 0 or len(payload) < 5:
                continue
            q = 2
            names_len = int.from_bytes(payload[:2], "big")
            limit = min(len(payload), 2 + names_len)
            while q + 3 <= limit:
                name_type = payload[q]
                name_len = int.from_bytes(payload[q+1:q+3], "big")
                q += 3
                name = payload[q:q+name_len]
                q += name_len
                if name_type == 0:
                    return name.decode("ascii", "ignore").strip(".").lower()
    except (IndexError, ValueError):
        pass
    return ""


async def pipe(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def read_preface(reader):
    first = await asyncio.wait_for(reader.readexactly(5), HELLO_TIMEOUT)
    if first[0] != 0x16:
        return first
    size = int.from_bytes(first[3:5], "big")
    if size < 1 or size > MAX_HELLO - 5:
        return first
    rest = await asyncio.wait_for(reader.readexactly(size), HELLO_TIMEOUT)
    return first + rest


async def handle(client_reader, client_writer, cfg):
    edge = cfg["edge443"]
    try:
        preface = await read_preface(client_reader)
        sni = client_hello_sni(preface)
        if sni == str(edge.get("free_sni", "")).lower():
            port = int(cfg["mtproto"]["free"]["port"])
        elif sni == str(edge.get("paid_sni", "")).lower():
            port = int(cfg["mtproto"]["paid"]["port"])
        else:
            port = int(edge.get("web_backend_port", 4443))
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port), 4.0
        )
        upstream_writer.write(preface)
        await upstream_writer.drain()
        a = asyncio.create_task(pipe(client_reader, upstream_writer))
        b = asyncio.create_task(pipe(upstream_reader, client_writer))
        done, pending = await asyncio.wait((a, b), return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, OSError):
        try:
            client_writer.close()
            await client_writer.wait_closed()
        except Exception:
            pass


async def main_async(cfg):
    edge = cfg.get("edge443", {})
    if not edge.get("enabled"):
        raise SystemExit("edge443 is disabled")
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, cfg),
        host=edge.get("listen_host", "0.0.0.0"),
        port=int(edge.get("listen_port", 443)),
        backlog=512,
        reuse_address=True,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/revpn-shop/config.json")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    asyncio.run(main_async(config))
