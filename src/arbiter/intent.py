"""Intent: a strategy's request to trade, submitted to the Arbiter.

Frozen and JSON-scalar so intents journal cleanly. Strategies never
execute; they emit Intents. The Arbiter decides.
"""
from dataclasses import dataclass, field, asdict

# Higher = better. Unknown grades rank 0 (worst).
GRADE_RANK = {"A++": 6, "A+": 5, "A": 4, "B+": 3, "B": 2, "C": 1}


def grade_rank(grade: str) -> int:
    return GRADE_RANK.get(grade, 0)


@dataclass(frozen=True)
class Intent:
    strategy_id: str          # manifest id (attribution key — NOT instance name)
    symbol: str
    direction: str            # "BUY" | "SELL"
    kind: str                 # "MARKET" | "LIMIT" | "STOP" (mirrors decision['type'])
    price: float
    sl: float
    tp: float
    grade: str = ""
    confidence: float = 0.0   # strategy-native [0,1]; 0.0 = not provided
    thesis_id: str = ""       # idempotency key; "" = auto (symbol:direction:price:sl)
    priority: int = 50        # manifest priority (lower wins ties)

    def effective_thesis(self) -> str:
        return self.thesis_id or f"{self.symbol}:{self.direction}:{self.price!r}:{self.sl!r}"

    def to_payload(self) -> dict:
        return asdict(self)
