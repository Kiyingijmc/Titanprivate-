# News Source Layer, Cache and Policy — Implementation Plan (Session 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-class `news_manager.py` with a small package that persists the
economic calendar to disk, blocks only red-folder events, and matches event currency to the
traded symbol — so a feed outage cannot halt the book and GBPJPY is gated by BOE/BOJ rather
than by US CPI.

**Architecture:** Five focused units behind a thin façade. A source fetches and normalises
events; a store persists and merges them; a pure policy decides blocking; the façade composes
them and keeps the controller's call sites small. Every event time is timezone-aware UTC at
the source boundary — no naive datetime may exist inside the package.

**Tech Stack:** Python 3.12, stdlib `unittest` (there is no pytest), `requests`, `pandas`
(already used by the existing parser), SQLite untouched. No new dependencies.

## Global Constraints

- Python ≥ 3.10. Run everything with `.venv/bin/python`.
- Tests are stdlib `unittest` under `tests/unit/`, named `test_*.py`. **There is no pytest.**
- Full suite command: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.
  It takes 10–105 minutes. Run **single modules** during development; run the full suite only
  before the final commit, and launch it detached (`setsid nohup … &`) so no harness timeout
  can cut it off.
- ForexFactory is the **PRIMARY** source. MT5 is a fallback and is **out of scope for this
  session** — do not add it.
- Only `importance == "HIGH"` may block trading. MEDIUM/LOW are carried for display only.
- All event times are **timezone-aware UTC**. Comparisons use `datetime.now(timezone.utc)`.
- Blackout window: **60 minutes before**, **30 minutes after** an event.
- `max_cache_age_hours` default **48**.
- Do not add new dependencies, layers, or frameworks.
- Work on a feature branch; `main` holds the baseline.
- The existing public entry points `NewsManager.update_calendar()` and
  `NewsManager.check_news_block(now=None)` must keep working until Task 7 migrates callers.

## File Structure

| Path | Responsibility |
|---|---|
| `src/analysis/news/__init__.py` | Re-exports `NewsManager` |
| `src/analysis/news/models.py` | `CalendarEvent` dataclass + `make_key` |
| `src/analysis/news/sources/__init__.py` | empty package marker |
| `src/analysis/news/sources/forexfactory.py` | CSV fetch + parse → `CalendarEvent` |
| `src/analysis/news/store.py` | `CalendarStore`: disk persistence, merge, staleness |
| `src/analysis/news/policy.py` | `NewsPolicy`: pure blocking decisions |
| `src/analysis/news/manager.py` | `NewsManager` façade composing the above |
| `src/analysis/news_manager.py` | **Deleted in Task 7** (shim removed, callers migrated) |
| `src/core/system_controller.py` | Per-symbol gate + global stale gate |
| `config/config.yaml` | New `news:` block |
| `.gitignore` | Ignore `data/news/` |

---

### Task 1: `CalendarEvent` model

**Files:**
- Create: `src/analysis/news/__init__.py`, `src/analysis/news/models.py`
- Test: `tests/unit/test_news_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CalendarEvent` frozen dataclass with fields `key: str`, `when_utc: datetime`,
  `currency: str`, `importance: str`, `title: str`, `forecast: str | None`,
  `previous: str | None`, `actual: str | None`, `url: str | None`, `source: str`.
  Also `make_key(currency: str, title: str, when_utc: datetime) -> str` and
  `CalendarEvent.to_dict() -> dict` / `CalendarEvent.from_dict(d: dict) -> CalendarEvent`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_news_models.py`:

```python
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.models import CalendarEvent, make_key


class MakeKey(unittest.TestCase):
    def test_same_event_within_five_minutes_gets_one_key(self):
        """Sources disagree by a minute or two; that must not create duplicates."""
        a = make_key("USD", "Core CPI m/m", datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc))
        b = make_key("USD", "core cpi m/m ", datetime(2026, 7, 30, 12, 32, tzinfo=timezone.utc))
        self.assertEqual(a, b)

    def test_different_events_get_different_keys(self):
        a = make_key("USD", "Core CPI m/m", datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc))
        b = make_key("EUR", "Core CPI m/m", datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc))
        self.assertNotEqual(a, b)

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            make_key("USD", "Core CPI m/m", datetime(2026, 7, 30, 12, 30))


class Roundtrip(unittest.TestCase):
    def _event(self):
        when = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
        return CalendarEvent(
            key=make_key("USD", "Core PCE", when), when_utc=when, currency="USD",
            importance="HIGH", title="Core PCE", forecast="0.3%", previous="0.2%",
            actual=None, url="https://example.test/1", source="forexfactory")

    def test_to_dict_from_dict_roundtrips(self):
        original = self._event()
        self.assertEqual(CalendarEvent.from_dict(original.to_dict()), original)

    def test_roundtrip_preserves_utc_awareness(self):
        restored = CalendarEvent.from_dict(self._event().to_dict())
        self.assertEqual(restored.when_utc.tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_news_models -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.news'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/analysis/news/__init__.py`:

```python
"""Economic-calendar sourcing, caching and blocking policy."""
```

Create `src/analysis/news/models.py`:

```python
"""The CalendarEvent contract every other unit in this package speaks."""
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

VALID_IMPORTANCE = ("HIGH", "MEDIUM", "LOW")


def make_key(currency: str, title: str, when_utc: datetime) -> str:
    """Stable cross-source identity. Times are rounded to 5 minutes so two
    sources that disagree slightly about a release time still dedup."""
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_news_models -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/news/__init__.py src/analysis/news/models.py tests/unit/test_news_models.py
git commit -m "feat(news): CalendarEvent model with UTC-only times and stable dedup key"
```

---

### Task 2: ForexFactory CSV parsing (pure)

**Files:**
- Create: `src/analysis/news/sources/__init__.py`, `src/analysis/news/sources/forexfactory.py`
- Test: `tests/unit/test_news_forexfactory_parse.py`

**Interfaces:**
- Consumes: `CalendarEvent`, `make_key` from Task 1.
- Produces: `ForexFactoryCsvSource(logger, url=None, tz=timezone.utc)` with
  `parse(csv_text: str) -> list[CalendarEvent]` (pure) and class attribute
  `URL: str`. `NAME = "forexfactory"`.

The live CSV header is exactly
`Title,Country,Date,Time,Impact,Forecast,Previous,URL`. Times are **UTC** — verified against
FOMC `6:00pm` = 18:00Z = 14:00 ET. Unlike the old parser, keep **all** currencies and **all**
impact tiers; filtering is the policy's job, not the source's.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_news_forexfactory_parse.py`:

```python
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.sources.forexfactory import ForexFactoryCsvSource


class _StubLogger:
    def log_event(self, *args, **kwargs):
        pass


CSV = (
    "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
    "FOMC Statement,USD,07-29-2026,6:00pm,High,,,https://example.test/1\n"
    "Core PCE Price Index m/m,USD,07-30-2026,12:30pm,High,0.3%,0.2%,https://example.test/2\n"
    "German ifo Business Climate,EUR,07-27-2026,8:00am,Low,86.1,85.6,https://example.test/3\n"
    "BOE Rate Decision,GBP,07-30-2026,11:00am,High,4.00%,4.25%,https://example.test/4\n"
    "Bank Holiday,JPY,07-28-2026,All Day,Holiday,,,https://example.test/5\n"
)


def _parse():
    return ForexFactoryCsvSource(_StubLogger()).parse(CSV)


class ParsesTimesAsUtc(unittest.TestCase):
    def test_six_pm_becomes_1800z(self):
        fomc = next(e for e in _parse() if e.title == "FOMC Statement")
        self.assertEqual(fomc.when_utc, datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc))


class KeepsEverythingThePolicyMightNeed(unittest.TestCase):
    def test_keeps_non_usd_currencies(self):
        self.assertIn("GBP", {e.currency for e in _parse()})

    def test_keeps_non_high_impact_rows(self):
        self.assertIn("LOW", {e.importance for e in _parse()})

    def test_captures_forecast_previous_and_url(self):
        pce = next(e for e in _parse() if e.title.startswith("Core PCE"))
        self.assertEqual(pce.forecast, "0.3%")
        self.assertEqual(pce.previous, "0.2%")
        self.assertEqual(pce.url, "https://example.test/2")

    def test_blank_forecast_becomes_none_not_empty_string(self):
        fomc = next(e for e in _parse() if e.title == "FOMC Statement")
        self.assertIsNone(fomc.forecast)


class HandlesMalformedInput(unittest.TestCase):
    def test_unparseable_time_row_is_skipped_not_fatal(self):
        """'All Day' has no clock time; drop that row, keep the rest."""
        titles = {e.title for e in _parse()}
        self.assertNotIn("Bank Holiday", titles)
        self.assertIn("FOMC Statement", titles)

    def test_wrong_schema_returns_empty_list(self):
        bad = ForexFactoryCsvSource(_StubLogger()).parse("Foo,Bar\n1,2\n")
        self.assertEqual(bad, [])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(ForexFactoryCsvSource(_StubLogger()).parse(""), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_news_forexfactory_parse -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.news.sources'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/analysis/news/sources/__init__.py`:

```python
"""Calendar sources. ForexFactory is primary; MT5 is a later-session fallback."""
```

Create `src/analysis/news/sources/forexfactory.py`:

```python
"""ForexFactory weekly CSV — the PRIMARY calendar source.

Times in this feed are UTC. Verified 2026-07-31 against three known releases:
FOMC 6:00pm = 18:00Z (14:00 ET), FOMC presser 6:30pm = 18:30Z, Advance GDP and
Core PCE 12:30pm = 12:30Z (08:30 ET). Were the feed US Eastern, FOMC would read
2:00pm. Treating these as local time is the defect fixed in commit ec883ae.
"""
import csv
import io
from datetime import datetime, timezone

from ..models import CalendarEvent, make_key

_REQUIRED = ("Title", "Country", "Date", "Time", "Impact")
_IMPORTANCE = {"high": "HIGH", "medium": "MEDIUM", "moderate": "MEDIUM", "low": "LOW"}


class ForexFactoryCsvSource:
    NAME = "forexfactory"
    URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.csv"

    def __init__(self, logger, url: str | None = None, tz=timezone.utc):
        self.logger = logger
        self.url = url or self.URL
        self.tz = tz

    def parse(self, csv_text: str) -> list[CalendarEvent]:
        """Pure: CSV text -> events. Never raises; returns [] on bad input."""
        if not csv_text or not csv_text.strip():
            return []
        try:
            reader = csv.DictReader(io.StringIO(csv_text))
            fields = [(f or "").strip() for f in (reader.fieldnames or [])]
            if not all(col in fields for col in _REQUIRED):
                self.logger.log_event("ERROR", "NEWS", f"CSV schema mismatch: {fields}")
                return []
            events = []
            for row in reader:
                event = self._row_to_event(row)
                if event is not None:
                    events.append(event)
            return events
        except Exception as exc:  # malformed CSV must never kill the caller
            self.logger.log_event("ERROR", "NEWS", f"Parse error: {exc}")
            return []

    def _row_to_event(self, row: dict) -> CalendarEvent | None:
        try:
            stamp = f"{(row.get('Date') or '').strip()} {(row.get('Time') or '').strip()}"
            when = datetime.strptime(stamp, "%m-%d-%Y %I:%M%p").replace(tzinfo=self.tz)
        except (ValueError, TypeError):
            return None  # "All Day", "Tentative", locale drift -> skip this row only
        currency = (row.get("Country") or "").strip().upper()
        title = " ".join((row.get("Title") or "").split())
        if not currency or not title:
            return None
        when = when.astimezone(timezone.utc)
        return CalendarEvent(
            key=make_key(currency, title, when),
            when_utc=when,
            currency=currency,
            importance=_IMPORTANCE.get((row.get("Impact") or "").strip().lower(), "LOW"),
            title=title,
            forecast=_clean(row.get("Forecast")),
            previous=_clean(row.get("Previous")),
            actual=None,
            url=_clean(row.get("URL")),
            source=self.NAME,
        )


def _clean(value) -> str | None:
    text = (value or "").strip()
    return text or None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_news_forexfactory_parse -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/news/sources/ tests/unit/test_news_forexfactory_parse.py
git commit -m "feat(news): ForexFactory CSV parser keeping all currencies, tiers, forecast/previous"
```

---

### Task 3: ForexFactory fetching with retries

**Files:**
- Modify: `src/analysis/news/sources/forexfactory.py`
- Test: `tests/unit/test_news_forexfactory_fetch.py`

**Interfaces:**
- Consumes: Task 2's `ForexFactoryCsvSource.parse`.
- Produces: `async def fetch(self) -> list[CalendarEvent]` — returns parsed events on success,
  raises `NewsFetchError` when all retries are exhausted. Also exports
  `NewsFetchError(Exception)` from the same module.

Raising on exhaustion (rather than returning `[]`) matters: the store must be able to tell
"the feed said there are no events" from "the feed did not answer", because only the second
one may eventually trip the stale-cache halt.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_news_forexfactory_fetch.py`:

```python
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.sources.forexfactory import ForexFactoryCsvSource, NewsFetchError


class _StubLogger:
    def log_event(self, *args, **kwargs):
        pass


CSV = (
    "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
    "FOMC Statement,USD,07-29-2026,6:00pm,High,,,https://example.test/1\n"
)


class _Response:
    def __init__(self, status_code, body=""):
        self.status_code = status_code
        self.content = body.encode("utf-8")


def _run(coro):
    """The repo's fresh-loop idiom: py3.12 deprecates get_event_loop()."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FetchSucceeds(unittest.TestCase):
    def test_returns_parsed_events_on_first_try(self):
        src = ForexFactoryCsvSource(_StubLogger())
        src._get = lambda: _Response(200, CSV)
        events = _run(src.fetch())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].title, "FOMC Statement")

    def test_retries_then_succeeds(self):
        src = ForexFactoryCsvSource(_StubLogger())
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("boom")
            return _Response(200, CSV)

        src._get = flaky
        src.backoff_base_s = 0  # keep the test fast
        self.assertEqual(len(_run(src.fetch())), 1)
        self.assertEqual(calls["n"], 3)


class FetchFails(unittest.TestCase):
    def test_raises_after_all_retries_exhausted(self):
        src = ForexFactoryCsvSource(_StubLogger())
        src.backoff_base_s = 0

        def dead():
            raise ConnectionError("down")

        src._get = dead
        with self.assertRaises(NewsFetchError):
            _run(src.fetch())

    def test_http_error_status_raises(self):
        src = ForexFactoryCsvSource(_StubLogger())
        src.backoff_base_s = 0
        src._get = lambda: _Response(503)
        with self.assertRaises(NewsFetchError):
            _run(src.fetch())

    def test_empty_event_list_is_success_not_failure(self):
        """A week with no parseable rows is data, not an outage."""
        src = ForexFactoryCsvSource(_StubLogger())
        header_only = "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
        src._get = lambda: _Response(200, header_only)
        self.assertEqual(_run(src.fetch()), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_news_forexfactory_fetch -v`
Expected: FAIL — `ImportError: cannot import name 'NewsFetchError'`

- [ ] **Step 3: Write the minimal implementation**

In `src/analysis/news/sources/forexfactory.py`, add to the imports at the top:

```python
import asyncio
import random

import requests
```

Add after the `_IMPORTANCE` constant:

```python
class NewsFetchError(Exception):
    """All retries exhausted. Distinct from 'the feed returned no events'."""


_USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
)
```

Add these attributes at the end of `__init__`:

```python
        self.max_retries = 3
        self.backoff_base_s = 1.0
        self.timeout_s = 15
```

Add these methods to `ForexFactoryCsvSource`:

```python
    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _get(self):
        """Blocking HTTP. Isolated so tests can substitute it."""
        return requests.get(self.url, headers=self._headers(), timeout=self.timeout_s)

    async def fetch(self) -> list[CalendarEvent]:
        """Returns parsed events, or raises NewsFetchError if the feed never answered."""
        last = "no attempt made"
        for attempt in range(self.max_retries):
            try:
                response = await asyncio.to_thread(self._get)
                if response.status_code == 200:
                    return self.parse(response.content.decode("utf-8", "replace"))
                last = f"HTTP {response.status_code}"
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
            self.logger.log_event("WARN", "NEWS", f"Attempt {attempt + 1}: {last}")
            if attempt < self.max_retries - 1 and self.backoff_base_s:
                await asyncio.sleep(self.backoff_base_s * (2 ** attempt))
        raise NewsFetchError(last)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_news_forexfactory_fetch -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/news/sources/forexfactory.py tests/unit/test_news_forexfactory_fetch.py
git commit -m "feat(news): ForexFactory fetch with retries; raise NewsFetchError on exhaustion"
```

---

### Task 4: `CalendarStore` — disk cache and merge

**Files:**
- Create: `src/analysis/news/store.py`
- Test: `tests/unit/test_news_store.py`

**Interfaces:**
- Consumes: `CalendarEvent` from Task 1.
- Produces: `CalendarStore(path: str)` with `load() -> None`,
  `merge(events: list[CalendarEvent], source: str, now_utc: datetime) -> None`,
  `save() -> None`, `events() -> list[CalendarEvent]` (sorted by `when_utc`),
  `last_success(source: str) -> datetime | None`, and
  `age(now_utc: datetime) -> timedelta | None` (`None` when nothing has ever succeeded).

Merge rule: incoming wins on `importance` and `when_utc`; fields the incoming event leaves
empty keep the stored value. That handles repeated ForexFactory fetches today and extends
unchanged to the MT5 fallback in Session 3.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_news_store.py`:

```python
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.models import CalendarEvent, make_key
from src.analysis.news.store import CalendarStore

NOW = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)


def _event(title="Core PCE", currency="USD", importance="HIGH", hour=12,
           forecast=None, source="forexfactory"):
    when = datetime(2026, 7, 30, hour, 30, tzinfo=timezone.utc)
    return CalendarEvent(key=make_key(currency, title, when), when_utc=when,
                         currency=currency, importance=importance, title=title,
                         forecast=forecast, source=source)


class Persistence(unittest.TestCase):
    def test_events_survive_a_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "news", "calendar.json")
            store = CalendarStore(path)
            store.merge([_event()], "forexfactory", NOW)
            store.save()

            reloaded = CalendarStore(path)
            reloaded.load()
            self.assertEqual(len(reloaded.events()), 1)
            self.assertEqual(reloaded.events()[0].title, "Core PCE")

    def test_creates_missing_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deep", "nested", "calendar.json")
            store = CalendarStore(path)
            store.merge([_event()], "forexfactory", NOW)
            store.save()
            self.assertTrue(os.path.isfile(path))

    def test_load_of_missing_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CalendarStore(os.path.join(tmp, "absent.json"))
            store.load()
            self.assertEqual(store.events(), [])

    def test_load_of_corrupt_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            with open(path, "w") as fh:
                fh.write("{not json")
            store = CalendarStore(path)
            store.load()
            self.assertEqual(store.events(), [])

    def test_save_leaves_no_temp_file_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            store = CalendarStore(path)
            store.merge([_event()], "forexfactory", NOW)
            store.save()
            self.assertEqual(sorted(os.listdir(tmp)), ["calendar.json"])

    def test_saved_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "calendar.json")
            store = CalendarStore(path)
            store.merge([_event()], "forexfactory", NOW)
            store.save()
            with open(path) as fh:
                json.load(fh)


class Merging(unittest.TestCase):
    def test_same_event_twice_stays_one_row(self):
        store = CalendarStore("unused")
        store.merge([_event()], "forexfactory", NOW)
        store.merge([_event()], "forexfactory", NOW)
        self.assertEqual(len(store.events()), 1)

    def test_incoming_wins_on_importance(self):
        store = CalendarStore("unused")
        store.merge([_event(importance="LOW")], "forexfactory", NOW)
        store.merge([_event(importance="HIGH")], "forexfactory", NOW)
        self.assertEqual(store.events()[0].importance, "HIGH")

    def test_incoming_blank_field_does_not_erase_stored_value(self):
        store = CalendarStore("unused")
        store.merge([_event(forecast="0.3%")], "forexfactory", NOW)
        store.merge([_event(forecast=None)], "forexfactory", NOW)
        self.assertEqual(store.events()[0].forecast, "0.3%")

    def test_events_are_sorted_by_time(self):
        store = CalendarStore("unused")
        store.merge([_event(title="Later", hour=15), _event(title="Earlier", hour=9)],
                    "forexfactory", NOW)
        self.assertEqual([e.title for e in store.events()], ["Earlier", "Later"])


class Staleness(unittest.TestCase):
    def test_age_is_none_before_any_success(self):
        self.assertIsNone(CalendarStore("unused").age(NOW))

    def test_age_measures_from_last_success(self):
        store = CalendarStore("unused")
        store.merge([_event()], "forexfactory", NOW - timedelta(hours=5))
        self.assertEqual(store.age(NOW), timedelta(hours=5))

    def test_last_success_is_tracked_per_source(self):
        store = CalendarStore("unused")
        store.merge([_event()], "forexfactory", NOW)
        self.assertEqual(store.last_success("forexfactory"), NOW)
        self.assertIsNone(store.last_success("mt5"))

    def test_age_uses_the_most_recent_source(self):
        store = CalendarStore("unused")
        store.merge([_event()], "forexfactory", NOW - timedelta(hours=9))
        store.merge([_event()], "mt5", NOW - timedelta(hours=2))
        self.assertEqual(store.age(NOW), timedelta(hours=2))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_news_store -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.news.store'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/analysis/news/store.py`:

```python
"""Disk-persisted calendar cache.

One ForexFactory fetch returns the whole week, so persisting it takes the
network off the critical path: a feed outage cannot blind us to Thursday's NFP
when we already learned about it on Monday. Only a cache that has gone stale
for days is dangerous, and that is the sole condition that halts trading.
"""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

from .models import CalendarEvent


class CalendarStore:
    def __init__(self, path: str):
        self.path = path
        self._events: dict[str, CalendarEvent] = {}
        self._last_success: dict[str, datetime] = {}

    # --- reading -----------------------------------------------------------
    def events(self) -> list[CalendarEvent]:
        return sorted(self._events.values(), key=lambda e: e.when_utc)

    def last_success(self, source: str) -> datetime | None:
        return self._last_success.get(source)

    def age(self, now_utc: datetime) -> timedelta | None:
        """Time since the most recent successful refresh from ANY source."""
        if not self._last_success:
            return None
        return now_utc - max(self._last_success.values())

    # --- writing -----------------------------------------------------------
    def merge(self, events, source: str, now_utc: datetime) -> None:
        for incoming in events:
            stored = self._events.get(incoming.key)
            self._events[incoming.key] = (
                incoming if stored is None else _prefer(incoming, stored))
        self._last_success[source] = now_utc

    def save(self) -> None:
        payload = {
            "events": [e.to_dict() for e in self.events()],
            "last_success": {k: v.isoformat() for k, v in self._last_success.items()},
        }
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        handle, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, self.path)  # atomic: readers never see a partial file
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def load(self) -> None:
        """A missing or corrupt cache is an empty cache, never an exception."""
        try:
            with open(self.path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            return
        try:
            self._events = {}
            for raw in payload.get("events", []):
                event = CalendarEvent.from_dict(raw)
                self._events[event.key] = event
            self._last_success = {
                k: _as_utc(datetime.fromisoformat(v))
                for k, v in (payload.get("last_success") or {}).items()
            }
        except (TypeError, ValueError, KeyError):
            self._events = {}
            self._last_success = {}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _prefer(incoming: CalendarEvent, stored: CalendarEvent) -> CalendarEvent:
    """Incoming wins on importance and timing; blanks never erase known values."""
    return CalendarEvent(
        key=incoming.key,
        when_utc=incoming.when_utc,
        currency=incoming.currency,
        importance=incoming.importance,
        title=incoming.title,
        forecast=incoming.forecast or stored.forecast,
        previous=incoming.previous or stored.previous,
        actual=incoming.actual or stored.actual,
        url=incoming.url or stored.url,
        source=incoming.source,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_news_store -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/news/store.py tests/unit/test_news_store.py
git commit -m "feat(news): disk-persisted CalendarStore with atomic write and per-source staleness"
```

---

### Task 5: `NewsPolicy` — pure blocking decisions

**Files:**
- Create: `src/analysis/news/policy.py`
- Test: `tests/unit/test_news_policy.py`

**Interfaces:**
- Consumes: `CalendarEvent` from Task 1.
- Produces: `NewsPolicy(config: dict | None = None)` with
  `currencies_for(symbol: str) -> list[str]`,
  `blocking_event(events, symbol, now_utc) -> CalendarEvent | None`,
  `reason_for(event, now_utc) -> str`, and `is_stale(age: timedelta | None) -> bool`.
  Exposes `.window_pre`, `.window_post` as `timedelta`, and `.max_cache_age` as `timedelta`.

This unit is pure — no I/O, no ambient clock. That is what makes code that can stop the book
testable; the module it replaces had zero tests.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_news_policy.py`:

```python
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.models import CalendarEvent, make_key
from src.analysis.news.policy import NewsPolicy

RELEASE = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)

CONFIG = {"news": {"symbol_currencies": {
    "EURUSD": ["EUR", "USD"], "GBPJPY": ["GBP", "JPY"], "XAUUSD": ["USD"],
}}}


def _event(currency="USD", importance="HIGH", title="Core PCE", when=RELEASE):
    return CalendarEvent(key=make_key(currency, title, when), when_utc=when,
                         currency=currency, importance=importance, title=title)


class CurrencyMapping(unittest.TestCase):
    def test_configured_symbol_uses_its_mapping(self):
        self.assertEqual(NewsPolicy(CONFIG).currencies_for("GBPJPY"), ["GBP", "JPY"])

    def test_unmapped_forex_pair_is_inferred_from_its_name(self):
        self.assertEqual(NewsPolicy({}).currencies_for("USDCHF"), ["USD", "CHF"])

    def test_unmapped_metal_infers_only_the_quote_currency(self):
        """XAU is not a fiat currency; XAUUSD is exposed to USD news."""
        self.assertEqual(NewsPolicy({}).currencies_for("XAUUSD"), ["USD"])

    def test_uninferrable_symbol_defaults_to_usd_not_empty(self):
        """An empty list would fail OPEN -- nothing would ever block."""
        self.assertEqual(NewsPolicy({}).currencies_for("US30"), ["USD"])


class OnlyRedFolderBlocks(unittest.TestCase):
    def test_high_impact_blocks(self):
        policy = NewsPolicy(CONFIG)
        self.assertIsNotNone(policy.blocking_event([_event()], "EURUSD", RELEASE))

    def test_medium_impact_never_blocks(self):
        policy = NewsPolicy(CONFIG)
        self.assertIsNone(
            policy.blocking_event([_event(importance="MEDIUM")], "EURUSD", RELEASE))

    def test_low_impact_never_blocks(self):
        policy = NewsPolicy(CONFIG)
        self.assertIsNone(
            policy.blocking_event([_event(importance="LOW")], "EURUSD", RELEASE))


class CurrencyMatching(unittest.TestCase):
    def test_usd_event_does_not_block_gbpjpy(self):
        """The proof-of-fix: GBPJPY holds no USD, so US CPI is irrelevant to it."""
        policy = NewsPolicy(CONFIG)
        self.assertIsNone(policy.blocking_event([_event("USD")], "GBPJPY", RELEASE))

    def test_gbp_event_blocks_gbpjpy(self):
        policy = NewsPolicy(CONFIG)
        event = _event("GBP", title="BOE Rate Decision")
        self.assertIsNotNone(policy.blocking_event([event], "GBPJPY", RELEASE))

    def test_jpy_event_blocks_gbpjpy(self):
        policy = NewsPolicy(CONFIG)
        event = _event("JPY", title="BOJ Policy Rate")
        self.assertIsNotNone(policy.blocking_event([event], "GBPJPY", RELEASE))

    def test_usd_event_blocks_xauusd(self):
        policy = NewsPolicy(CONFIG)
        self.assertIsNotNone(policy.blocking_event([_event("USD")], "XAUUSD", RELEASE))


class BlackoutWindow(unittest.TestCase):
    def _blocked_at(self, offset_min):
        policy = NewsPolicy(CONFIG)
        moment = RELEASE + timedelta(minutes=offset_min)
        return policy.blocking_event([_event()], "EURUSD", moment) is not None

    def test_blocked_thirty_minutes_before(self):
        self.assertTrue(self._blocked_at(-30))

    def test_blocked_at_the_release(self):
        self.assertTrue(self._blocked_at(0))

    def test_blocked_twenty_minutes_after(self):
        self.assertTrue(self._blocked_at(20))

    def test_clear_ninety_minutes_before(self):
        self.assertFalse(self._blocked_at(-90))

    def test_clear_forty_minutes_after(self):
        self.assertFalse(self._blocked_at(40))

    def test_reason_names_the_event(self):
        policy = NewsPolicy(CONFIG)
        event = policy.blocking_event([_event()], "EURUSD", RELEASE)
        self.assertIn("Core PCE", policy.reason_for(event, RELEASE))


class Staleness(unittest.TestCase):
    def test_never_refreshed_counts_as_stale(self):
        self.assertTrue(NewsPolicy({}).is_stale(None))

    def test_fresh_cache_is_not_stale(self):
        self.assertFalse(NewsPolicy({}).is_stale(timedelta(hours=6)))

    def test_cache_past_the_ceiling_is_stale(self):
        self.assertTrue(NewsPolicy({}).is_stale(timedelta(hours=49)))

    def test_ceiling_is_configurable(self):
        policy = NewsPolicy({"news": {"max_cache_age_hours": 12}})
        self.assertTrue(policy.is_stale(timedelta(hours=13)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_news_policy -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.news.policy'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/analysis/news/policy.py`:

```python
"""Pure blocking policy: which red-folder events gate which symbols, and when.

No I/O and no ambient clock -- `now_utc` is always passed in. Only HIGH
importance may block; MEDIUM/LOW are carried purely for display.
"""
from datetime import timedelta

# Fiat codes we are willing to infer from a symbol name. XAU/XAG/BTC/ETH are
# deliberately absent: they are instruments, not the currency whose calendar
# moves them, so XAUUSD correctly resolves to USD alone.
_FIAT = frozenset(("USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD"))


class NewsPolicy:
    def __init__(self, config: dict | None = None):
        cfg = (config or {}).get("news", {}) or {}
        self.window_pre = timedelta(minutes=int(cfg.get("window_pre_min", 60)))
        self.window_post = timedelta(minutes=int(cfg.get("window_post_min", 30)))
        self.max_cache_age = timedelta(hours=int(cfg.get("max_cache_age_hours", 48)))
        self._map = {
            str(k).upper(): [str(c).upper() for c in (v or [])]
            for k, v in (cfg.get("symbol_currencies") or {}).items()
        }
        self._warned: set[str] = set()
        self.logger = None  # optional; set by NewsManager so fallbacks are visible

    def currencies_for(self, symbol: str) -> list[str]:
        name = (symbol or "").upper()
        mapped = self._map.get(name)
        if mapped:
            return mapped
        inferred = [name[i:i + 3] for i in range(0, max(len(name) - 2, 0))
                    if name[i:i + 3] in _FIAT]
        deduped = list(dict.fromkeys(inferred))
        if deduped:
            return deduped
        if name not in self._warned:
            self._warned.add(name)
            if self.logger is not None:
                self.logger.log_event(
                    "WARN", "NEWS",
                    f"No currency mapping for {name}; defaulting to USD. "
                    f"Add it to news.symbol_currencies in config.yaml.")
        return ["USD"]  # never [] -- an empty list would fail OPEN

    def blocking_event(self, events, symbol: str, now_utc):
        """The first red-folder event inside `symbol`'s blackout window, else None."""
        wanted = set(self.currencies_for(symbol))
        for event in events:
            if event.importance != "HIGH" or event.currency not in wanted:
                continue
            if -self.window_post <= (event.when_utc - now_utc) <= self.window_pre:
                return event
        return None

    def reason_for(self, event, now_utc) -> str:
        minutes = (event.when_utc - now_utc).total_seconds() / 60.0
        if minutes > 0:
            return f"{event.currency} {event.title} in {int(minutes)}m"
        return f"{event.currency} {event.title} active ({int(-minutes)}m ago)"

    def is_stale(self, age) -> bool:
        """No successful refresh ever, or older than the ceiling."""
        return age is None or age > self.max_cache_age
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_news_policy -v`
Expected: PASS (21 tests)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/news/policy.py tests/unit/test_news_policy.py
git commit -m "feat(news): pure NewsPolicy — red-folder only, per-symbol currency matching"
```

---

### Task 6: `NewsManager` façade and the failure ladder

**Files:**
- Create: `src/analysis/news/manager.py`
- Modify: `src/analysis/news/__init__.py`
- Test: `tests/unit/test_news_manager_failure_ladder.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: `NewsManager(logger, config=None, source=None, store=None)` with
  `async update_calendar() -> None`,
  `check_symbol(symbol, now=None) -> tuple[bool, str | None]`,
  `is_globally_blocked(now=None) -> tuple[bool, str | None]`, and
  `snapshot(now=None) -> dict` (consumed by Session 2). Attribute
  `feed_degraded: bool` is True when the last refresh failed but the cache is still usable.

The failure ladder is the point of this task: feed down with a fresh cache must keep trading.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_news_manager_failure_ladder.py`:

```python
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.manager import NewsManager
from src.analysis.news.models import CalendarEvent, make_key
from src.analysis.news.sources.forexfactory import NewsFetchError
from src.analysis.news.store import CalendarStore

RELEASE = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
CONFIG = {"news": {"symbol_currencies": {"EURUSD": ["EUR", "USD"], "GBPJPY": ["GBP", "JPY"]}}}


class _StubLogger:
    def log_event(self, *args, **kwargs):
        pass


class _Source:
    NAME = "forexfactory"

    def __init__(self, events=None, error=None):
        self.events = events or []
        self.error = error

    async def fetch(self):
        if self.error:
            raise self.error
        return self.events


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _pce():
    return CalendarEvent(key=make_key("USD", "Core PCE", RELEASE), when_utc=RELEASE,
                         currency="USD", importance="HIGH", title="Core PCE")


def _manager(source, store=None):
    manager = NewsManager(_StubLogger(), config=CONFIG, source=source,
                          store=store or CalendarStore(os.devnull))
    return manager


class HealthyFeed(unittest.TestCase):
    def test_blocks_the_matching_symbol(self):
        manager = _manager(_Source([_pce()]))
        _run(manager.update_calendar())
        blocked, reason = manager.check_symbol("EURUSD", now=RELEASE)
        self.assertTrue(blocked)
        self.assertIn("Core PCE", reason)

    def test_does_not_block_an_unrelated_symbol(self):
        manager = _manager(_Source([_pce()]))
        _run(manager.update_calendar())
        blocked, _ = manager.check_symbol("GBPJPY", now=RELEASE)
        self.assertFalse(blocked)


class FeedDownButCacheFresh(unittest.TestCase):
    """The whole point: an outage must not halt the book."""

    def _primed_store(self):
        store = CalendarStore(os.devnull)
        store.merge([_pce()], "forexfactory", RELEASE - timedelta(hours=2))
        return store

    def test_trading_is_not_globally_halted(self):
        manager = _manager(_Source(error=NewsFetchError("down")), self._primed_store())
        _run(manager.update_calendar())
        halted, _ = manager.is_globally_blocked(now=RELEASE)
        self.assertFalse(halted)

    def test_blackouts_are_still_enforced_from_cache(self):
        manager = _manager(_Source(error=NewsFetchError("down")), self._primed_store())
        _run(manager.update_calendar())
        blocked, _ = manager.check_symbol("EURUSD", now=RELEASE)
        self.assertTrue(blocked)

    def test_degraded_flag_is_raised(self):
        manager = _manager(_Source(error=NewsFetchError("down")), self._primed_store())
        _run(manager.update_calendar())
        self.assertTrue(manager.feed_degraded)


class FeedDownAndCacheStale(unittest.TestCase):
    def test_halts_globally_when_cache_exceeds_the_ceiling(self):
        store = CalendarStore(os.devnull)
        store.merge([_pce()], "forexfactory", RELEASE - timedelta(hours=72))
        manager = _manager(_Source(error=NewsFetchError("down")), store)
        _run(manager.update_calendar())
        halted, reason = manager.is_globally_blocked(now=RELEASE)
        self.assertTrue(halted)
        self.assertIn("stale", reason.lower())

    def test_halts_when_nothing_was_ever_fetched(self):
        manager = _manager(_Source(error=NewsFetchError("down")))
        _run(manager.update_calendar())
        halted, _ = manager.is_globally_blocked(now=RELEASE)
        self.assertTrue(halted)

    def test_stale_cache_also_blocks_every_symbol(self):
        manager = _manager(_Source(error=NewsFetchError("down")))
        _run(manager.update_calendar())
        blocked, _ = manager.check_symbol("GBPJPY", now=RELEASE)
        self.assertTrue(blocked)


class Snapshot(unittest.TestCase):
    def test_reports_next_event_and_source_health(self):
        manager = _manager(_Source([_pce()]))
        _run(manager.update_calendar())
        snap = manager.snapshot(now=RELEASE - timedelta(minutes=45))
        self.assertEqual(snap["status"], "ok")
        self.assertEqual(snap["next"]["title"], "Core PCE")
        self.assertIn("EURUSD", snap["next"]["affects"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_news_manager_failure_ladder -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.news.manager'`

- [ ] **Step 3: Write the minimal implementation**

Create `src/analysis/news/manager.py`:

```python
"""Façade composing source + store + policy, and the failure ladder.

  feed OK                      -> normal, cache refreshed
  feed down, cache fresh       -> TRADING CONTINUES, blackouts from cache
  feed down, cache stale/empty -> fail closed globally
"""
from datetime import datetime, timezone

from .policy import NewsPolicy
from .sources.forexfactory import ForexFactoryCsvSource
from .store import CalendarStore

_DEFAULT_CACHE = "data/news/calendar.json"


class NewsManager:
    def __init__(self, logger, config=None, source=None, store=None):
        cfg = (config or {}).get("news", {}) or {}
        self.logger = logger
        self.enabled = bool(cfg.get("enabled", True))
        self.refresh_interval_s = float(cfg.get("refresh_interval_min", 60)) * 60.0
        self.policy = NewsPolicy(config)
        self.policy.logger = logger
        self.source = source or ForexFactoryCsvSource(logger)
        self.store = store or CalendarStore(cfg.get("cache_path", _DEFAULT_CACHE))
        self.store.load()
        self.feed_degraded = False
        self._last_attempt = None

    async def update_calendar(self) -> None:
        now = datetime.now(timezone.utc)
        if self._last_attempt is not None:
            if (now - self._last_attempt).total_seconds() < self.refresh_interval_s:
                return
        self._last_attempt = now
        try:
            events = await self.source.fetch()
        except Exception as exc:
            self.feed_degraded = True
            self.logger.log_event(
                "WARN", "NEWS",
                f"Refresh failed ({exc}); serving cached calendar "
                f"(age {self._age_text(now)}).")
            return
        self.store.merge(events, getattr(self.source, "NAME", "forexfactory"), now)
        try:
            self.store.save()
        except Exception as exc:  # a cache we cannot persist is still usable in RAM
            self.logger.log_event("WARN", "NEWS", f"Cache write failed: {exc}")
        self.feed_degraded = False
        self.logger.log_event("INFO", "NEWS", f"Sync success. {len(events)} events loaded.")

    # --- decisions ---------------------------------------------------------
    def is_globally_blocked(self, now=None):
        """Only ONE genuinely global condition: a cache too stale to trust."""
        if not self.enabled:
            return False, None
        now = now or datetime.now(timezone.utc)
        age = self.store.age(now)
        if self.policy.is_stale(age):
            return True, (
                f"News calendar is stale ({self._age_text(now)}) and the feed is "
                f"unreachable -- trading halted until it refreshes.")
        return False, None

    def check_symbol(self, symbol: str, now=None):
        if not self.enabled:
            return False, None
        now = now or datetime.now(timezone.utc)
        halted, reason = self.is_globally_blocked(now)
        if halted:
            return True, reason
        event = self.policy.blocking_event(self.store.events(), symbol, now)
        if event is None:
            return False, None
        return True, self.policy.reason_for(event, now)

    # --- presentation (consumed by Session 2) ------------------------------
    def snapshot(self, now=None) -> dict:
        try:
            now = now or datetime.now(timezone.utc)
            age = self.store.age(now)
            upcoming = [e for e in self.store.events()
                        if e.importance == "HIGH" and e.when_utc >= now]
            nxt = upcoming[0] if upcoming else None
            symbols = list(self.policy._map.keys())
            return {
                "status": "stale" if self.policy.is_stale(age)
                          else ("degraded" if self.feed_degraded else "ok"),
                "cache_age_min": None if age is None else int(age.total_seconds() // 60),
                "sources": {getattr(self.source, "NAME", "forexfactory"):
                            "degraded" if self.feed_degraded else "ok"},
                "next": None if nxt is None else {
                    "in_min": int((nxt.when_utc - now).total_seconds() // 60),
                    "title": nxt.title, "currency": nxt.currency,
                    "importance": nxt.importance, "forecast": nxt.forecast,
                    "previous": nxt.previous,
                    "affects": [s for s in symbols
                                if nxt.currency in self.policy.currencies_for(s)],
                },
                "blocked_symbols": {
                    s: self.check_symbol(s, now)[1] for s in symbols
                    if self.check_symbol(s, now)[0]
                },
            }
        except Exception as exc:  # the GUI payload must never break on news
            self.logger.log_event("WARN", "NEWS", f"Snapshot failed: {exc}")
            return {"status": "unavailable"}

    def _age_text(self, now) -> str:
        age = self.store.age(now)
        return "never refreshed" if age is None else f"{int(age.total_seconds() // 60)}m old"
```

Replace `src/analysis/news/__init__.py` with:

```python
"""Economic-calendar sourcing, caching and blocking policy."""
from .manager import NewsManager

__all__ = ["NewsManager"]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_news_manager_failure_ladder -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/news/manager.py src/analysis/news/__init__.py \
        tests/unit/test_news_manager_failure_ladder.py
git commit -m "feat(news): NewsManager facade — outage keeps trading, stale cache fails closed"
```

---

### Task 7: Controller integration, config, and retiring the old module

**Files:**
- Modify: `src/core/system_controller.py:29` (import), `:124` (construction),
  `:937-947` (`_check_news_status`), `:398` (`_execute_signal` gate)
- Modify: `config/config.yaml` (new `news:` block), `.gitignore`
- Delete: `src/analysis/news_manager.py`, `tests/unit/test_news_manager_timezone.py`
- Test: `tests/unit/test_controller_news_gate.py`

**Interfaces:**
- Consumes: `NewsManager` from Task 6.
- Produces: `SystemController._news_blocks_symbol(symbol) -> tuple[bool, str | None]`,
  called at the top of `_execute_signal`.

The old `tests/unit/test_news_manager_timezone.py` is deleted because its behaviour is now
covered by `tests/unit/test_news_forexfactory_parse.py` (UTC parsing) and
`tests/unit/test_news_policy.py` (window arithmetic) against the new package.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_controller_news_gate.py`:

```python
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.manager import NewsManager
from src.analysis.news.models import CalendarEvent, make_key
from src.analysis.news.store import CalendarStore

RELEASE = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
CONFIG = {"news": {"symbol_currencies": {"EURUSD": ["EUR", "USD"], "GBPJPY": ["GBP", "JPY"]}}}


class _StubLogger:
    def log_event(self, *args, **kwargs):
        pass


def _manager_with_pce():
    store = CalendarStore(os.devnull)
    event = CalendarEvent(key=make_key("USD", "Core PCE", RELEASE), when_utc=RELEASE,
                          currency="USD", importance="HIGH", title="Core PCE")
    store.merge([event], "forexfactory", RELEASE)
    return NewsManager(_StubLogger(), config=CONFIG, source=None, store=store)


class PerSymbolGate(unittest.TestCase):
    """A USD release must stop USD-quoted symbols WITHOUT halting the whole bot."""

    def test_usd_release_blocks_eurusd(self):
        blocked, reason = _manager_with_pce().check_symbol("EURUSD", now=RELEASE)
        self.assertTrue(blocked)
        self.assertIn("Core PCE", reason)

    def test_same_release_leaves_gbpjpy_tradeable(self):
        blocked, _ = _manager_with_pce().check_symbol("GBPJPY", now=RELEASE)
        self.assertFalse(blocked)

    def test_bot_is_not_globally_halted_by_a_symbol_level_block(self):
        halted, _ = _manager_with_pce().is_globally_blocked(now=RELEASE)
        self.assertFalse(halted)


class ControllerWiring(unittest.TestCase):
    def test_execute_signal_consults_the_per_symbol_gate(self):
        """_execute_signal must call _news_blocks_symbol before sizing anything."""
        import inspect

        from src.core.system_controller import SystemController
        source = inspect.getsource(SystemController._execute_signal)
        self.assertIn("_news_blocks_symbol", source)

    def test_controller_exposes_the_gate_helper(self):
        from src.core.system_controller import SystemController
        self.assertTrue(hasattr(SystemController, "_news_blocks_symbol"))

    def test_controller_imports_the_new_package(self):
        """Note the trailing dot: the OLD module is 'src.analysis.news_manager',
        which would satisfy a bare startswith('src.analysis.news') and let this
        test pass before the change was made."""
        import src.core.system_controller as controller_module
        self.assertEqual(
            controller_module.NewsManager.__module__, "src.analysis.news.manager")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_controller_news_gate -v`
Expected: FAIL — `AssertionError: False is not true` on `_news_blocks_symbol`, and the
import assertion fails because `NewsManager.__module__` is still `src.analysis.news_manager`.

- [ ] **Step 3: Write the minimal implementation**

Change the import at `src/core/system_controller.py:29`:

```python
from src.analysis.news import NewsManager
```

Change the construction at `src/core/system_controller.py:124` to pass config:

```python
        self.news_manager = NewsManager(self.logger, self.config)
```

Replace `_check_news_status` (currently `:937-947`) with:

```python
    async def _check_news_status(self):
        """Global pause is reserved for the ONE genuinely global condition: a
        calendar too stale to trust. Ordinary red-folder blackouts are applied
        per symbol in _execute_signal, so a BOE release cannot halt US100."""
        await self.news_manager.update_calendar()
        blocked, reason = self.news_manager.is_globally_blocked()
        if blocked and self.state == BotState.ACTIVE:
            self.state = BotState.PAUSED
            self._publish(SystemStateChanged(state="PAUSED"))
            await self.telemetry.send_message(
                f"🛑 **NEWS DATA STALE**: {reason}", parse_mode="Markdown")
        elif not blocked and self.state == BotState.PAUSED and not self.is_manual_pause:
            self.state = BotState.ACTIVE
            self._publish(SystemStateChanged(state="ACTIVE"))
            await self.telemetry.send_message(
                "✅ News calendar refreshed. Resuming.", parse_mode="Markdown")
```

Add this helper immediately above `_execute_signal` (currently `:398`):

```python
    def _news_blocks_symbol(self, symbol):
        """Per-symbol red-folder gate. Never raises: a news fault must not
        crash the trade path, so an internal error degrades to 'not blocked'
        while the global stale-cache guard remains in force."""
        try:
            return self.news_manager.check_symbol(symbol)
        except Exception as exc:
            self.logger.log_event("WARN", "NEWS", f"Symbol gate failed for {symbol}: {exc}")
            return False, None
```

Insert as the first statements inside `_execute_signal`, before the `normalize_price` calls:

```python
        news_blocked, news_reason = self._news_blocks_symbol(symbol)
        if news_blocked:
            self.logger.log_event("INFO", "NEWS", f"{symbol} signal skipped: {news_reason}")
            return
```

Add this block to `config/config.yaml` at the top level (after the `ops:` block):

```yaml
# Economic calendar. ForexFactory is the PRIMARY source; MT5 is a fallback
# added in a later session. Only High ("red folder") events halt trading, and
# only for symbols exposed to the event's currency.
news:
  enabled: true
  refresh_interval_min: 60
  window_pre_min: 60
  window_post_min: 30
  max_cache_age_hours: 48
  cache_path: "data/news/calendar.json"
  symbol_currencies:
    EURUSD: [EUR, USD]
    GBPUSD: [GBP, USD]
    USDJPY: [USD, JPY]
    AUDUSD: [AUD, USD]
    USDCAD: [USD, CAD]
    GBPJPY: [GBP, JPY]
    XAUUSD: [USD]
    US30:   [USD]
    US100:  [USD]
    BTCUSD: [USD]
    ETHUSD: [USD]
    XTIUSD: [USD]
```

Add to `.gitignore` after the `data/results/**` line:

```
data/news/
```

Delete the superseded module and its test:

```bash
git rm src/analysis/news_manager.py tests/unit/test_news_manager_timezone.py
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_controller_news_gate -v`
Expected: PASS (6 tests)

Then confirm nothing still imports the deleted module:

Run: `grep -rn "analysis.news_manager" --include=*.py src/ tests/ scripts/`
Expected: no output.

- [ ] **Step 5: Run the whole suite, detached**

```bash
L=/tmp/news_suite.log
setsid nohup bash -c ".venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' \
  > $L 2>&1; echo \"EXIT=\$?\" >> $L" < /dev/null > /dev/null 2>&1 &
# then poll until EXIT= appears; expect "OK" and no failures
until grep -q '^EXIT=' $L; do sleep 15; done; grep -E '^(Ran|OK|FAILED|EXIT=)' $L
```

Expected: `OK`, `EXIT=0`. Baseline before this session was 687 tests. This plan adds 67
(4 + 8 + 5 + 14 + 21 + 9 + 6) and deletes 4, so expect **750**. A count materially below
that means a module failed to collect — investigate before proceeding. Do not proceed on a
red suite.

- [ ] **Step 6: Commit**

```bash
git add -A src/analysis src/core/system_controller.py config/config.yaml .gitignore tests/unit
git commit -m "feat(news): per-symbol red-folder gate; retire monolithic news_manager

Global PAUSE now fires only for a stale calendar. Ordinary blackouts apply per
symbol in _execute_signal, so a BOE release stops GBPUSD/GBPJPY while US100
keeps trading. A feed outage with a fresh cache no longer halts the book."
```

---

## Self-Review

**Spec coverage.** §2.1 `CalendarEvent` → Task 1. §2.2 ForexFactory source → Tasks 2–3.
§2.3 `CalendarStore` → Task 4. §2.4 failure ladder → Task 6. §2.5 `NewsPolicy` → Task 5.
§3 config + §3.1 GBPJPY case → Tasks 5 and 7. §4 controller integration → Task 7.
§7 testing → every task. §5 dashboard and §6 digest are **deliberately out of scope** —
they are Session 2; Task 6 ships `snapshot()` as the seam Session 2 consumes. MT5
(§2.2 fallback) is Session 3.

**Type consistency.** `CalendarEvent` field names are identical across Tasks 1, 2, 4, 6.
`NewsPolicy.blocking_event` returns an event-or-`None` in Task 5 and is consumed that way in
Task 6. `NewsFetchError` is defined in Task 3 and imported in Task 6's test.
`store.age()` returns `timedelta | None` in Task 4 and `policy.is_stale()` accepts exactly
that in Task 5. `NAME` exists on the source in Tasks 2–3 and is read in Task 6.

**Known wart.** `snapshot()` in Task 6 reads `self.policy._map`, a private attribute, to
enumerate configured symbols. Acceptable within one package; if Session 2 needs it more
widely, promote it to a `policy.mapped_symbols()` accessor then rather than speculatively now.
