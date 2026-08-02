#!/usr/bin/env python3
# scripts/cancel_pending_retry.py
# Re-issue a cancel for an untracked pending order once its market reopens.
#   .venv/bin/python scripts/cancel_pending_retry.py <ticket> [--open-at HH:MM] [--now]
"""Retry + verify a CANCEL that the broker refused while the market was shut.

Why this exists: CANCEL is fire-and-forget on the PUSH socket, so an EA-side
reject (e.g. retcode 10018 TRADE_RETCODE_MARKET_CLOSED over the weekend) never
reaches Python — the control API reports success and the `active_orders` row is
deleted anyway, orphaning a live order at the broker with no DB row and no `sl`.
That is audit finding EXIT-03; until it is fixed, a refused cancel needs a human
or this script.

The only trustworthy confirmation is the order disappearing from the heartbeat,
so that is what this polls. It drives the bot's control API on :8770 rather than
the ZMQ sockets, so it does not contend for the bound ports — but it does need
the bot to be running.

First used 2026-08-02 for the orphaned EURUSD SELL LIMIT 1936559060.
"""
import argparse
import json
import os
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
API = os.environ.get("TITAN_GUI_URL", "http://127.0.0.1:8770")
LOG = os.path.join(ROOT, "data/logs/cancel_pending_retry.log")
MAX_ATTEMPTS = 24
INTERVAL_S = 300


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n"
    with open(LOG, "a") as fh:
        fh.write(line)
    print(line, end="", flush=True)


def token():
    with open(os.path.join(ROOT, ".env")) as fh:
        for line in fh:
            if line.startswith("TITAN_GUI_TOKEN"):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError("TITAN_GUI_TOKEN not in .env")


def call(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data,
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def still_resting(ticket):
    return any(o["ticket"] == ticket for o in call("/api/state").get("orders", []))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ticket", type=int, help="broker ticket of the resting order")
    ap.add_argument("--open-at", default="22:05",
                    help="UTC HH:MM to wake at (default 22:05, just after the Sunday FX open)")
    ap.add_argument("--now", action="store_true", help="skip the wait and retry immediately")
    args = ap.parse_args()

    if not args.now:
        hh, mm = (int(x) for x in args.open_at.split(":"))
        now = time.gmtime()
        delay = (hh * 3600 + mm * 60) - (now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec)
        if delay < 0:
            delay += 86400
        log(f"armed: sleeping {delay}s until ~{args.open_at} UTC to retry cancel of {args.ticket}")
        time.sleep(delay)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if not still_resting(args.ticket):
                log(f"attempt {attempt}: order {args.ticket} is gone — nothing to do, exiting")
                return
            result = call("/api/command", {"command": "cancel", "ticket": args.ticket})
            log(f"attempt {attempt}: sent cancel -> {result}")
            time.sleep(20)
            if not still_resting(args.ticket):
                log(f"attempt {attempt}: CONFIRMED — {args.ticket} no longer in the book")
                return
            log(f"attempt {attempt}: still resting (broker likely refused); retrying")
        except Exception as exc:                       # bot down, socket refused, etc.
            log(f"attempt {attempt}: error {exc!r}")
        time.sleep(INTERVAL_S)

    log(f"gave up after {MAX_ATTEMPTS} attempts — {args.ticket} still resting, needs a human")


if __name__ == "__main__":
    main()
