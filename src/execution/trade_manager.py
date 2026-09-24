# ==============================================================================
# FILE: src/execution/trade_manager.py
# TYPE: LOGIC SAFETY UPDATE (Execution)
# AUDIT:
#   1. Improved "Dust Guard" math (Error 4756 prevention).
#   2. Added Zero-Division protections for Manual/Modified trades.
#   3. Fully aligned with v14.3 Quantized Risk Manager.
# STATUS: Legacy ratchet with opt-in experimental M15 structure management
# ==============================================================================

import time
import math
from decimal import Decimal
import pytz
from datetime import datetime, timezone, timedelta

from src.utils.instrument import InstrumentHelper
from src.analysis import trading_days
from src.analysis.structure_management import StructurePolicy, m15_context, management_plan
from dataclasses import asdict

class TradeManager:
    """
    Titan Trade Management Engine (legacy ratchet or durable M15 profile).

    Stages (progress toward original TP):
      L1 0.382  -> stop to break-even (+3 pip buffer)
      L2 0.618  -> stop to L1 price, bank 30%
      L3 0.886  -> stop to L2 price, bank 50%; runner mode drops the TP
      Runner    -> after L3 the remaining tail trails behind price

    Commands are dicts consumed by SystemController._dispatch_mgmt_command:
      MODIFY        {ticket, symbol, sl, tp}   (reconciled against broker snapshots)
      CLOSE_PARTIAL {ticket, volume, target_volume} (idempotent remaining-volume target)
      CLOSE_POS     {ticket}
    """
    def __init__(self, logger, state_manager, risk_manager, config=None):
        self.logger = logger
        self.state_manager = state_manager
        self.risk_manager = risk_manager
        self.command_cooldowns = {}
        self._legacy_partial_warned = set()

        # Standard Institutional Fibonacci Ratchet Levels
        self.L1_FIB = 0.382  # Stage 1: Break-Even
        self.L2_FIB = 0.618  # Stage 2: Bank 30%
        self.L3_FIB = 0.886  # Stage 3: Bank 50%

        mgmt = (config or {}).get('trade_management', {})
        structure = mgmt.get('structure', {})
        self._structure_new = structure.get('enabled', False) is True
        self._structure_policy = StructurePolicy(**structure.get('settings', {}))
        self._structure_strategies = set(structure.get('strategies', ['SilverBullet', 'Gyroscope']))
        self._started_at = time.time()
        self._structure_context = {}
        self._structure_cache = {}
        persisted = (state_manager.has_structure_profiles()
                     if callable(getattr(type(state_manager), 'has_structure_profiles', None)) else False)
        self.structure_enabled = self._structure_new or persisted
        runner_cfg = mgmt.get('runner', {})
        self.runner_enabled = bool(runner_cfg.get('enabled', False))
        # Arm C (validated 2026-07-11): one-way runner-trail tighten on a give-back.
        self.tighten_enabled = bool(runner_cfg.get('tighten_on_giveback', False))
        self.giveback_frac = float(runner_cfg.get('giveback_frac', 0.75))
        self.tight_trail_frac = float(runner_cfg.get('tight_trail_frac', 0.10))
        self.runner_hwm = {}      # ticket -> best price in trade direction (in-memory)
        self.tightened = set()    # tickets whose trail has been tightened (one-way)

        # Time exits: strategy NAME -> rule. Three variants share the hook:
        #   calendar (Almanac): {exit_trading_day: 3} or a plain int -- close
        #     once the turn-of-month window has passed
        #     (src/analysis/trading_days.should_time_exit).
        #   duration (Gyroscope v2b GO): {max_bars: 48} -- close once held
        #     >= max_bars H1 bars, measured as wall-clock hours since
        #     time_placed. Weekend hours count, so a weekend-spanning trade
        #     exits up to ~2 bars earlier than the offline replay's
        #     market-bar count (4/1112 gate trades reached the stop; the
        #     skew only ever shortens exposure).
        #   flat_at_ny (Gambit): {flat_at_ny: ["05:00","11:00"]} -- close once
        #     any listed NY wall-clock time has been crossed since placement
        #     (session-end flat for intraday strategies). DST handled by pytz.
        # Empty or absent config keeps this hook fully inert.
        self.time_exits = {}
        self.time_exits_bars = {}
        self.time_exits_flat_ny = {}
        self._ny_tz = pytz.timezone('US/Eastern')
        for name, rule in (mgmt.get('time_exits') or {}).items():
            try:
                if isinstance(rule, dict) and 'flat_at_ny' in rule:
                    parsed = []
                    for s in rule['flat_at_ny']:
                        hh, mm = str(s).split(':')
                        parsed.append((int(hh), int(mm)))
                    if parsed:
                        self.time_exits_flat_ny[str(name)] = parsed
                    continue
                if isinstance(rule, dict) and 'max_bars' in rule:
                    self.time_exits_bars[str(name)] = int(rule['max_bars'])
                    continue
                day = rule.get('exit_trading_day', 3) if isinstance(rule, dict) else rule
                self.time_exits[str(name)] = int(day)
            except (ValueError, TypeError, AttributeError):
                continue

    def update_structure_context(self, symbol, m5, timestamp):
        """Refresh once per source candle/15-minute boundary, including while paused."""
        try:
            if timestamp > 32503680000:
                timestamp /= 1000.
            last = str(m5.iloc[-1]['time']) if m5 is not None and len(m5) else None
            key = (last, int(timestamp // 900))
            if self._structure_cache.get(symbol) != key:
                self._structure_context[symbol] = m15_context(
                    m5, datetime.fromtimestamp(timestamp, timezone.utc))
                self._structure_cache[symbol] = key
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            # Bad history must not suppress emergency exits or intent recovery.
            self._structure_context[symbol] = None
            self.logger.log_event('WARN', 'TRADE_MGR', f'{symbol}: invalid M15 context: {exc}')

    def _management_profile(self, ticket, level, pending_intent=False):
        if not self.structure_enabled:
            return None
        profile = self.state_manager.get_management_profile(ticket)
        if profile is None:
            meta = self.state_manager.get_order_meta(ticket)
            eligible = (self._structure_new and level == 0 and not pending_intent and meta
                        and meta[0] in self._structure_strategies and meta[1] >= self._started_at)
            profile = ({'mode': 'm15_structure_v1', 'settings': asdict(self._structure_policy),
                        'since': datetime.now(timezone.utc).replace(tzinfo=None).isoformat()}
                       if eligible else {'mode': 'legacy'})
            profile = self.state_manager.save_management_profile(ticket, profile)
        return profile

    def _time_exit_due(self, ticket, now):
        """True when the ticket belongs to a time-exit strategy whose calendar
        window has passed. UTC dates on both sides (time_placed is stored as
        time.time() at registration); the broker-vs-UTC skew of a few hours
        only shifts the day-4 boundary, identically live and in replay."""
        if not self.time_exits and not self.time_exits_bars and not self.time_exits_flat_ny:
            return False
        meta = self.state_manager.get_order_meta(ticket)
        if not meta:
            return False
        strat_name, placed = meta
        if not placed or placed <= 0:
            return False
        flat_times = self.time_exits_flat_ny.get(strat_name)
        if flat_times is not None:
            placed_ny = datetime.fromtimestamp(placed, tz=timezone.utc).astimezone(self._ny_tz)
            now_ny = datetime.fromtimestamp(now, tz=timezone.utc).astimezone(self._ny_tz)
            day = placed_ny.date()
            # Walk each NY calendar day from placement to now (bounded: a
            # flat-by-close trade should never span days, but an outage might).
            while day <= now_ny.date():
                for hh, mm in flat_times:
                    b = self._ny_tz.localize(
                        datetime(day.year, day.month, day.day, hh, mm))
                    if placed_ny < b <= now_ny:
                        return True
                day += timedelta(days=1)
            return False
        max_bars = self.time_exits_bars.get(strat_name)
        if max_bars is not None:
            return (now - placed) >= max_bars * 3600.0
        exit_day = self.time_exits.get(strat_name)
        if exit_day is None:
            return False
        entry_d = datetime.fromtimestamp(placed, tz=timezone.utc).date()
        today = datetime.fromtimestamp(now, tz=timezone.utc).date()
        return trading_days.should_time_exit(today, entry_d, exit_day)

    def sync_positions(self, position_list_json, current_prices_dict, ask_prices=None):
        """
        Iterates active MT5 positions and applies management logic.
        Returns the list of commands to send to the bridge.
        """
        commands = []
        now = time.time()

        # 1. Emergency Kill Switch: prevents runaway losses during flash crashes
        max_risk = self.risk_manager.get_max_risk_amount()
        max_loss_allowed = max_risk * 1.5 if max_risk > 0 else 99999.0

        for pos in position_list_json:
            try:
                ticket = int(pos.get('t', 0))
                symbol = pos.get('s')
                if ticket == 0 or not symbol:
                    continue
                if symbol not in current_prices_dict:
                    continue

                curr_price = float(current_prices_dict[symbol])

                # Prevent command spamming (2.0s cooldown per ticket)
                if (now - self.command_cooldowns.get(ticket, 0)) < 2.0:
                    continue

                # 2. Emergency Risk Guard
                profit = float(pos.get('pf', 0.0))
                if profit < -max_loss_allowed:
                    self.logger.log_event("RISK", "EMERGENCY", f"Killed #{ticket}: Loss ${profit:.2f} > 1.5x Limit")
                    commands.append({"action": "CLOSE_POS", "ticket": ticket, "comment": "Risk Guard"})
                    self.command_cooldowns[ticket] = now
                    continue

                # 3. Time Exit (calendar strategies, e.g. Almanac): close once
                # the turn-of-month window has passed, before ratchet logic.
                if self._time_exit_due(ticket, now):
                    self.logger.log_event("TRADE_MGR", "TIME_EXIT",
                                          f"Closing #{ticket}: calendar window passed")
                    commands.append({"action": "CLOSE_POS", "ticket": ticket,
                                     "comment": "Time Exit"})
                    self.command_cooldowns[ticket] = now
                    continue

                # 4. State Retrieval: original Entry/TP from SQLite
                r_level, init_entry, init_tp = self.state_manager.get_ratchet_state(ticket)
                if init_entry == 0 or init_tp == 0:
                    continue

                range_size = abs(init_tp - init_entry)
                if range_size < 1e-9:
                    continue

                is_long = (int(pos['type']) == 0) if pos.get('type') is not None else (init_tp > init_entry)
                if not is_long and ask_prices is not None:
                    # Never substitute bid for an unavailable executable ask.
                    if symbol not in ask_prices:
                        continue
                    curr_price = float(ask_prices[symbol])
                dist = (curr_price - init_entry) if is_long else (init_entry - curr_price)
                pct = dist / range_size

                curr_tp = float(pos.get('tp', 0))
                current_vol = float(pos.get('vol', 0))

                def get_sl(price_level):
                    candidate = self.risk_manager.normalize_price(price_level, symbol)
                    current_sl = float(pos.get('sl', 0) or 0)
                    # Broker-side protection is monotonic even if local stage
                    # state was lost and later recovered.
                    if current_sl > 0:
                        if is_long:
                            candidate = max(candidate, current_sl)
                        else:
                            candidate = min(candidate, current_sl)
                    return candidate

                intent = self.state_manager.get_management_intent(ticket)
                profile = self._management_profile(ticket, r_level, bool(intent))
                if intent:
                    pending = self._intent_commands(ticket, symbol, pos, intent, is_long)
                    if pending:
                        commands.extend(pending)
                        self.command_cooldowns[ticket] = now
                        continue
                    self.state_manager.confirm_management_intent(ticket, intent['level'])
                    r_level = max(r_level, intent['level'])
                    commands.append({'action': 'MODIFY_CONFIRMED', 'ticket': ticket,
                                     'symbol': symbol, 'sl': float(pos.get('sl', 0)),
                                     'tp': float(pos.get('tp', 0)),
                                     'comment': intent.get('label', f"Ratchet L{intent['level']}" )})

                if profile and profile['mode'] != 'legacy':
                    if profile['mode'] != 'm15_structure_v1':
                        raise ValueError('unknown durable management profile')
                    # Both quotes are required for spread-aware structure stops.
                    if not ask_prices or symbol not in ask_prices:
                        continue
                    spread = float(ask_prices[symbol]) - float(current_prices_dict[symbol])
                    spec = self.risk_manager.symbol_specs.get(symbol, {})
                    plan = management_plan(
                        context=self._structure_context.get(symbol),
                        policy=StructurePolicy(**profile['settings']), entry=init_entry,
                        original_tp=init_tp, current_sl=float(pos.get('sl', 0)),
                        current_tp=curr_tp, price=curr_price, is_long=is_long,
                        spread=spread, tick_size=float(spec.get('ts', 0)),
                        since=profile['since'], level=r_level)
                    if plan:
                        mode, amount = self._partial_volume(symbol, current_vol, plan['fraction'])
                        # Keep a legal runner: never turn a partial into a full close.
                        target = round(current_vol-amount, 8) if mode == 'PARTIAL' else current_vol
                        plan.update(sl=get_sl(plan['sl']), target_volume=target,
                                    partial=mode == 'PARTIAL')
                        self.state_manager.save_management_intent(ticket, plan)
                        commands.extend(self._intent_commands(ticket, symbol, pos, plan, is_long))
                        self.command_cooldowns[ticket] = now
                    continue

                # A legacy request has no durable volume target. Do not guess
                # a second close; continue to preserve its protective stop.
                confirmed, requested = self.state_manager.get_partial_state(ticket)
                partial_pending = requested > confirmed
                if partial_pending and ticket not in self._legacy_partial_warned:
                    self.logger.log_event("WARN", "TRADE_MGR",
                        f"#{ticket}: legacy partial request has no volume target; broker reconciliation required before further partials")
                    self._legacy_partial_warned.add(ticket)
                # Older versions advanced levels at send time. Repair their
                # protection too, without inventing another partial close.
                if r_level in (1, 2):
                    direction = 1 if is_long else -1
                    distance = (InstrumentHelper.get_pip_size(symbol) * 3 if r_level == 1
                                else range_size * self.L1_FIB)
                    protection = {'level': r_level, 'sl': get_sl(init_entry + direction * distance),
                                  'tp': curr_tp, 'partial': False, 'target_volume': current_vol}
                    repair = self._intent_commands(ticket, symbol, pos, protection, is_long)
                else:
                    repair = []
                level = None
                if pct >= self.L2_FIB and r_level < 2:
                    level = 2
                elif pct >= self.L1_FIB and r_level < 1:
                    level = 1
                elif pct >= self.L3_FIB and r_level < 3 and not partial_pending:
                    level = 3
                if level is not None:
                    direction = 1 if is_long else -1
                    distance = (InstrumentHelper.get_pip_size(symbol) * 3 if level == 1
                                else range_size * (self.L1_FIB if level == 2 else self.L2_FIB))
                    target = current_vol
                    mode = 'SKIP'
                    if level >= 2:
                        mode, amount = self._partial_volume(symbol, current_vol, 0.3 if level == 2 else 0.5)
                        if mode == 'PARTIAL':
                            target = round(current_vol - amount, 8)
                        elif mode == 'FULL':
                            target = 0.0
                    intent = {'level': level, 'sl': get_sl(init_entry + direction * distance),
                              'tp': 0.0 if level == 3 and self.runner_enabled else curr_tp,
                              'target_volume': target, 'partial': mode != 'SKIP'}
                    self.state_manager.save_management_intent(ticket, intent)
                    actions = self._intent_commands(ticket, symbol, pos, intent, is_long)
                    commands.extend(actions)
                    self.command_cooldowns[ticket] = now
                    continue

                if repair:
                    commands.extend(repair)
                    self.command_cooldowns[ticket] = now
                    continue

                # --- RUNNER TRAIL (post-L3, runner mode only) ---
                if self.runner_enabled and r_level >= 3:
                    base_trail = range_size * (self.L3_FIB - self.L2_FIB)

                    # Arm C: track the runner-leg high-water mark and, once a pullback
                    # gives back >= giveback_frac of the trail distance from it, tighten
                    # the trail (one-way). Entirely inert when disabled.
                    if self.tighten_enabled:
                        prev_hwm = self.runner_hwm.get(ticket, curr_price)
                        hwm = max(prev_hwm, curr_price) if is_long else min(prev_hwm, curr_price)
                        self.runner_hwm[ticket] = hwm
                        if ticket not in self.tightened:
                            give_back = (hwm - curr_price) if is_long else (curr_price - hwm)
                            if give_back >= self.giveback_frac * base_trail:
                                self.tightened.add(ticket)

                    trail_dist = (range_size * self.tight_trail_frac
                                  if ticket in self.tightened else base_trail)

                    candidate = (curr_price - trail_dist) if is_long else (curr_price + trail_dist)
                    candidate = get_sl(candidate)
                    curr_sl = float(pos.get('sl', 0))
                    tighter = (candidate > curr_sl) if is_long else (curr_sl == 0 or candidate < curr_sl)
                    if tighter or curr_tp != 0.0:
                        commands.append({"action": "MODIFY", "ticket": ticket, "symbol": symbol,
                                         "sl": candidate, "tp": 0.0, "comment": "Runner Trail"})
                        self.command_cooldowns[ticket] = now

            except Exception as e:
                # Log error but prevent single trade logic crash from stopping loop
                self.logger.log_event("ERROR", "TRADE_MGR", f"Logic fail on {pos.get('t', '?')}: {e}")

        return commands

    def _intent_commands(self, ticket, symbol, pos, intent, is_long):
        """Reconcile desired protection and remaining volume with broker state.

        Repeated close requests carry a remaining-volume target, so a delayed
        first execution cannot make the retry close the same quantity twice.
        """
        commands = []
        current_sl = float(pos.get('sl', 0) or 0)
        sl = intent['sl']
        protected = current_sl > 0 and (current_sl >= sl if is_long else current_sl <= sl)
        if not protected or not math.isclose(float(pos.get('tp', 0)), intent['tp'], abs_tol=1e-9):
            if protected:
                sl = current_sl
            commands.append({'action': 'MODIFY', 'ticket': ticket, 'symbol': symbol,
                             'sl': sl, 'tp': intent['tp'], 'await_confirmation': True,
                             'comment': intent.get('label', f"Ratchet L{intent['level']}" )})
        remaining = float(pos.get('vol', 0))
        if intent['partial'] and remaining > intent['target_volume'] + 1e-9:
            commands.append({'action': 'CLOSE_PARTIAL', 'ticket': ticket,
                             'volume': round(remaining - intent['target_volume'], 8),
                             'target_volume': intent['target_volume'],
                             'comment': intent.get('label', f"Ratchet L{intent['level']}" ) + ' partial requested'})
        return commands

    def _partial_volume(self, symbol, vol, pct):
        """
        Institutional Dust Guard (prevents Error 4756 / Invalid Volume).
        Returns (mode, volume):
          ("PARTIAL", lots) - close 'lots', remainder stays legal
          ("FULL", None)    - remainder would be dust; close everything
          ("SKIP", None)    - intended close is below the broker minimum
        """
        if vol <= 0:
            return "SKIP", None

        spec = self.risk_manager.symbol_specs.get(symbol)
        min_lot = spec['vm'] if spec and spec['vm'] > 0 else 0.01
        step_lot = spec['vs'] if spec and spec['vs'] > 0 else 0.01

        # Snap intended close to the volume step (floor + float tolerance)
        raw_close = vol * pct
        close_amt = math.floor((raw_close + 1e-9) / step_lot) * step_lot
        precision = max(0, -Decimal(str(step_lot)).as_tuple().exponent)
        close_amt = round(close_amt, precision)

        if close_amt < min_lot:
            return "SKIP", None

        # Dust check: the broker rejects a partial whose REMAINDER is below min lot
        remainder = round(vol - close_amt, max(precision, 8))
        if remainder < min_lot and not math.isclose(remainder, 0.0, abs_tol=1e-9):
            return "FULL", None

        return "PARTIAL", close_amt
