#!/usr/bin/env python3
"""Telegram alert for a systemd unit that has entered `failed` (RS-RISK-01 MEDIUM-5).

Invoked by `OnFailure=titan-alert@%n.service`. Argument is the failed unit name.

DELIBERATELY DEPENDENCY-FREE: stdlib only, and it imports nothing from `src/`.
A failure notifier that shares code with the thing that failed is not a
notifier -- if the engine died on an import error or a broken venv, anything
reaching into `src.ops.telemetry` dies the same way and the operator hears
nothing. That silence is the whole finding: with StartLimitBurst=3 the live
unit can sit in `failed` indefinitely holding open positions, with no
break-even move, no partials, no trailing stop and no daily-drawdown breaker.

Reads TELEGRAM_TOKEN / TELEGRAM_CHAT_ID from the environment, falling back to
a plain parse of the repo's .env (no python-dotenv dependency).

Exit codes: 0 sent, 1 could not send (systemd records it in the journal;
nothing retries -- this is a best-effort last gasp, not a delivery guarantee).
"""
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _from_dotenv(key):
    """Minimal .env reader. Tolerates comments, blank lines, quotes, export."""
    env = REPO / ".env"
    if not env.is_file():
        return None
    try:
        for raw in env.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            name, _, value = line.partition("=")
            if name.strip() != key:
                continue
            return value.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _cfg(key):
    return os.environ.get(key) or _from_dotenv(key)


def main(argv):
    unit = argv[1] if len(argv) > 1 else "titan (unit unknown)"
    token, chat = _cfg("TELEGRAM_TOKEN"), _cfg("TELEGRAM_CHAT_ID")

    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    text = (
        f"\U0001F6D1 TITAN UNIT FAILED\n"
        f"unit: {unit}\n"
        f"host: {socket.gethostname()}\n"
        f"time: {stamp}\n\n"
        f"systemd has given up restarting it (StartLimitBurst reached) and it "
        f"will NOT come back on its own.\n\n"
        f"If this is the LIVE unit, positions may be open with no break-even "
        f"move, no partials, no trailing stop and no daily-drawdown breaker.\n\n"
        f"journalctl -u {unit} -n 100 --no-pager\n"
        f"systemctl reset-failed {unit} && systemctl start {unit}"
    )

    if not token or not chat:
        print(f"[ALERT] {unit} FAILED -- no TELEGRAM_TOKEN/TELEGRAM_CHAT_ID, "
              f"cannot notify. Message follows:\n{text}", file=sys.stderr)
        return 1

    payload = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            ok = 200 <= resp.status < 300
        # Never echo the token: this runs under systemd and lands in the journal.
        print(f"[ALERT] {unit}: telegram {'sent' if ok else 'rejected'}")
        return 0 if ok else 1
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        print(f"[ALERT] {unit}: telegram send failed: {e!r}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
