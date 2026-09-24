"""Offline LIMIT/ratchet replay on explicit piecewise-linear BID OHLC paths.

No live imports or side effects. Prices are executable: BUY fills on ASK,
SELL on BID; longs exit on BID, shorts on ASK. Spread is not charged again.
R uses the planned entry-to-stop distance. Commission is a full round turn
per initial unit, including marked end-of-data tails. This is a continuous
path idealization, not a broker/tick/latency simulator.
"""
from dataclasses import dataclass
import math

import numpy as np

EXITS = ("fixed", "ratchet", "runner", "tight_runner")
PATHS = {"OHLC": ("open", "high", "low", "close"),
         "OLHC": ("open", "low", "high", "close")}


@dataclass
class Position:
    arm: str
    be_r: float = 0.0
    stop: float = -1.0
    stage: int = 0
    volume: float = 1.0
    realized: float = 0.0
    hwm: float = 0.0
    tightened: bool = False
    rejected_be: int = 0
    outcome: str = ""

    @property
    def running(self):
        return self.arm in ("runner", "tight_runner") and self.stage == 3

    @property
    def trail(self):
        return 0.2 if self.tightened else 0.536

    def finish(self, y, outcome):
        self.realized += self.volume * y
        self.volume = 0.0
        self.outcome = outcome

    def manage(self, y):
        """Immediate idealized management at executable oriented return y."""
        if self.arm == "fixed":
            return
        if self.stage < 1 and y >= 0.764:
            if self.be_r < y:
                self.stop = max(self.stop, self.be_r)
            else:
                # A stop beyond the current quote is not executable.
                self.rejected_be += 1
            self.stage = 1
        if self.stage < 2 and y >= 1.236:
            self.realized += self.volume * 0.3 * y
            self.volume *= 0.7
            self.stop = max(self.stop, 0.764)
            self.stage = 2
        if self.stage < 3 and y >= 1.772:
            self.realized += self.volume * 0.5 * y
            self.volume *= 0.5
            self.stop = max(self.stop, 1.236)
            self.stage = 3
            self.hwm = y
        if self.running:
            if (self.arm == "tight_runner" and not self.tightened
                    and self.hwm - y >= 0.75 * 0.536 - 1e-12):
                self.tightened = True
            self.hwm = max(self.hwm, y)
            self.stop = max(self.stop, y - self.trail)

    def opening_quote(self, y):
        """A gap jumps prices: broker SL/TP acts before software management."""
        if y <= self.stop:
            self.finish(y, "STOP")  # gap slippage is realized, not capped at -1R
        elif not self.running and y >= 2.0:
            self.finish(2.0, "TP")  # conservative: no favorable TP improvement
        else:
            self.manage(y)

    def segment(self, start, end):
        """Visit crossed events in price order; never reuse pre-entry extremes."""
        if self.outcome:
            return
        if end > start:
            if self.arm != "fixed":
                for stage, level in enumerate((0.764, 1.236, 1.772), 1):
                    if self.stage < stage and start <= level <= end:
                        self.manage(level)
            if not self.running and end >= 2.0:
                self.finish(2.0, "TP")
            else:
                self.manage(end)
        elif end < start:
            # Tightening occurs only if reached BEFORE the currently resting SL.
            trigger = self.hwm - 0.75 * 0.536
            if (self.running and self.arm == "tight_runner" and not self.tightened
                    and end <= trigger <= start and trigger > self.stop):
                self.manage(trigger)
            if end <= self.stop:
                self.finish(self.stop, "STOP")
            else:
                self.manage(end)


def validate_bars(bars):
    """Fail on unordered/nonfinite/malformed data rather than invent a path."""
    t = bars["time"]
    if len(t) == 0 or np.isnat(t).any() or (np.diff(t) <= np.timedelta64(0, "s")).any():
        raise ValueError("bars require nonempty, strictly increasing timestamps")
    for key in ("open", "high", "low", "close"):
        if len(bars[key]) != len(t) or not np.isfinite(bars[key]).all():
            raise ValueError(f"invalid {key}")
    if ((bars["high"] < np.maximum(bars["open"], bars["close"])).any()
            or (bars["low"] > np.minimum(bars["open"], bars["close"])).any()):
        raise ValueError("OHLC extremes do not contain open/close")


def replay_order(sig, bars, *, arm, path, spread, commission, be_buffer=0.0,
                 ttl_hours=12, signal_minutes=60, ttl_minutes=None,
                 max_hold_minutes=None, structure_contexts=None, tick_size=None):
    """Resolve a closed-bar signal on M5 open timestamps (legacy default H1).

    Limit gaps fill at requested price (no favorable price improvement).
    Resting orders expire after wall-clock TTL, exclusive of the boundary.
    Release time is the end of the exit M5 bar: H1 signals at that close can
    enter; intrabar release timing is deliberately not inferred.
    """
    if arm not in (*EXITS, 'structure') or path not in PATHS or sig["dir"] not in ("BUY", "SELL"):
        raise ValueError("invalid arm/path/direction")
    if arm == 'structure' and (structure_contexts is None or tick_size is None or tick_size <= 0):
        raise ValueError('structure replay needs causal contexts and tick size')
    entry = float(sig["entry"])
    risk = float(sig['risk'] if 'risk' in sig else sig['atr'])
    if (not all(math.isfinite(x) for x in (entry, risk, spread, commission, be_buffer))
            or risk <= 0 or min(spread, commission, be_buffer) < 0 or ttl_hours <= 0):
        raise ValueError("invalid price/risk/cost/TTL")
    side = 1 if sig["dir"] == "BUY" else -1
    duration = ttl_hours * 60 if ttl_minutes is None else ttl_minutes
    for value in (signal_minutes, duration, max_hold_minutes):
        if value is not None and (not math.isfinite(value) or value <= 0 or value % 5):
            raise ValueError('durations must be positive multiples of five minutes')
    created = np.datetime64(sig["time"], "ns") + np.timedelta64(int(signal_minutes), "m")
    if np.isnat(created):
        raise ValueError('signal timestamp must be valid')
    expiry = created + np.timedelta64(int(duration), "m")
    times = bars["time"]
    start = int(np.searchsorted(times, created))
    end_time = times[-1] + np.timedelta64(5, "m")
    pos = None
    fill_idx = None
    trigger = entry - spread if side == 1 else entry

    def eligible(bid):
        return bid <= trigger if side == 1 else bid >= trigger

    def y(bid):
        return side * (bid + (spread if side == -1 else 0.0) - entry) / risk

    def make_position(k):
        if arm == 'structure':
            from src.research.structure_execution import StructurePosition
            return StructurePosition(entry, risk, side, spread, tick_size,
                                     times[k] + np.timedelta64(5, 'm'), structure_contexts(k))
        return Position(arm, be_buffer / risk)

    def result(outcome, release, exit_idx=None):
        return {"time": str(sig["time"]), "dir": sig["dir"], "entry": entry,
                "risk": risk, "created": str(created), "release": str(release),
                "fill_idx": fill_idx, "exit_idx": exit_idx, "outcome": outcome,
                "gross_r": pos.realized if pos is not None else None,
                "net_r": pos.realized - commission / risk if pos is not None else None,
                "rejected_be": pos.rejected_be if pos is not None else 0}

    for k in range(start, len(times)):
        if pos is None and times[k] >= expiry:
            return result("EXPIRED", expiry)
        points = [float(bars[key][k]) for key in PATHS[path]]
        if arm == 'structure' and pos is not None:
            pos.context = structure_contexts(k)
        if (pos is not None and max_hold_minutes is not None
                and times[k] >= times[fill_idx] + np.timedelta64(int(max_hold_minutes), 'm')):
            quote = y(points[0])
            # Resting broker orders win at a gap; otherwise time-close before
            # software management or any extrema of this bar are observed.
            if quote <= pos.stop or (not pos.running and quote >= 2.0):
                pos.opening_quote(quote)
            else:
                pos.finish(quote, 'TIME_EXIT')
            return result(pos.outcome, times[k] + np.timedelta64(5, 'm'), k)
        if pos is None and eligible(points[0]):
            pos, fill_idx = make_position(k), k
        if pos is not None:
            pos.opening_quote(y(points[0]))
        for left, right in zip(points, points[1:]):
            if pos is not None and pos.outcome:
                break
            if pos is None:
                if not eligible(right):
                    continue
                pos, fill_idx = make_position(k), k
                # Start at the fill crossing, not the beginning of this segment.
                left = trigger
                pos.opening_quote(y(left))
            if not pos.outcome:
                pos.segment(y(left), y(right))
        if pos is not None and pos.outcome:
            return result(pos.outcome, times[k] + np.timedelta64(5, "m"), k)

    if pos is None:
        if end_time >= expiry:
            return result("EXPIRED", expiry)
        return result("PENDING_AT_END", max(created, end_time))
    pos.finish(y(float(bars["close"][-1])), "MARKED_AT_END")
    return result(pos.outcome, end_time, len(times) - 1)


def simulate(signals, bars, **kwargs):
    """One pending OR open position per symbol, scheduled separately per arm."""
    validate_bars(bars)
    rows, skipped = [], 0
    release = np.datetime64("1678-01-01", "ns")
    previous = release
    for sig in signals:
        created = (np.datetime64(sig["time"], "ns")
                   + np.timedelta64(int(kwargs.get('signal_minutes', 60)), "m"))
        if np.isnat(created):
            raise ValueError('signal timestamp must be valid')
        if created < previous:
            raise ValueError("signals must be chronological")
        previous = created
        if created < release:
            skipped += 1
            continue
        row = replay_order(sig, bars, **kwargs)
        rows.append(row)
        release = np.datetime64(row["release"], "ns")
    return rows, skipped
