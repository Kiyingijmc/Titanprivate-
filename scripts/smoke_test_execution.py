#!/usr/bin/env python
"""
Live execution smoke test for the v14.4 trade-management pipeline (ZMQ/EA).

Exercises, against the CURRENTLY LOGGED-IN terminal (run on demo!):
  1. PING handshake
  2. GET_HISTORY -> bars + broker specs
  3. MARKET BUY (default 0.02 lots) with wide SL/TP (percentage-based)
  4. MODIFY SL/TP over the reliable REQ socket (TRADE/cmd=MODIFY)
  5. Partial close half via CLOSE_POS + volume   (needs the v14.4 EA)
  6. Full close of the remainder

Run ONLY when main.py is NOT running (same ZMQ ports).
Usage:
  .venv/bin/python scripts/smoke_test_execution.py                 # EURUSD (weekdays)
  .venv/bin/python scripts/smoke_test_execution.py --symbol BTCUSD # weekends
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.execution.bridge_zmq import ZMQBridge  # noqa: E402

SL_PCT = 0.005   # stop 0.5% below entry: far enough on any asset
TP_PCT = 0.010   # target 1% above


class Monitor:
    """Drains the PULL socket and keeps the latest known state."""
    def __init__(self, bridge, symbol):
        self.bridge = bridge
        self.symbol = symbol
        self.last_bid = 0.0
        self.positions = []          # from last HEARTBEAT
        self.executions = []         # EXECUTION messages
        self.history_specs = None    # (tv, ts, vm, vs)
        self.bars = 0

    async def pump(self, seconds):
        loop = asyncio.get_event_loop()
        end = loop.time() + seconds
        while loop.time() < end:
            for m in await self.bridge.poll_data():
                if not isinstance(m, dict):
                    continue
                t = m.get("type")
                if t == "TICK" and m.get("s") == self.symbol:
                    self.last_bid = float(m.get("b", 0))
                elif t == "HEARTBEAT":
                    self.positions = m.get("pos", [])
                elif t == "EXECUTION":
                    self.executions.append(m)
                elif t == "HISTORY" and m.get("symbol") == self.symbol:
                    self.history_specs = (m.get("tv"), m.get("ts"), m.get("vm"), m.get("vs"))
                    self.bars = len(m.get("data") or [])
            await asyncio.sleep(0.05)

    def my_position(self):
        for p in self.positions:
            if p.get("s") == self.symbol:
                return p
        return None

    async def wait_for(self, predicate, timeout, what):
        loop = asyncio.get_event_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            await self.pump(0.5)
            v = predicate()
            if v:
                return v
        raise TimeoutError(f"Timed out waiting for {what}")


def report(step, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {step}" + (f" — {detail}" if detail else ""))
    return ok


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD",
                    help="use BTCUSD on weekends (forex closed)")
    ap.add_argument("--lots", type=float, default=0.02,
                    help="total volume; half is partially closed")
    args = ap.parse_args()
    symbol, lots = args.symbol, args.lots
    partial = round(lots / 2, 2)

    print(f"v14.4 EXECUTION SMOKE TEST on {symbol} {lots} lots (demo terminal).")
    print("Ctrl+C aborts; cleanup closes the position.\n")
    bridge = ZMQBridge()
    mon = Monitor(bridge, symbol)
    results = []
    ticket = None

    def snap(price, ts):
        """Round to the broker tick grid using the specs from HISTORY."""
        ts = float(ts) if ts else 0.00001
        steps = round(price / ts)
        p = steps * ts
        return round(p, max(0, len(f"{ts:.10f}".rstrip('0').split('.')[-1])))

    try:
        # 1. Handshake
        pong = await bridge.ping()
        results.append(report("PING handshake", pong))
        if not pong:
            return 1

        # 2. History + specs
        await bridge.send_command("GET_HISTORY", {"symbol": symbol, "tf": "M5", "count": 50})
        await mon.wait_for(lambda: mon.history_specs, 15, "HISTORY + specs")
        tv, ts, vm, vs = mon.history_specs
        results.append(report("HISTORY + broker specs", mon.bars > 0,
                              f"{mon.bars} bars, tv={tv} ts={ts} vm={vm} vs={vs}"))

        # Need a live price for SL/TP
        await mon.wait_for(lambda: mon.last_bid > 0, 15, f"{symbol} tick")
        bid = mon.last_bid
        sl = snap(bid * (1 - SL_PCT), ts)
        tp = snap(bid * (1 + TP_PCT), ts)

        # 3. Market order (graceful FAIL if the broker rejects, e.g. market closed)
        ok = await bridge.send_order_reliable({
            "action": "TRADE", "symbol": symbol, "cmd": "MARKET", "side": "BUY",
            "price": bid, "sl": sl, "tp": tp, "volume": lots,
            "magic": 88000, "comment": "SmokeTest", "strat": "SmokeTest"})
        if not ok:
            results.append(report("MARKET BUY execution", False,
                                  "broker rejected (market closed? check EA Experts log)"))
            raise SystemExit(1)
        pos = await mon.wait_for(mon.my_position, 20, "position in HEARTBEAT")
        ticket = int(pos["t"])
        results.append(report("MARKET BUY execution", ticket > 0,
                              f"ticket #{ticket} vol={pos['vol']} entry={pos['p']}"))

        # 4. MODIFY via fire-and-forget PUSH (v14.4.1 architecture: the live
        # ratchet uses this exact path; result is verified from the HEARTBEAT,
        # never a synchronous ack — a slow SLTP round-trip once wedged the
        # REQ/REP socket for good).
        new_sl = snap(bid * (1 - SL_PCT * 0.8), ts)
        new_tp = snap(bid * (1 + TP_PCT * 1.2), ts)
        await bridge.send_command("MODIFY", {"ticket": ticket, "symbol": symbol,
                                             "sl": new_sl, "tp": new_tp})
        # Tolerance covers the pre-v14.4 EA's %G heartbeat (6 significant digits,
        # i.e. up to ~0.5 error at BTC prices) as well as the tick grid.
        tol = max(float(ts), abs(new_sl) * 1e-5)
        try:
            pos = await mon.wait_for(
                lambda: (p := mon.my_position()) and abs(float(p.get("sl", 0)) - new_sl) <= tol and p,
                25, "modified SL in HEARTBEAT")
            results.append(report("MODIFY SL/TP via PUSH", True,
                                  f"sl={pos['sl']} tp={pos['tp']} (heartbeat-verified)"))
        except TimeoutError:
            p = mon.my_position()
            results.append(report("MODIFY SL/TP via PUSH", False,
                                  f"SL unchanged in heartbeat (now {p.get('sl') if p else '?'}, "
                                  f"wanted {new_sl}) — check Experts log for 'Modify'"))

        # 5. Partial close (v14.4 EA feature)
        await bridge.send_command("CLOSE_POS", {"ticket": ticket, "volume": partial})
        try:
            pos = await mon.wait_for(
                lambda: (p := mon.my_position()) and abs(float(p.get("vol", 0)) - (lots - partial)) < 1e-9 and p,
                20, "reduced volume in HEARTBEAT")
            results.append(report("PARTIAL close via CLOSE_POS+volume", True,
                                  f"remaining vol={pos['vol']}"))
        except TimeoutError:
            p = mon.my_position()
            if p is None:
                results.append(report("PARTIAL close via CLOSE_POS+volume", False,
                                      "position fully closed -> OLD EA still running (recompile needed)"))
                ticket = None
            else:
                results.append(report("PARTIAL close via CLOSE_POS+volume", False,
                                      f"volume unchanged ({p['vol']}) -> partial ignored"))

        # 6. Full close of whatever remains
        if mon.my_position() is not None:
            await bridge.send_command("CLOSE_POS", {"ticket": ticket})
            await mon.wait_for(lambda: mon.my_position() is None, 20, "flat in HEARTBEAT")
            results.append(report("FULL close", True, "flat"))
            ticket = None

        closes = [e for e in mon.executions if e.get("status") == "CLOSED"]
        pnl = sum(float(e.get("pn", 0)) for e in closes)
        print(f"\nEXECUTION events seen: {len(mon.executions)} "
              f"(CLOSED: {len(closes)}, total PnL ${pnl:.2f})")
        print(f"\n{'✅ ALL STEPS PASSED' if all(results) else '❌ SOME STEPS FAILED'} "
              f"({sum(results)}/{len(results)})")
        return 0 if all(results) else 1

    except TimeoutError as e:
        print(f"\n[ABORT] {e}")
        return 1
    finally:
        # Safety net: never leave the smoke-test position open
        if ticket is not None and mon.my_position() is not None:
            print("[CLEANUP] closing leftover smoke-test position...")
            await bridge.send_command("CLOSE_POS", {"ticket": ticket})
            try:
                await mon.wait_for(lambda: mon.my_position() is None, 15, "cleanup close")
                print("[CLEANUP] flat.")
            except TimeoutError:
                print(f"[CLEANUP] ⚠️ could not confirm close of #{ticket} — check the terminal!")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
