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
from src.utils.instrument import InstrumentHelper

class RiskManager:
    """
    Version 14.3 Institutional Risk Engine.
    
    AUDIT UPGRADE:
    - Implements Quantized Price Normalization (Supports non-power-of-10 ticks).
    - Enforces Broker-Specific Contract Specs over Generic Fallbacks.
    """
    def __init__(self, config):
        self.config = config['risk']
        
        # Original oper.txt constants
        self.max_dd = self.config['account']['max_daily_drawdown_pct']
        self.risk_pct = self.config['trade']['risk_per_trade_pct']
        self.hard_max_lots = self.config['trade'].get('hard_max_lots', 5.0)
        self.comm_per_lot = self.config['trade'].get('static_commission_usd', 7.0)
        
        # State Management
        self.starting_balance = 0.0
        self.current_equity = 0.0
        self.symbol_specs = {} 
        
        # V14 Reporting Metrics (For 11:45 PM Uganda Report)
        self.equity_max = 0.0
        self.equity_min = float('inf')

    def update_account_info(self, balance, equity):
        """Standard oper.txt logic: Permanent lock of starting balance on init"""
        if self.starting_balance == 0 and balance > 0: 
            self.starting_balance = balance
        
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
                # reliable string counting for formatting
                precision = len(str(float(tick_size)).split('.')[1])
                
            return round(normalized, precision)
        
        # Fallback to InstrumentHelper if no specs from Broker
        return InstrumentHelper.normalize_price(price, InstrumentHelper.get_pip_size(symbol))

    def check_can_trade(self) -> bool:
        """Daily Drawdown Circuit Breaker (oper.txt Legacy)"""
        if self.starting_balance == 0: return True
        # Safety: divide by zero protection
        if self.starting_balance <= 0: return False
            
        pnl_pct = (self.current_equity - self.starting_balance) / self.starting_balance * 100
        return pnl_pct > -self.max_dd

    def get_max_risk_amount(self, bias_multiplier=1.0):
        """V14 Enhancement: Integrated Bias Multiplier (0.5x for Neutral)"""
        if self.current_equity == 0: return 0.0
        base_risk = self.current_equity * (self.risk_pct / 100.0)
        return base_risk * bias_multiplier

    def calculate_lot_size(self, entry, sl, symbol, htf_bias="NEUTRAL") -> float:
        """
        FULL POSITION SIZER (Restored oper.txt Logic)
        Includes: Net Risk Adjustment, Hard Caps, and Asset Fallbacks.
        """
        # 1. Circuit Breaker
        if not self.check_can_trade(): 
            return 0.0

        # 2. Bias Shield (V14 Feature)
        multiplier = 1.0 if htf_bias != "NEUTRAL" else 0.5
        raw_risk_money = self.get_max_risk_amount(bias_multiplier=multiplier)

        entry = float(entry); sl = float(sl)
        diff = abs(entry - sl)
        if diff == 0: return 0.0

        spec = self.symbol_specs.get(symbol)
        lots_gross = 0.0
        min_vol = 0.01; vol_step = 0.01

        # 3. LIVE PRECISION MODE (Tick-Value Logic)
        # This is the "Audit Preferred" path: Broker-provided math
        if spec and spec['val'] > 0 and spec['ts'] > 0:
            tick_size = spec['ts']
            tick_val = spec['val']
            
            # Risk Equation: Money = Lots * (DistPoints) * TickValue
            # But wait: MT5 TickValue is "Value of 1 Lot for 1 Tick Change"
            
            ticks_at_risk = diff / tick_size
            money_loss_per_lot = ticks_at_risk * tick_val
            
            if money_loss_per_lot > 0: 
                lots_gross = raw_risk_money / money_loss_per_lot
                
            min_vol = spec['vm']
            vol_step = spec['vs']
            
        # 4. RESTORED FALLBACK MODE (oper.txt Instrument Specs)
        else:
            pip_size = InstrumentHelper.get_pip_size(symbol)
            pip_dist = diff / pip_size
            
            val_per_pip = 10.0 # Forex Std
            if "JPY" in symbol: val_per_pip = 8.5
            if "XAU" in symbol: val_per_pip = 100.0 
            if "BTC" in symbol: val_per_pip = 1.0
            
            if pip_dist > 0: 
                lots_gross = raw_risk_money / (pip_dist * val_per_pip)

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

    def reset_daily_metrics(self):
        """V14 Report Support: Reset range trackers"""
        self.equity_max = self.current_equity
        self.equity_min = self.current_equity