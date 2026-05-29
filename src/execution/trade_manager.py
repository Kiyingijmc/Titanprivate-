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
    Titan v14.3 Production Trade Management Engine.
    
    AUDIT UPGRADE:
    - Retains: 100% of v14.1 Fibonacci Ratchet Logic & Emergency Kill-Switch.
    - Improves: Floating point precision for Partial Close "Dust Checks".
    - Protects: Against Division-by-Zero on manual trades (Entry == TP).
    """
    def __init__(self, logger, state_manager, risk_manager):
        self.logger = logger
        self.state_manager = state_manager
        self.risk_manager = risk_manager 
        self.command_cooldowns = {} 
        
        # RESTORATION (v14.1): Standard Institutional Fibonacci Ratchet Levels
        self.L1_FIB = 0.382  # Stage 1: Break-Even
        self.L2_FIB = 0.618  # Stage 2: Bank 30%
        self.L3_FIB = 0.886  # Stage 3: Bank 50%

    def sync_positions(self, position_list_json, current_prices_dict):
        """
        RESTORATION (v14.1): Full position sync loop with dollar-based risk guard.
        Iterates active MT5 positions and applies management logic.
        """
        commands = []
        now = time.time()
        
        # 1. Emergency Kill Switch (v14.1 Logic)
        # Prevents runaway losses during flash crashes
        max_risk = self.risk_manager.get_max_risk_amount()
        # Safety: Ensure we have a valid max risk (default high if calc fails)
        max_loss_allowed = max_risk * 1.5 if max_risk > 0 else 99999.0

        for pos in position_list_json:
            try:
                ticket = int(pos.get('t', 0))
                symbol = pos.get('s')
                
                # Invalid packet data guard
                if ticket == 0 or not symbol: 
                    continue
                
                # 2. Data & Cooldown Guard (v14.1 Logic)
                if symbol not in current_prices_dict: 
                    continue
                    
                curr_price = float(current_prices_dict[symbol])

                # Prevent command spamming (2.0s cooldown per ticket)
                if (now - self.command_cooldowns.get(ticket, 0)) < 2.0: 
                    continue

                # 3. Emergency Risk Guard (v14.1 Logic)
                profit = float(pos.get('pf', 0.0))
                if profit < -max_loss_allowed:
                    self.logger.log_event("RISK", "EMERGENCY", f"Killed #{ticket}: Loss ${profit:.2f} > 1.5x Limit")
                    commands.append({"action": "CLOSE_POS", "ticket": ticket, "comment": "Risk Guard"})
                    self.command_cooldowns[ticket] = now
                    continue 

                # 4. State Retrieval (v14.1 Protocol)
                # Fetch original Entry/TP from SQLite
                r_level, init_entry, init_tp = self.state_manager.get_ratchet_state(ticket)
                
                # Validation: Cannot manage trade without DB record or valid TP
                if init_entry == 0 or init_tp == 0: 
                    continue
                
                # 5. Range Progress Calculation (v14.1 Logic)
                # Safety: Absorb manual modification where TP might equal Entry temporarily
                range_size = abs(init_tp - init_entry)
                if range_size < 1e-9: # Effectively Zero
                    continue
                
                is_long = (init_tp > init_entry)
                
                # Calculate progress % (How close are we to TP?)
                dist = (curr_price - init_entry) if is_long else (init_entry - curr_price)
                pct = dist / range_size
                
                curr_tp = float(pos.get('tp', 0))
                current_vol = float(pos.get('vol', 0))
                
                new_level = r_level
                actions = []
                
                # Helper for Stop Loss normalization using upgraded RiskManager
                def get_sl(price_level):
                    return self.risk_manager.normalize_price(price_level, symbol)

                # --- STAGE 1: Break Even (L1_FIB 0.382) ---
                if pct >= self.L1_FIB and r_level < 1:
                    pip = InstrumentHelper.get_pip_size(symbol)
                    # v14.1 Restore: Standard 3-pip buffer to cover spread/swaps
                    be_price = (init_entry + pip*3) if is_long else (init_entry - pip*3)
                    
                    actions.append({"action": "MODIFY", "ticket": ticket, "sl": get_sl(be_price), "tp": curr_tp, "comment": "Ratchet L1"})
                    new_level = 1

                # --- STAGE 2: Bank 30% (L2_FIB 0.618) ---
                if pct >= self.L2_FIB and r_level < 2:
                    # Trail SL to L1 level (Lock in profit)
                    l1_price = init_entry + (range_size * self.L1_FIB) if is_long else init_entry - (range_size * self.L1_FIB)
                    actions.append({"action": "MODIFY", "ticket": ticket, "sl": get_sl(l1_price), "tp": curr_tp, "comment": "Ratchet L2"})
                    
                    # UPGRADE (v14.2): Partial Check with Dust Guard
                    partial_res = self._check_partial(symbol, current_vol, 0.3)
                    if partial_res == "CLOSE_FULL":
                        actions.append({"action": "CLOSE_POS", "ticket": ticket, "comment": "Dust Guard Exit"})
                    elif partial_res is True:
                        actions.append({"action": "CLOSE_PARTIAL", "ticket": ticket, "volume_pct": 0.3})
                    
                    new_level = 2

                # --- STAGE 3: Bank 50% (L3_FIB 0.886) ---
                if pct >= self.L3_FIB and r_level < 3:
                    # Trail SL to L2 level
                    l2_price = init_entry + (range_size * self.L2_FIB) if is_long else init_entry - (range_size * self.L2_FIB)
                    actions.append({"action": "MODIFY", "ticket": ticket, "sl": get_sl(l2_price), "tp": curr_tp, "comment": "Ratchet L3"})
                    
                    # UPGRADE (v14.2): Partial Check with Dust Guard
                    partial_res = self._check_partial(symbol, current_vol, 0.5)
                    if partial_res == "CLOSE_FULL":
                        actions.append({"action": "CLOSE_POS", "ticket": ticket, "comment": "Dust Guard Exit"})
                    elif partial_res is True:
                        actions.append({"action": "CLOSE_PARTIAL", "ticket": ticket, "volume_pct": 0.5})
                        
                    new_level = 3

                # --- 6. COMMAND EXECUTION (v14.1 Protocol) ---
                if new_level > r_level:
                    self.state_manager.update_ratchet_level(ticket, new_level)
                    self.state_manager.update_trade_phase(ticket, new_level)
                    commands.extend(actions)
                    self.command_cooldowns[ticket] = now
            
            except Exception as e:
                # Log error but prevent single trade logic crash from stopping loop
                self.logger.log_event("ERROR", "TRADE_MGR", f"Logic fail on {pos.get('t', '?')}: {e}")

        return commands

    def _check_partial(self, symbol, vol, pct):
        """
        NEW FEATURE (v14.3): Institutional Dust Guard.
        Prevents Error 4756 (Invalid Volume) by verifying that the 
        REMAINDER of the trade is large enough for the broker to maintain.
        """
        if vol <= 0: return False 
        
        # Retrieve dynamic broker constraints from RiskManager (Restored v14.1 Spec)
        spec = self.risk_manager.symbol_specs.get(symbol)
        
        # Defaults if specs not yet loaded (Safe defaults)
        min_lot = spec['vm'] if spec and spec['vm'] > 0 else 0.01
        step_lot = spec['vs'] if spec and spec['vs'] > 0 else 0.01
        
        # Calculate intended close amount
        raw_close = vol * pct
        
        # Snap to Volume Step (Floor logic + float correction)
        # Using 1e-9 tolerance to prevent 0.099999 issues
        close_amt = math.floor((raw_close + 1e-9) / step_lot) * step_lot
        close_amt = round(close_amt, 2) # Standard Lot precision
        
        # 1. Is the close amount valid?
        if close_amt < min_lot:
            return False 
            
        # 2. THE DUST CHECK: Is the REMAINDER valid?
        remainder = round(vol - close_amt, 5)
        
        # Robust comparison using math.isclose implies: is remainder < min_lot?
        # If remainder is effectively zero (full close), that's fine (remainder 0 < min_lot is logic fail usually, 
        # but here we care if remainder is POSITIVE but small).
        # Wait: If we close 0.5 of 0.5, remainder is 0. Valid.
        # If we close 0.9 of 1.0, remainder is 0.1. Valid.
        # If we close 0.09 of 0.10 (min 0.01), remainder 0.01. Valid.
        
        if remainder < min_lot and not math.isclose(remainder, 0.0, abs_tol=1e-9):
            # If the remainder exists (not 0) AND is smaller than min_lot,
            # The broker will REJECT the partial because the leftover position is illegal.
            # v14.2 Solution: Close the whole position to secure profits.
            return "CLOSE_FULL"
        
        return True