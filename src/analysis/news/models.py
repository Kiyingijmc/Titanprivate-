"""The CalendarEvent contract every other unit in this package speaks."""
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

VALID_IMPORTANCE = ("HIGH", "MEDIUM", "LOW")


def make_key(currency: str, title: str, when_utc: datetime) -> str:
    """Stable cross-source identity. Times are floored into fixed 5-minute buckets.
    Note: two sources straddling a 5-minute bucket boundary will NOT dedup, even
    if they differ by only a minute or two."""
    if when_utc.tzinfo is None:
        raise ValueError("when_utc must be timezone-aware UTC")
    stamp = when_utc.astimezone(timezone.utc).replace(second=0, microsecond=0)
    bucket = stamp.replace(minute=(stamp.minute // 5) * 5)
    raw = f"{currency.strip().upper()}|{' '.join(title.split()).lower()}|{bucket.isoformat()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class CalendarEvent:
    key: str
    when_utc: datetime
    currency: str
    importance: str
    title: str
    forecast: str | None = None
    previous: str | None = None
    actual: str | None = None
    url: str | None = None
    source: str = "forexfactory"

    def __post_init__(self) -> None:
        if self.when_utc.tzinfo is None:
            raise ValueError("when_utc must be timezone-aware UTC")
        object.__setattr__(self, "when_utc", self.when_utc.astimezone(timezone.utc))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["when_utc"] = self.when_utc.astimezone(timezone.utc).isoformat()
        return d

    @staticmethod
    def from_dict(d: dict) -> "CalendarEvent":
        raw = dict(d)
        when = datetime.fromisoformat(raw.pop("when_utc"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return CalendarEvent(when_utc=when.astimezone(timezone.utc), **raw)
