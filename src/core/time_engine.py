# ==============================================================================
# FILE: src/core/time_engine.py
# TYPE: LEGACY REDIRECT
# AUDIT: 
#   1. Detected Duplicate Logic vs src/analysis/time_math.py.
#   2. Converted to Proxy Pattern to point to the Single Source of Truth.
#   3. Prevents "Split Brain" logic where two different time engines exist.
# STATUS: PRODUCTION READY
# ==============================================================================

# This file is maintained for backward compatibility.
# The core logic has been centralized in src.analysis.time_math to ensure
# precise timestamp handling across the Strategy and Execution layers.

from src.analysis.time_math import TimeNormalizer

# Re-exporting class for any legacy imports
__all__ = ['TimeNormalizer']