# ==============================================================================
# FILE: src/analysis/time_math.py
# TYPE: LOGIC REFINEMENT (Math & Timezones)
# AUDIT: 
#   1. Added Type Guards for timestamp inputs.
#   2. Standardized Millisecond/Year 3000 logic matching CandleMaker.
#   3. Optimized Timezone Conversion stability.
# STATUS: PRODUCTION READY
# ==============================================================================

import pytz
from datetime import datetime, timedelta

class TimeNormalizer:
    """
    Titan Institutional Time Engine.
    Handles Broker-to-NY conversions, Killzones, and Timestamp Normalization.
    
    AUDIT UPGRADE:
    - Robust input handling (prevents crashes on malformed broker timestamps).
    - Unified Logic with SystemController and Strategy layers.
    """
    def __init__(self, broker_gmt_offset=0):
        # We store offset, ensuring it is an integer
        try:
            self.broker_offset = int(broker_gmt_offset)
        except (ValueError, TypeError):
            self.broker_offset = 2 # Default to UTC+2 if config bad
            
        # Optimization: Cache Timezone Objects once
        self.ny_tz = pytz.timezone('US/Eastern')
        self.utc_tz = pytz.timezone('UTC')

    def convert_broker_to_ny(self, broker_timestamp) -> datetime:
        """
        Converts a raw MT5 Tick Timestamp to New York Time.
        Auto-detects Milliseconds vs Seconds.
        
        SAFEGUARDS: Returns current NY time if timestamp is invalid (Fail-Safe).
        """
        if broker_timestamp is None:
            return datetime.now(self.ny_tz)

        try:
            ts = float(broker_timestamp)
        except (ValueError, TypeError):
            # Fallback if non-numeric data received
            return datetime.now(self.ny_tz)

        # Logic matching CandleMaker: Handle MS vs Seconds
        # Threshold: Year 3000 in seconds (32503680000)
        if ts > 32503680000: 
            ts /= 1000.0
            
        # 1. Server Time (Naive)
        try:
            server_dt = datetime.fromtimestamp(ts)
        except (ValueError, OSError):
            return datetime.now(self.ny_tz)
        
        # 2. Convert to UTC
        # Subtracting broker offset to get to UTC
        utc_dt = server_dt - timedelta(hours=self.broker_offset)
        
        # localize as UTC
        utc_dt = utc_dt.replace(tzinfo=self.utc_tz)
        
        # 3. Convert to NY
        return utc_dt.astimezone(self.ny_tz)

    def is_in_killzone(self, ny_time: datetime, start_str="07:00", end_str="10:00") -> bool:
        """
        String-based Killzone Checker (Retained Logic).
        Input: "07:00", "10:00"
        """
        if ny_time is None: return False
        
        try:
            sh, sm = map(int, start_str.split(':'))
            eh, em = map(int, end_str.split(':'))
            
            # Construct start/end times on the SAME DAY as the input ny_time
            start_time = ny_time.replace(hour=sh, minute=sm, second=0, microsecond=0)
            end_time = ny_time.replace(hour=eh, minute=em, second=0, microsecond=0)
            
            # Logic: Simple interval
            if start_time < end_time:
                # Standard day session (e.g. 07:00 to 10:00)
                return start_time <= ny_time < end_time
            else:
                # Cross-Midnight session (e.g. 23:00 to 02:00)
                return start_time <= ny_time or ny_time < end_time
                
        except (ValueError, AttributeError):
            # Fail closed (Not in zone) if format errors occur
            return False

    def get_current_ny_string(self) -> str:
        """Returns string representation 'HH:MM:SS EST/EDT'"""
        now_utc = datetime.now(self.utc_tz)
        now_ny = now_utc.astimezone(self.ny_tz)
        return now_ny.strftime("%H:%M:%S %Z")