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
        self.symbol_specs = {}
        # Set by aggregate_open_risk when it returns None: the row that made
        # the book un-computable, so the operator halt alert can name it
        # (a book-wide block the operator can't locate is not actionable).
        self.last_uncomputable_row = None
        
        # V14 Reporting Metrics (For 11:45 PM Uganda Report)
        self.equity_max = 0.0
        self.equity_min = float('inf')

    def update_account_info(self, balance, equity):
        """Standard oper.txt logic: Permanent lock of starting balance on init"""
        if self.starting_balance == 0 and balance > 0:
            self.starting_balance = balance
        if self.day_start_equity == 0 and equity > 0:
            self.day_start_equity = equity

        self.current_equity = equity
        self.track_equity(equity)

    def track_equity(self, equity):
        """V14 Feature: Tracks intraday range for the Ugandan Report"""
        if equity > self.equity_max: self.equity_max = equity
        if equity < self.equity_min: self.equity_min = equity

    def update_symbol_specs(self, symbol, val, size, v_min, v_step):
        """
        Receives precise contract details from MQL5.
        AUDIT FIX: Sanitizes inputs to prevent mathematical crashes.
        """
        try:
            self.symbol_specs[symbol] = {
                'val': float(val) if val is not None else 0.0,    # Tick Value
                'ts': float(size) if size is not None else 0.0,   # Tick Size
                'vm': float(v_min) if v_min is not None else 0.01,# Volume Min
                'vs': float(v_step) if v_step is not None else 0.01 # Volume Step
            }
        except ValueError:
            # If ZMQ sends garbage, ignore update to keep existing/default state
            pass

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

    def reset_daily_metrics(self):
        """New trading day: reset range trackers and re-anchor the daily DD."""
        self.equity_max = self.current_equity
        self.equity_min = self.current_equity
        if self.current_equity > 0:
            self.day_start_equity = self.current_equity