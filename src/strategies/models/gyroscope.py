"""Gyroscope: Kalman drift estimator + Wald SPRT decision gate (H1).

Arsenal strategy #1 (docs/research/2026-07-12-novel-arsenal-brainstorm.md
sections 1 and 14). Consumes raw OHLC only -- no SMC columns, and no HTF
bias context: its own drift estimate IS its bias (the manifest's
honors_htf_bias: false exempts it from the controller's HTF filter, Task 6).

Emits the standard decision dict {signal, type: 'MARKET', price, sl, tp}.
Stop = k_sl * sqrt(S) in price space (the filter's own uncertainty), floored
at sl_atr_floor * ATR so it never undercuts the validated finding that tight
H1 stops die. tp = rr_target * risk (arms the existing partials ladder live).

Carried state per symbol: KalmanDrift instance, last-seen bar timestamp
(idempotency guard -- a re-fed bar is a no-op), cooldown counter. On first
sight of a symbol the whole window bootstraps the filter (mirrors live
warmup history); afterwards only strictly-newer bars are fed, and only a
crossing on the NEWEST bar may signal -- bootstrap crossings are history,
never traded.
"""
import math

from src.strategies.base_strategy import BaseStrategy
from src.analysis.kalman_drift import KalmanDrift
from src.analysis.atr_simple import last_atr


class GyroscopeStrategy(BaseStrategy):
    def __init__(self, config, logger):
        super().__init__("Gyroscope", config, logger)
        self.timeframe = str(config.get('timeframe', 'H1'))
        self.warmup_bars = int(config.get('warmup_bars', 200))
        self.q_atr_frac = float(config.get('q_atr_frac', 0.05))
        self.r_frac = float(config.get('r_frac', 1.0))
        sprt = config.get('sprt', {}) or {}
        self.alpha = float(sprt.get('alpha', 0.05))
        self.beta = float(sprt.get('beta', 0.20))
        self.delta = float(sprt.get('delta', 0.40))
        self.nis_window = int(config.get('nis_window', 50))
        # v2 (docs/research/2026-08-01-gyroscope2-gate.md): innovation-SPRT
        # mode + velocity confirmation + reachable NIS brake. Defaults keep
        # the v1 velocity mode bit-identical.
        self.sprt_on = str(config.get('sprt_on', 'velocity'))
        self.z_confirm = float(config.get('z_confirm', 0.0))
        nis_persist = config.get('nis_persist')
        self.nis_persist = None if nis_persist is None else int(nis_persist)
        self.k_sl = float(config.get('k_sl', 3.0))
        self.sl_atr_floor = float(config.get('sl_atr_floor', 0.8))
        self.rr_target = float(config.get('rr_target', 2.0))
        self.reentry_lockout = int(config.get('reentry_lockout', 5))
        self.max_spread_atr_frac = float(config.get('max_spread_atr_frac', 0.10))
        self.vol_floor = config.get('vol_floor')  # optional ATR band, absent = off
        self.vol_ceil = config.get('vol_ceil')

        self._filters = {}    # symbol -> KalmanDrift
        self._last_ts = {}    # symbol -> last fed bar's time string
        self._cooldown = {}   # symbol -> bars remaining in re-entry lockout

    def _filter_for(self, symbol):
        if symbol not in self._filters:
            self._filters[symbol] = KalmanDrift(
                warmup_bars=self.warmup_bars, q_atr_frac=self.q_atr_frac,
                r_frac=self.r_frac, alpha=self.alpha, beta=self.beta,
                delta=self.delta, nis_window=self.nis_window,
                sprt_on=self.sprt_on, z_confirm=self.z_confirm,
                nis_persist=self.nis_persist)
        return self._filters[symbol]

    async def analyze_tick(self, tick_data, history_df):
        return None

    async def on_new_candle(self, df, context=None):
        context = context or {}
        symbol = context.get('symbol', 'UNKNOWN')
        if not self.validate_data(df, min_length=self.warmup_bars, check_smc=False):
            return None
        if 'time' not in df.columns:
            return None  # carried-state strategy needs bar identity

        times = df['time'].astype(str).tolist()
        closes = df['close'].tolist()
        last_seen = self._last_ts.get(symbol)
        if last_seen is not None and times[-1] == last_seen:
            return None  # duplicate window: no-op

        # First index strictly newer than last_seen (0 on first sight).
        start_idx = 0
        if last_seen is not None:
            start_idx = len(times)
            for i in range(len(times) - 1, -1, -1):
                if times[i] <= last_seen:
                    start_idx = i + 1
                    break
                start_idx = i

        filt = self._filter_for(symbol)
        reading = None
        for i in range(start_idx, len(times)):
            atr_i = last_atr(df.iloc[:i + 1])
            reading = filt.update(math.log(closes[i]), atr_i)
        if reading is None:
            return None  # stale/older window: no bars fed, state untouched
        self._last_ts[symbol] = times[-1]

        # Cooldown ages once per newly-fed bar. A signal sets the counter to
        # reentry_lockout; the newest bar is still inside the lockout while
        # (counter - n_new) >= 0, i.e. a full reentry_lockout bars are blocked
        # and the earliest re-entry is lockout+1 bars after the signal.
        n_new = len(times) - start_idx
        cd = self._cooldown.get(symbol, 0) - n_new
        self._cooldown[symbol] = max(0, cd)

        if reading.state != "OBSERVE" or not reading.crossed or cd >= 0:
            return None

        atr = last_atr(df)
        if atr <= 0:
            return None
        if self.vol_floor is not None and atr < float(self.vol_floor):
            return None
        if self.vol_ceil is not None and atr > float(self.vol_ceil):
            return None
        spread = context.get('spread')
        if spread is not None and float(spread) > self.max_spread_atr_frac * atr:
            return None

        price = float(closes[-1])
        risk = max(self.k_sl * reading.sqrt_S_price, self.sl_atr_floor * atr)
        self._cooldown[symbol] = self.reentry_lockout
        self.log(f"{symbol} SPRT {reading.crossed} boundary crossing "
                 f"(v={reading.velocity:+.6f}, risk={risk:.5f})")
        if reading.crossed == "LONG":
            return {'signal': 'BUY', 'type': 'MARKET', 'price': price,
                    'sl': price - risk, 'tp': price + self.rr_target * risk}
        return {'signal': 'SELL', 'type': 'MARKET', 'price': price,
                'sl': price + risk, 'tp': price - self.rr_target * risk}
