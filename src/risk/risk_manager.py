# ==============================================================================
# FILE: src/risk/risk_manager.py
# TYPE: PRECISION UPDATE (Math & Risk)
# AUDIT: 
#   1. Replaced log10 rounding with Step-Quantization (Fixes US30/SPX 0.25 ticks).
#   2. Prioritized Dynamic TickValue/TickSize over hardcoded string fallbacks.
#   3. Added Input Validation for Broker Specs to prevent Division-by-Zero.
# STATUS: PRODUCTION READY
# ==============================================================================

import math
from decimal import Decimal
from src.utils.instrument import InstrumentHelper

class RiskManager:
    """
    Version 14.3 Institutional Risk Engine.
    
    AUDIT UPGRADE:
    - Implements Quantized Price Normalization (Supports non-power-of-10 ticks).
    - Enforces Broker-Specific Contract Specs over Generic Fallbacks.
    """
    def __init__(self, config, logger=None):
        self.config = config['risk']
        self.logger = logger  # optional AuditLogger; used to surface skipped trades
        
        # Original oper.txt constants
        self.max_dd = self.config['account']['max_daily_drawdown_pct']
        self.risk_pct = self.config['trade']['risk_per_trade_pct']
        self.hard_max_lots = self.config['trade'].get('hard_max_lots', 5.0)
        self.comm_per_lot = self.config['trade'].get('static_commission_usd', 7.0)
        
        # State Management
        self.starting_balance = 0.0
        self.current_equity = 0.0
        self.day_start_equity = 0.0  # daily DD anchor; re-set by reset_daily_metrics
        # True only between restore_daily_anchor() and the first heartbeat
        # that can corroborate it (RS-RISK-01 MEDIUM-2).
        self._anchor_needs_corroboration = False
        self.symbol_specs = {}
        # Set by aggregate_open_risk when it returns None: the row that made
        # the book un-computable, so the operator halt alert can name it
        # (a book-wide block the operator can't locate is not actionable).
        self.last_uncomputable_row = None
        
        # V14 Reporting Metrics (For 11:45 PM Uganda Report)
        self.equity_max = 0.0
        self.equity_min = float('inf')

    # RS-RISK-01 MEDIUM-2. A restored anchor comes off DISK, so it is an
    # externally-sourced number controlling a safety limit -- the same class of
    # input as the broker specs above, which are bounded rather than trusted.
    # A tiny positive anchor (0.01) makes pnl_pct enormously positive, so
    # check_can_trade() returns True forever and throttle_factor() returns 1.0:
    # the 3% breaker and the throttle are BOTH off for the whole day, and the
    # value survives restarts. `> 0` alone does not catch that.
    #
    # A real trading day cannot move equity by this factor -- the breaker halts
    # at 3% long before -- so a breach means corruption, not a bad day. Wide
    # enough that a genuine catastrophic day is never mistaken for corruption.
    MAX_ANCHOR_EQUITY_RATIO = 20.0

    def update_account_info(self, balance, equity):
        """Standard oper.txt logic: Permanent lock of starting balance on init"""
        if self.starting_balance == 0 and balance > 0:
            self.starting_balance = balance
        if self.day_start_equity == 0 and equity > 0:
            self.day_start_equity = equity
        elif self._anchor_needs_corroboration and equity > 0:
            # First heartbeat after a restore: this is the earliest moment a
            # persisted anchor can be checked against reality, because at boot
            # there is no equity to compare it with.
            self._anchor_needs_corroboration = False
            anchor = self.day_start_equity
            if anchor > 0:
                ratio = max(anchor / equity, equity / anchor)
                if ratio > self.MAX_ANCHOR_EQUITY_RATIO:
                    # Fail CLOSED: fall back to anchoring from live equity (the
                    # pre-RISK-01 behaviour) rather than keeping a value that
                    # would switch the breaker off entirely.
                    self.day_start_equity = equity
                    if self.logger:
                        self.logger.log_event(
                            "RISK", "ANCHOR",
                            f"Rejected restored DD anchor {anchor!r}: {ratio:.4g}x "
                            f"from live equity {equity} (max {self.MAX_ANCHOR_EQUITY_RATIO}x). "
                            f"Re-anchored to {equity} -- the breaker would otherwise "
                            f"have been disabled for the whole day.",
                            {"rejected": anchor, "equity": equity, "ratio": ratio})

        self.current_equity = equity
        self.track_equity(equity)

    def restore_daily_anchor(self, equity):
        """Prime today's DD anchor from persisted state, before any heartbeat.

        RISK-01: day_start_equity was in-memory only, so every restart re-set it
        to whatever equity the first post-boot heartbeat reported -- discarding
        the day's realised drawdown and granting a fresh allowance. The caller
        (SystemController, at boot) supplies the anchor persisted earlier today.

        Once restored the anchor is non-zero, so update_account_info's existing
        `if self.day_start_equity == 0` guard declines to re-anchor. The fix is
        to prime that guard before the first heartbeat, not to add a second one.

        No I/O here on purpose: RiskManager stays a pure class that ~10 test
        modules construct from a bare config dict. Storage is StateManager's job.

        A non-positive or unusable value is a NO-OP, not a coercion: a corrupt
        persisted row must leave the existing first-heartbeat path intact rather
        than anchor the breaker to nonsense.
        """
        try:
            value = float(equity)
        except (TypeError, ValueError):
            return
        if math.isfinite(value) and value > 0:
            self.day_start_equity = value
            self._anchor_needs_corroboration = True

    def track_equity(self, equity):
        """V14 Feature: Tracks intraday range for the Ugandan Report"""
        if equity > self.equity_max: self.equity_max = equity
        if equity < self.equity_min: self.equity_min = equity

    # SEC-05 / OPS-07: broker-plausible envelopes for the two spec fields the
    # sizing math divides by. They are deliberately wide -- they do not encode
    # any symbol's true values, they only bracket what a real MT5 quote can be
    # (1e-6 covers 5-digit forex ticks, 100 covers whole-unit index ticks).
    # 'vm'/'vs' have no upper bound; a broker may legitimately require large
    # lots. They only have to be positive so the volume math cannot divide by 0.
    SPEC_BOUNDS = {'val': (1e-4, 1e4), 'ts': (1e-6, 100.0)}

    # A real symbol regrade (4-digit -> 5-digit forex) moves a field by exactly
    # 10x. More than that is a corrupt or hostile frame, not a spec change.
    MAX_SPEC_JUMP = 10.0

    def update_symbol_specs(self, symbol, val, size, v_min, v_step):
        """
        Receives precise contract details from MQL5.

        SEC-05: these arrive on an UNAUTHENTICATED socket, and every trade is
        sized off them. A single bad HISTORY frame -- hostile, or a broker
        misquoting tick_value after a symbol-spec change -- drives
        ticks_at_risk towards 0, blows every subsequent trade out to
        hard_max_lots against an intended 1% risk, and has risk_to_stop
        validate it as safe off the same poisoned numbers. So an update is
        sanity-bounded, and a rejected one is a NO-OP: previously accepted
        specs stay put, and a symbol that never had accepted specs stays
        spec-less so calculate_lot_size keeps failing safe to 0. Never coerce
        a bad value into the store -- half-good specs size real trades.
        """
        incoming = {'val': val, 'ts': size, 'vm': v_min, 'vs': v_step}
        clean = {}

        for field, raw in incoming.items():
            try:
                num = float(raw)
            except (TypeError, ValueError):
                return self._reject_specs(symbol, field, raw, "not a number")
            if not math.isfinite(num):
                return self._reject_specs(symbol, field, raw, "not finite")

            bounds = self.SPEC_BOUNDS.get(field)
            if bounds is None:
                if num <= 0:
                    return self._reject_specs(symbol, field, raw, "must be > 0")
            elif not (bounds[0] <= num <= bounds[1]):
                return self._reject_specs(
                    symbol, field, raw, f"outside [{bounds[0]}, {bounds[1]}]")

            clean[field] = num

        # Jump guard, measured against the last ACCEPTED specs only -- a
        # rejected frame must never become the baseline, or two bad messages
        # in a row can walk the specs anywhere they like.
        prior = self.symbol_specs.get(symbol)
        if prior:
            for field, num in clean.items():
                was = prior.get(field, 0.0)
                if was <= 0:
                    continue
                ratio = max(num / was, was / num)
                # +epsilon so an exactly-10x regrade survives float rounding.
                if ratio > self.MAX_SPEC_JUMP * (1 + 1e-9):
                    # incoming[field], NOT `raw`: `raw` is the loop variable
                    # from the validation pass above and by now holds the LAST
                    # field's value, so it would name the jumping field beside
                    # an unrelated (healthy) number.
                    return self._reject_specs(
                        symbol, field, incoming[field],
                        f"{ratio:.4g}x jump from last accepted {was}")

        self.symbol_specs[symbol] = clean

    def _reject_specs(self, symbol, field, value, reason):
        """Drop a spec update and tell the operator which field poisoned it.

        A silent reject is indistinguishable from a symbol that simply never
        got specs -- and the visible symptom of both is 'that pair stopped
        trading', so the message has to name symbol + field + value.
        """
        if self.logger:
            self.logger.log_event(
                "RISK", "SPECS",
                f"Rejected {symbol} spec update: {field}={value!r} ({reason}). "
                f"Keeping previously accepted specs.",
                {"symbol": symbol, "field": field, "value": repr(value), "reason": reason},
            )

    def normalize_price(self, price, symbol):
        """
        AUDIT FIX: Quantization Approach.
        Replaced brittle 'log10' logic with math.round(price / tick_size) * tick_size.
        This correctly handles Steps like 0.25 (Indices) or 0.05.
        """
        if price is None or price <= 0: return 0.0
        price = float(price)
        
        spec = self.symbol_specs.get(symbol)
        if spec and spec['ts'] > 0:
            tick_size = spec['ts']
            # Quantize: Snap to nearest grid step
            steps = round(price / tick_size)
            normalized = steps * tick_size
            
            # Format to correct decimal places to avoid float artifacts (e.g. 1.20000001)
            # We calculate required precision based on the tick size string logic or log10 just for formatting
            precision = 0
            if tick_size < 1:
                # Count decimal places via Decimal's exponent. This handles
                # sub-0.0001 ticks (e.g. 5-digit forex 0.00001) that Python
                # renders in scientific notation ("1e-05"), which the previous
                # str().split('.') logic could not parse (see boot_crash.log).
                precision = max(0, -Decimal(str(tick_size)).as_tuple().exponent)

            return round(normalized, precision)
        
        # Fallback to InstrumentHelper if no specs from Broker
        return InstrumentHelper.normalize_price(price, InstrumentHelper.get_pip_size(symbol))

    def check_can_trade(self) -> bool:
        """
        Daily Drawdown Circuit Breaker.
        Anchored to TODAY's starting equity (reset by reset_daily_metrics), so
        the limit stays a true intraday guard as the account compounds, instead
        of drifting against the boot-time balance.
        """
        anchor = self.day_start_equity if self.day_start_equity > 0 else self.starting_balance
        if anchor == 0: return True
        if anchor < 0: return False

        pnl_pct = (self.current_equity - anchor) / anchor * 100
        return pnl_pct > -self.max_dd

    def get_max_risk_amount(self, bias_multiplier=1.0):
        """V14 Enhancement: Integrated Bias Multiplier (0.5x for Neutral)"""
        if self.current_equity == 0: return 0.0
        base_risk = self.current_equity * (self.risk_pct / 100.0)
        return base_risk * bias_multiplier

    def calculate_lot_size(self, entry, sl, symbol, htf_bias="NEUTRAL", risk_mult=1.0) -> float:
        """
        FULL POSITION SIZER.
        Sizes from broker tick_value/tick_size (any asset class); includes Net
        Risk Adjustment and Hard Caps. Fails safe (returns 0) without specs.

        risk_mult: v15.2 drawdown-throttle multiplier (default 1.0 = no-op,
        byte-identical sizing). Applied to the risk amount BEFORE the lot math
        so vol_step normalization at the end still applies to the throttled
        size, not tacked on afterward.
        """
        # 1. Circuit Breaker
        if not self.check_can_trade():
            return 0.0

        # 2. Bias Shield (V14 Feature)
        multiplier = 1.0 if htf_bias != "NEUTRAL" else 0.5
        raw_risk_money = self.get_max_risk_amount(bias_multiplier=multiplier) * risk_mult

        entry = float(entry); sl = float(sl)
        diff = abs(entry - sl)
        if diff == 0: return 0.0

        # 3. BROKER-SPEC SIZING (the only correct, asset-agnostic path).
        # Sizing requires real tick_value/tick_size from MT5. If they have not
        # arrived for this symbol we FAIL SAFE -- skip the trade rather than guess
        # with forex-shaped assumptions, which silently mis-sized non-forex assets
        # (gold/oil collapsed to 0 lots; indices mis-scaled). See test_risk_manager_sizing.
        spec = self.symbol_specs.get(symbol)
        if not (spec and spec['val'] > 0 and spec['ts'] > 0):
            if self.logger:
                self.logger.log_event(
                    "RISK", "SIZING",
                    f"No broker specs for {symbol}; skipping trade (cannot size safely)."
                )
            return 0.0

        # MT5 TickValue is the account-currency P/L of a 1.0-lot, 1-tick move,
        # so this sizes any asset class the broker prices correctly.
        ticks_at_risk = diff / spec['ts']
        money_loss_per_lot = ticks_at_risk * spec['val']
        lots_gross = raw_risk_money / money_loss_per_lot if money_loss_per_lot > 0 else 0.0

        # Volume constraints (guard against a broker reporting 0 to avoid /0).
        min_vol = spec['vm'] if spec['vm'] > 0 else 0.01
        vol_step = spec['vs'] if spec['vs'] > 0 else 0.01

        # 5. RESTORED NET RISK ADJUSTMENT (The 2-Step Solver)
        # Calculates "True" risk by accounting for Commission drag
        adjusted_lots = 0.0
        if lots_gross > 0:
            estimated_comm = lots_gross * self.comm_per_lot
            
            # Only adjust if comm is significant, otherwise simple math
            if estimated_comm < (raw_risk_money * 0.5):
                # Reverse engineering ValuePerLot from Gross
                # Risk = (Lots * ValPerLot) + (Lots * Comm)
                # Risk = Lots * (ValPerLot + Comm)
                # Lots = Risk / (ValPerLot + Comm)
                
                value_per_lot = raw_risk_money / lots_gross
                adjusted_lots = raw_risk_money / (value_per_lot + self.comm_per_lot)
            else:
                adjusted_lots = lots_gross

        # 6. SAFETY HARD CAPS & STEP ROUNDING
        if adjusted_lots > self.hard_max_lots: 
            adjusted_lots = self.hard_max_lots
            
        if adjusted_lots < min_vol: 
            return 0.0
        
        # Precision Floor Math to match VolStep
        lots = math.floor(adjusted_lots / vol_step) * vol_step
        return round(lots, 2)

    def throttle_factor(self) -> float:
        """v15.2 config-gated drawdown throttle.

        Config (config.yaml `risk.drawdown_throttle`):
            enabled: false          # default OFF -> always returns 1.0
            trigger_dd_pct: 2.0     # intraday drawdown pct (vs day-start equity)
            factor: 0.5             # risk multiplier once triggered

        Reuses the same day_start_equity anchor as check_can_trade() (reset
        daily by reset_daily_metrics). Returns 1.0 (no throttle) whenever
        disabled, un-anchored, or below the trigger threshold.
        """
        cfg = self.config.get('drawdown_throttle', {})
        if not cfg.get('enabled', False):
            return 1.0

        anchor = self.day_start_equity if self.day_start_equity > 0 else self.starting_balance
        if anchor <= 0:
            return 1.0

        trigger_pct = cfg.get('trigger_dd_pct', 2.0)
        dd_pct = (anchor - self.current_equity) / anchor * 100.0
        if dd_pct >= trigger_pct:
            return cfg.get('factor', 0.5)
        return 1.0

    def has_specs(self, symbol) -> bool:
        """True when real broker tick_value/tick_size are loaded for this symbol."""
        spec = self.symbol_specs.get(symbol)
        return bool(spec and spec['val'] > 0 and spec['ts'] > 0)

    def money_for_move(self, symbol, price_distance, lots) -> float:
        """Account-currency value of a `price_distance` move at `lots`, from broker specs.

        Mirrors calculate_lot_size's spec discipline: without real tick_value/tick_size
        it returns 0.0 (caller treats 0.0 as 'unknown') rather than guessing.
        """
        spec = self.symbol_specs.get(symbol)
        if not (spec and spec['val'] > 0 and spec['ts'] > 0):
            return 0.0
        try:
            ticks = abs(float(price_distance)) / spec['ts']
            return ticks * spec['val'] * float(lots)
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.0

    def risk_to_stop(self, symbol, price_distance, lots) -> float:
        """Risk-to-stop of `lots` over `price_distance`, NET of commission drag.

        money_for_move is gross P/L only, but calculate_lot_size sizes each
        trade net of commission (the 2-step solver above). Comparing gross
        figures against a cap derived from net-risk sizing would let the
        portfolio gate admit `lots x comm_per_lot` more true risk than
        configured on every row -- a systematic bias in the permissive
        direction, in the one component whose job is to be conservative. Adding
        the commission back keeps the cap and the sizer in the same units.

        Returns money_for_move's 0.0 'unknown' sentinel when specs are missing.
        """
        gross = self.money_for_move(symbol, price_distance, lots)
        if gross <= 0.0:
            return 0.0
        try:
            return gross + abs(float(lots)) * self.comm_per_lot
        except (TypeError, ValueError):
            return 0.0

    def _row_risk(self, symbol, entry, sl, lots):
        """Risk-to-stop for one book row, or None when un-computable."""
        try:
            entry = float(entry or 0.0)
            sl = float(sl or 0.0)
            lots = float(lots or 0.0)
        except (TypeError, ValueError):
            return None

        if entry == 0.0 or sl == 0.0 or lots == 0.0:
            return None

        risk = self.risk_to_stop(symbol, abs(entry - sl), lots)
        return None if risk <= 0.0 else risk

    def aggregate_open_risk(self, open_positions, pending_orders=None):
        """Total account-currency risk-to-stop across the whole committed book.

        Feeds the portfolio-wide cap (ExposureManager.check_total_risk). Two
        sources, because an order is committed risk long before it fills:

          * `open_positions` -- heartbeat rows carrying `t`/`s`/`p`/`sl`/`vol`
            (Titan_Gateway.mq5:194).
          * `pending_orders` -- StateManager.get_pending_orders() rows for
            resting LIMIT/STOP entries, carrying `ticket_id`/`symbol`/
            `initial_entry`/`initial_sl`/`lots`. These MUST be counted: the only
            approved strategy (SilverBullet) enters on LIMIT, and a resting
            limit lives up to 12 bars of its timeframe before ghost cleanup
            cancels it, so the normal state of the live book is "several limits
            resting, none filled yet" -- exactly the state in which a
            positions-only aggregate reads 0.0 and waves everything through.
            (The heartbeat's own `orders` rows are NOT a usable source: the EA
            emits them as `t,s,p,type,vol` with no `sl`, Titan_Gateway.mq5:225.
            Consequence: a pending order placed MANUALLY in MT5 has no DB row
            and cannot be priced, so it is NOT counted — unlike a manual
            stopless *position*, which halts the book. Closing that asymmetry
            needs an EA change.)

        Rows are de-duplicated by ticket: between a limit filling and the next
        heartbeat's backfill flipping the DB row PENDING->ACTIVE, the same trade
        appears in both lists, and counting it twice would over-block.

        Returns None -- "un-computable", callers must BLOCK -- when any single
        row's risk is unknown, following the same fail-safe discipline as
        calculate_lot_size (never guess a risk number):
          * sl == 0: a stopless position (e.g. opened outside Titan) has no
            defined risk-to-stop, and skipping it would understate the book.
          * money_for_move returns its 0.0 'no specs' sentinel: counting that
            as $0 of risk would silently hide a real position.

        Note this is deliberately conservative for ratcheted trades: abs()
        means a stop moved past entry (BE+) reads as risk rather than as
        locked-in profit, so the aggregate over-states rather than under-states.
        """
        total = 0.0
        open_tickets = set()
        self.last_uncomputable_row = None

        for pos in open_positions or []:
            try:
                ticket = int(pos.get('t', 0) or 0)
            except (TypeError, ValueError):
                ticket = 0
            if ticket:
                open_tickets.add(ticket)

            risk = self._row_risk(pos.get('s', ''), pos.get('p'),
                                  pos.get('sl'), pos.get('vol'))
            if risk is None:
                self.last_uncomputable_row = {
                    'ticket': ticket, 'symbol': pos.get('s', ''), 'source': 'position'}
                return None
            total += risk

        for row in pending_orders or []:
            try:
                ticket = int(row.get('ticket_id', 0) or 0)
            except (TypeError, ValueError):
                ticket = 0
            if ticket and ticket in open_tickets:
                continue  # already counted above as the filled position

            risk = self._row_risk(row.get('symbol', ''), row.get('initial_entry'),
                                  row.get('initial_sl'), row.get('lots'))
            if risk is None:
                self.last_uncomputable_row = {
                    'ticket': ticket, 'symbol': row.get('symbol', ''), 'source': 'pending'}
                return None
            total += risk

        return total

    def roll_daily_anchor(self):
        """New trading day: re-anchor the DD breaker, or INVALIDATE it.

        RS-RISK-01 MAJOR-1. Sets day_start_equity to live equity when known.
        When equity is NOT yet known -- restarted across the day boundary with
        no heartbeat in yet -- it zeroes the anchor instead of leaving
        yesterday's in place, so update_account_info's `== 0` guard anchors
        fresh on the first heartbeat. Keeping the stale value is precisely what
        let a previous day's anchor be written under the NEW day's key and then
        restored on every restart for the rest of that day, handing back a
        larger loss allowance than intended -- the failure class RISK-01 exists
        to kill.

        Deliberately does NOT touch equity_max/equity_min. Those are the daily
        report's range trackers and reset_daily_metrics owns them; the rollover
        fires just before the 23:45 report in the same loop iteration, so
        clearing them here would make the report describe an empty day.
        """
        self.day_start_equity = self.current_equity if self.current_equity > 0 else 0.0

    def reset_daily_metrics(self):
        """New trading day: reset range trackers and re-anchor the daily DD."""
        self.equity_max = self.current_equity
        self.equity_min = self.current_equity
        if self.current_equity > 0:
            self.day_start_equity = self.current_equity