# ==============================================================================
# FILE: src/strategies/models/gambit.py
# Gambit — M5 session playbook chassis (spec 2026-08-02).
# Owns: session windows, pre-session range, one-intent-per-symbol-per-session,
# cost floor, live-spread guard, setup precedence (judas > reprise same-bar).
# Setup logic lives in gambit_setups.py (pure; shared with scripts/poc_gambit).
# Flat-by-close is NOT here: trade_management.time_exits.Gambit.flat_at_ny.
# ==============================================================================
from src.strategies.base_strategy import BaseStrategy
from src.analysis.time_math import TimeNormalizer
from src.strategies.models.gambit_setups import (
    compute_presession_range, detect_judas, detect_reprise)

_BAR_COLS = ("open", "high", "low", "close", "atr",
             "is_fvg_bull", "is_fvg_bear", "fvg_top", "fvg_bottom")
_TAIL = 320   # bars converted to NY per close: covers the 96-bar London range
              # plus a full session with margin; keeps per-close tz cost flat.


def _parse_min(hhmm):
    hh, mm = str(hhmm).split(":")
    return int(hh) * 60 + int(mm)


class Gambit(BaseStrategy):
    def __init__(self, config, logger):
        super().__init__("Gambit", config, logger)
        self.timeframe = str(config.get("timeframe", "M5"))
        self.rr = float(config.get("rr", 2.0))
        self.tz = TimeNormalizer(config.get("broker_gmt_offset", 2))
        self.sessions = {}
        for name, s in (config.get("sessions") or {}).items():
            self.sessions[name] = {
                "window": (_parse_min(s["window"][0]), _parse_min(s["window"][1])),
                "range": (_parse_min(s["range"][0]), _parse_min(s["range"][1])),
            }
        self.symbol_sessions = config.get("symbol_sessions") or {}
        self.setups = config.get("setups") or {}
        self.min_stop_price = config.get("min_stop_price") or {}
        self.max_spread_price = config.get("max_spread_price") or {}
        self._fired = {}   # (symbol, session, ny_date) -> True

    async def analyze_tick(self, tick_data, history_df):
        pass

    def _setup_cfg(self, key):
        c = self.setups.get(key) or {}
        if not c.get("enabled", False):
            return None
        return {"sweep_ttl_bars": int(c.get("sweep_ttl_bars", 12)),
                "body_min_atr": float(c.get("body_min_atr", 0.8)),
                "stop_buffer_atr": float(c.get("stop_buffer_atr", 0.2)),
                "rr": self.rr}

    async def on_new_candle(self, df, context=None):
        if not self.validate_data(df, min_length=100) or not context:
            return None
        symbol = context.get("symbol", "")
        try:
            hh, mm = context["ny_time"].split(":")[:2]
            now_min = int(hh) * 60 + int(mm)
        except (KeyError, ValueError, IndexError, AttributeError):
            return None

        session = None
        for name in self.symbol_sessions.get(symbol, []):
            s = self.sessions.get(name)
            if s and s["window"][0] <= now_min < s["window"][1]:
                session, sname = s, name
                break
        if session is None:
            return None

        tail = df.tail(_TAIL)
        ny_times = [self.tz.convert_broker_to_ny(t) for t in tail["time"]]
        key = (symbol, sname, ny_times[-1].date())
        if key in self._fired:
            return None

        spread = context.get("spread")
        cap = self.max_spread_price.get(symbol)
        if spread is not None and cap is not None and spread > cap:
            self.log(f"{symbol} skipped: live spread {spread} > cap {cap}")
            return None

        bars = {c: tail[c if c != "atr" else "ATR"].values for c in _BAR_COLS}
        bias = context.get("bias", "NEUTRAL")

        intent = None
        jcfg = self._setup_cfg("judas")
        if jcfg is not None:
            rng = compute_presession_range(
                ny_times, bars["high"], bars["low"],
                session["range"][0], session["range"][1])
            if rng is not None:
                intent = detect_judas(bars, ny_times, (rng[0], rng[1]),
                                      session["window"][0], bias, jcfg)
        if intent is None:
            rcfg = self._setup_cfg("reprise")
            if rcfg is not None:
                intent = detect_reprise(bars, bias, rcfg)
        if intent is None:
            return None

        # Cost floor: fail-safe if the symbol has no configured floor.
        floor = self.min_stop_price.get(symbol)
        risk = abs(intent["sl"] - intent["price"])
        if floor is None or risk < floor:
            self.log(f"{symbol} {intent['setup']} skipped: risk {risk:.5f} "
                     f"below cost floor {floor}")
            return None

        self._fired[key] = True
        if len(self._fired) > 64:      # prune stale session keys
            for k in sorted(self._fired, key=lambda k: str(k[2]))[:-32]:
                del self._fired[k]
        self.log(f"♟️ GAMBIT {intent['setup']} {intent['signal']} @ {intent['price']}")
        return intent
