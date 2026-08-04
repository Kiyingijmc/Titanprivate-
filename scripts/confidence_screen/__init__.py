"""Confidence–Skew Screen (spec 2026-08-04). Frozen constants only.

Every value here is preregistered. Changing one after the run has started
invalidates the study — see spec §5.3 on bounded re-specification.
"""

H_BARS = 12                 # excursion horizon, H1 bars
W_BARS = 12                 # max wait for the entry level to be touched
RR = 2.0                    # SilverBullet's fixed reward:risk
ATR10_MULT = 1.0            # the live stop model: sl = entry -/+ 1.0 * ATR
NY_SHIFT = -7               # broker -> NY hour offset (poc_sb_stops.py:42)
Q_FDR = 0.10
ECONOMIC_FLOOR_R = 0.25
SPLIT_FRAC = 0.70
EMBARGO_BUFFER_BARS = 4
BOOTSTRAP_DRAWS = 10000
SEED = 20260804
INJECT_TARGET_RHO = 0.15
MIN_CELL_N = 30

# Primary universe (11) and the live cost-viable subset (9), spec §2.1.
UNIVERSE_11 = ("AUDUSD", "BTCUSD", "EURUSD", "GBPCAD", "GBPJPY", "GBPUSD",
               "US30", "USDCAD", "USDJPY", "XAUUSD", "XBRUSD")
UNIVERSE_LIVE_9 = ("AUDUSD", "BTCUSD", "EURUSD", "GBPJPY", "GBPUSD",
                   "US30", "USDCAD", "USDJPY", "XAUUSD")
