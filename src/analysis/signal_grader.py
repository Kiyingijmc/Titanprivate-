# ==============================================================================
# FILE: src/analysis/signal_grader.py
# TYPE: SIGNAL QUALITY ENGINE (v14.4)
#
# Grades every strategy decision on confluence BEFORE execution, so only
# setups above a configurable quality floor reach the broker, and every
# signal (taken or skipped) is journaled with its grade and factor breakdown.
#
# Score (max 100):
#   HTF bias alignment   30  (aligned 30 / neutral 10 / counter 0)
#   Risk:Reward          20  (>=3R 20 / >=2R 15 / >=1.5R 8)
#   Displacement         20  (signal-candle body vs ATR)
#   PD array location    15  (buy in DISCOUNT / sell in PREMIUM)
#   Killzone timing      15  (London 02-05, NY AM 07-11, NY PM 13-16 NY time)
#
# Grades: A++ >=90, A+ >=80, A >=70, B >=55, C below.
# ==============================================================================


class SignalGrader:
    GRADES = [(90, "A++"), (80, "A+"), (70, "A"), (55, "B")]
    GRADE_RANK = {"C": 0, "B": 1, "A": 2, "A+": 3, "A++": 4}
    KILLZONES = [(2, 5), (7, 11), (13, 16)]  # NY-time hours, end exclusive

    def __init__(self, config=None):
        cfg = (config or {}).get('signal_grading', {})
        self.enabled = bool(cfg.get('enabled', True))
        self.min_grade = str(cfg.get('min_grade', 'B'))
        if self.min_grade not in self.GRADE_RANK:
            self.min_grade = 'B'

    def grade(self, decision, context, candle=None):
        """
        Returns {'score': int, 'grade': str, 'factors': [str, ...]}.
        decision: strategy dict {signal, price, sl, tp}
        context:  controller dict {bias, liquidity, ny_time}
        candle:   the signal candle (dict/Series with open/close/ATR), optional
        """
        score = 0
        factors = []
        side = decision.get('signal', '')
        context = context or {}

        # 1. HTF bias alignment
        bias = context.get('bias', 'NEUTRAL')
        if (bias == "BULLISH" and side == "BUY") or (bias == "BEARISH" and side == "SELL"):
            score += 30
            factors.append("bias_aligned +30")
        elif bias == "NEUTRAL":
            score += 10
            factors.append("bias_neutral +10")
        else:
            factors.append("bias_counter +0")

        # 2. Risk:Reward (epsilon-tolerant thresholds: floats like 1.4999999 are 1.5)
        eps = 1e-6
        try:
            entry = float(decision['price']); sl = float(decision['sl']); tp = float(decision['tp'])
            risk = abs(entry - sl)
            if risk <= 1e-12:
                # Degenerate signal (entry == SL): unexecutable, hard fail
                return {'score': 0, 'grade': 'C', 'factors': ['invalid_risk_distance']}
            rr = abs(tp - entry) / risk
        except (KeyError, TypeError, ValueError):
            rr = 0.0
        if rr >= 3.0 - eps: pts = 20
        elif rr >= 2.0 - eps: pts = 15
        elif rr >= 1.5 - eps: pts = 8
        else: pts = 0
        score += pts
        factors.append(f"rr={rr:.2f} +{pts}")

        # 3. Displacement strength (signal-candle body vs ATR)
        pts = 0
        if candle is not None:
            try:
                atr = float(candle.get('ATR', 0) if hasattr(candle, 'get') else candle['ATR'])
                body = abs(float(candle['close']) - float(candle['open']))
                ratio = body / atr if atr > 1e-12 else 0.0
                if ratio >= 1.5 - eps: pts = 20
                elif ratio >= 1.0 - eps: pts = 15
                elif ratio >= 0.8 - eps: pts = 10
                factors.append(f"displacement={ratio:.2f} +{pts}")
            except (KeyError, TypeError, ValueError):
                factors.append("displacement=n/a +0")
        else:
            factors.append("displacement=n/a +0")
        score += pts

        # 4. Premium/Discount array location
        status = (context.get('liquidity') or {}).get('STATUS', '')
        if (side == "BUY" and status == "DISCOUNT") or (side == "SELL" and status == "PREMIUM"):
            score += 15
            factors.append(f"pd_array={status} +15")
        elif status in ("", "EQ", None):
            score += 5
            factors.append("pd_array=eq/unknown +5")
        else:
            factors.append(f"pd_array={status} +0")

        # 5. Killzone timing
        pts = 0
        try:
            hour = int(str(context.get('ny_time', '')).split(':')[0])
            if any(start <= hour < end for start, end in self.KILLZONES):
                pts = 15
        except (ValueError, IndexError):
            pass
        score += pts
        factors.append(f"killzone +{pts}")

        return {'score': score, 'grade': self._to_grade(score), 'factors': factors}

    def _to_grade(self, score):
        for floor, g in self.GRADES:
            if score >= floor:
                return g
        return "C"

    def passes(self, grade):
        """Gate check against the configured quality floor."""
        if not self.enabled:
            return True
        return self.GRADE_RANK.get(grade, 0) >= self.GRADE_RANK[self.min_grade]
