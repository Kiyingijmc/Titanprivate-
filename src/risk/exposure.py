# ==============================================================================
# FILE: src/risk/exposure.py
# TYPE: RISK LOGIC UPDATE (Safety Guards)
# AUDIT: 
#   1. Clarified Config Semantics (Exposure Pct -> Position Count).
#   2. Secured input access (.get) to prevent KeyErrors on malformed ZMQ packets.
#   3. Integrated updated O(1) Correlation Manager.
# STATUS: PRODUCTION READY
# ==============================================================================

from src.risk.correlation import CorrelationManager

class ExposureManager:
    """
    Titan Portfolio Guard.
    Manages Max Positions, Currency Saturation, and Correlation blocking.
    
    AUDIT UPGRADE:
    - Robust Config Parsing (Float -> Int for counts).
    - Defensive Packet Parsing for ZMQ position lists.
    """
    def __init__(self, config, market_data_store):
        # We pass market_data_store (system_controller.market_data) 
        # so correlation manager can access histories.
        self.config = config['risk']['account']
        
        # AUDIT FIX: Config semantics. 
        # Variable is named 'pct' in config but logic behaves as 'Max Count'.
        # We coerce to INT to ensure comparisons work correctly (e.g. 6.0 -> 6)
        raw_val = self.config.get('max_global_exposure_pct', 6.0)
        self.max_total_positions = int(raw_val)
        
        self.max_currency_saturation = 2

        # v15 Plan 10 Advisory A: portfolio-wide aggregate open-risk ceiling,
        # as a percentage of live equity. Unlike max_global_exposure_pct (a
        # position COUNT) this one really is a percent. See check_total_risk.
        self.max_total_open_risk_pct = float(
            self.config.get('max_total_open_risk_pct', 5.0)
        )

        self.correlation = CorrelationManager(market_data_store)

    def check_total_risk(self, aggregate_open_risk, proposed_risk, current_equity):
        """Portfolio-wide aggregate open-risk cap.

        The count gate above gladly allows N positions that each pass their own
        1%-of-equity sizing; nothing summed the book's $ risk before this. Here
        we do: (committed risk + this trade's risk) / equity must stay at or
        under `risk.account.max_total_open_risk_pct`.

        Args:
            aggregate_open_risk: $ risk-to-stop across everything already
                committed -- open positions AND resting pending orders
                (RiskManager.aggregate_open_risk) plus anything dispatched
                earlier in the same bar sweep that no heartbeat has reported yet
                (SystemController._reserved_risk_total) -- or None when
                un-computable. A positions-only figure is NOT sufficient: the
                only approved strategy enters on LIMIT, so it would read 0.0
                exactly when the cap needs to bite.
            proposed_risk: $ risk-to-stop of the trade being considered
                (RiskManager.risk_to_stop); its 0.0 sentinel means
                un-computable.
            current_equity: live account equity; <= 0 means no heartbeat yet.

        Returns: (Bool is_allowed, String reason)
        """
        # Fail safe on every un-computable input rather than guessing a number
        # or dividing by zero -- an unknown book is not a safe book.
        if current_equity is None or current_equity <= 0:
            return False, "Total Open Risk un-computable (no equity snapshot)"
        if aggregate_open_risk is None:
            return False, ("Total Open Risk un-computable "
                           "(open position without a stop, or missing broker specs)")
        if proposed_risk is None or proposed_risk <= 0:
            return False, "Total Open Risk un-computable (proposed trade risk unknown)"

        total_pct = (aggregate_open_risk + proposed_risk) / current_equity * 100.0
        if total_pct > self.max_total_open_risk_pct:
            return False, (f"Total Open Risk {total_pct:.2f}% exceeds cap "
                           f"{self.max_total_open_risk_pct:.2f}%")

        return True, "Safe"

    def check_exposure(self, proposed_symbol, active_positions_list):
        """
        Gatekeeper for portfolio risk.
        Returns: (Bool is_allowed, String reason)
        """
        # 1. Total Load Check
        # Prevents over-trading beyond account operational capacity
        if len(active_positions_list) >= self.max_total_positions:
            return False, f"Max Trades ({len(active_positions_list)}/{self.max_total_positions}) Reached"

        # 2. Duplicate Check
        # Prevents opening multiple trades on the same symbol (unless grid logic intended, which this is not)
        for pos in active_positions_list:
            # Defensive Access: ZMQ keys are usually 's', but safely get
            existing_sym = pos.get('s', '')
            if existing_sym == proposed_symbol:
                return False, f"Active position on {proposed_symbol} exists"

        # 3. Currency Saturation (The Simple Heuristic)
        # Prevents e.g. 3 Shorts on USD simultaneously (Risk Concentration)
        # Assumes standard 6-char symbol format (e.g. EURUSD). 
        # Safely ignores Indices/Crypto that don't fit length.
        if len(proposed_symbol) == 6:
            base = proposed_symbol[:3]
            quote = proposed_symbol[3:]
            sat_count = 0
            
            for pos in active_positions_list:
                sym = pos.get('s', '')
                if len(sym) == 6:
                    # Check overlap (e.g. EUR matches EURUSD and EURJPY)
                    if base in sym or quote in sym:
                        sat_count += 1
            
            if sat_count >= self.max_currency_saturation:
                return False, f"Currency Saturated ({base}/{quote})"

        # 4. Mathematical Correlation (The Advanced Heuristic)
        # Uses the matrix cache to check if we are taking a statistically similar bet
        safe, reason = self.correlation.check_correlation(proposed_symbol, active_positions_list)
        if not safe:
            return False, reason

        return True, "Safe"