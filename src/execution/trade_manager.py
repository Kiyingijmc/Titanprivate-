# ==============================================================================
# FILE: src/execution/trade_manager.py
# TYPE: LOGIC SAFETY UPDATE (Execution)
# AUDIT:
#   1. Improved "Dust Guard" math (Error 4756 prevention).
#   2. Added Zero-Division protections for Manual/Modified trades.
#   3. Fully aligned with v14.3 Quantized Risk Manager.
# STATUS: PRODUCTION READY
# ==============================================================================

import time
import math
from src.utils.instrument import InstrumentHelper

class TradeManager:
    """
    Titan Trade Management Engine (Fibonacci Ratchet).

    Stages (progress toward original TP):
      L1 0.382  -> stop to break-even (+3 pip buffer)
      L2 0.618  -> stop to L1 price, bank 30%
      L3 0.886  -> stop to L2 price, bank 50%; runner mode drops the TP
      Runner    -> after L3 the remaining tail trails behind price

    Commands are dicts consumed by SystemController._dispatch_mgmt_command:
      MODIFY        {ticket, symbol, sl, tp}   (routed via reliable REQ socket)
      CLOSE_PARTIAL {ticket, volume}           (absolute lots, dust-guarded)
      CLOSE_POS     {ticket}
    """
    def __init__(self, logger, state_manager, risk_manager, config=None):
        self.logger = logger
        self.state_manager = state_manager
        self.risk_manager = risk_manager
        self.command_cooldowns = {}

        # Standard Institutional Fibonacci Ratchet Levels
        self.L1_FIB = 0.382  # Stage 1: Break-Even
        self.L2_FIB = 0.618  # Stage 2: Bank 30%
        self.L3_FIB = 0.886  # Stage 3: Bank 50%

        mgmt = (config or {}).get('trade_management', {})
        runner_cfg = mgmt.get('runner', {})
        self.runner_enabled = bool(runner_cfg.get('enabled', False))
        # Arm C (validated 2026-07-11): one-way runner-trail tighten on a give-back.
        self.tighten_enabled = bool(runner_cfg.get('tighten_on_giveback', False))
        self.giveback_frac = float(runner_cfg.get('giveback_frac', 0.75))
        self.tight_trail_frac = float(runner_cfg.get('tight_trail_frac', 0.10))
        self.runner_hwm = {}      # ticket -> best price in trade direction (in-memory)
        self.tightened = set()    # tickets whose trail has been tightened (one-way)

    def sync_positions(self, position_list_json, current_prices_dict):
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

                # 3. State Retrieval: original Entry/TP from SQLite
                r_level, init_entry, init_tp = self.state_manager.get_ratchet_state(ticket)
                if init_entry == 0 or init_tp == 0:
                    continue

                range_size = abs(init_tp - init_entry)
                if range_size < 1e-9:
                    continue

                is_long = (init_tp > init_entry)
                dist = (curr_price - init_entry) if is_long else (init_entry - curr_price)
                pct = dist / range_size

                curr_tp = float(pos.get('tp', 0))
                current_vol = float(pos.get('vol', 0))

                new_level = r_level
                actions = []

                def get_sl(price_level):
                    return self.risk_manager.normalize_price(price_level, symbol)

                # --- STAGE 1: Break Even (0.382) ---
                if pct >= self.L1_FIB and r_level < 1:
                    pip = InstrumentHelper.get_pip_size(symbol)
                    # 3-pip buffer to cover spread/swaps
                    be_price = (init_entry + pip*3) if is_long else (init_entry - pip*3)
                    actions.append({"action": "MODIFY", "ticket": ticket, "symbol": symbol,
                                    "sl": get_sl(be_price), "tp": curr_tp, "comment": "Ratchet L1"})
                    new_level = 1

                # --- STAGE 2: Bank 30% (0.618) ---
                if pct >= self.L2_FIB and r_level < 2:
                    l1_price = init_entry + (range_size * self.L1_FIB) if is_long else init_entry - (range_size * self.L1_FIB)
                    actions.append({"action": "MODIFY", "ticket": ticket, "symbol": symbol,
                                    "sl": get_sl(l1_price), "tp": curr_tp, "comment": "Ratchet L2"})
                    actions.extend(self._partial_actions(ticket, symbol, current_vol, 0.3))
                    new_level = 2

                # --- STAGE 3: Bank 50% (0.886) ---
                if pct >= self.L3_FIB and r_level < 3:
                    l2_price = init_entry + (range_size * self.L2_FIB) if is_long else init_entry - (range_size * self.L2_FIB)
                    # Runner mode: release the TP so the tail can run; trailing takes over
                    l3_tp = 0.0 if self.runner_enabled else curr_tp
                    actions.append({"action": "MODIFY", "ticket": ticket, "symbol": symbol,
                                    "sl": get_sl(l2_price), "tp": l3_tp, "comment": "Ratchet L3"})
                    actions.extend(self._partial_actions(ticket, symbol, current_vol, 0.5))
                    new_level = 3

                if new_level > r_level:
                    self.state_manager.update_ratchet_level(ticket, new_level)
                    self.state_manager.update_trade_phase(ticket, new_level)
                    commands.extend(actions)
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
                    if tighter:
                        commands.append({"action": "MODIFY", "ticket": ticket, "symbol": symbol,
                                         "sl": candidate, "tp": curr_tp, "comment": "Runner Trail"})
                        self.command_cooldowns[ticket] = now

            except Exception as e:
                # Log error but prevent single trade logic crash from stopping loop
                self.logger.log_event("ERROR", "TRADE_MGR", f"Logic fail on {pos.get('t', '?')}: {e}")

        return commands

    def _partial_actions(self, ticket, symbol, vol, pct):
        """Translate a partial-close intent into bridge commands (or none)."""
        mode, close_vol = self._partial_volume(symbol, vol, pct)
        if mode == "FULL":
            return [{"action": "CLOSE_POS", "ticket": ticket, "comment": "Dust Guard Exit"}]
        if mode == "PARTIAL":
            return [{"action": "CLOSE_PARTIAL", "ticket": ticket, "volume": close_vol,
                     "comment": f"Bank {int(pct * 100)}%"}]
        return []

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
        close_amt = round(close_amt, 2)

        if close_amt < min_lot:
            return "SKIP", None

        # Dust check: the broker rejects a partial whose REMAINDER is below min lot
        remainder = round(vol - close_amt, 5)
        if remainder < min_lot and not math.isclose(remainder, 0.0, abs_tol=1e-9):
            return "FULL", None

        return "PARTIAL", close_amt
