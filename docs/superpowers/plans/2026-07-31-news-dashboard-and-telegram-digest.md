# News on the Dashboard + Telegram Digest — Implementation Plan (Session 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the news subsystem visible — a degrading `news` block in the GUI snapshot, a
compact panel on the Overview page, per-symbol block badges on Positions, and a summarised
Telegram digest — so the operator can see what is coming and why a symbol is being held.

**Architecture:** Session 1 already built and tested `NewsManager.snapshot()` as the seam.
This session adds a defensive `_news_block` to `state_view.py` (exactly like the existing
`_dollar_block`), a pure digest renderer in `telegram_format.py`, one scheduling hook in the
controller mirroring the existing 23:45 performance report, and a `NewsPanel` React component
modelled on `DollarBias`. No change to blocking behaviour.

**Tech Stack:** Python 3.12 + stdlib `unittest` (backend); React 18 + TypeScript + Tailwind +
vitest (frontend). No new dependencies.

## Global Constraints

- Python: run with `.venv/bin/python`. Tests are stdlib `unittest` under `tests/unit/`,
  named `test_*.py`. **There is no pytest.**
- Frontend: `cd frontend && npm test` (vitest). Component tests live beside the component as
  `X.test.tsx`.
- The full Python suite takes 9–30 min depending on machine load. Run **single modules**
  during development. The controller runs it once at the end.
- **This session must not change blocking behaviour.** `NewsPolicy`, `CalendarStore`,
  `check_symbol`, `is_globally_blocked` and `_execute_signal` are read-only for this work.
  If a task seems to need a change there, stop and report BLOCKED.
- The `news` snapshot block must **never** raise into the GUI payload; it degrades to
  `{"status": "unavailable"}` — same contract as `_dollar_block`.
- Telegram sends must never raise into the trading loop.
- MT5 is out of scope (Session 3). `actual` values will normally be absent; render
  forecast/previous, which ForexFactory supplies.
- No new dependencies, layers, or frameworks.
- Work on a feature branch off `main`.

### ⚠️ Plan-code caveat — read this before transcribing anything

Session 1's plan embedded complete implementation code, and **every one of its six fix rounds
closed a defect that came from those code samples**, not from the implementers. Three were
total-function violations (a constructor that accepted naive datetimes, a `load()` that
crashed on wrong-shaped JSON, parse bugs relabelled as feed outages); three were tests that
could not fail. None turned a test red.

So: the code below is a **starting point, not gospel**. Before transcribing any block, check
it against the invariants stated in its task. If the sample contradicts an invariant, the
invariant wins — implement correctly and say so in your report. Specifically, for every
function you write here, ask: *can this raise? can it silently swallow? would my test fail if
the behaviour broke?*

## File Structure

| Path | Responsibility |
|---|---|
| `src/analysis/news/manager.py` | **modify** — add `digest(now)` returning plain data |
| `src/ops/web/state_view.py` | **modify** — add `_news_block` + `"news"` key |
| `src/ops/telegram_format.py` | **modify** — pure digest/alert renderers |
| `src/core/system_controller.py` | **modify** — one daily-digest hook + T-15m alerts |
| `config/config.yaml` | **modify** — `news.digest` settings |
| `tests/unit/test_gui_news.py` | new — snapshot block |
| `tests/unit/test_news_digest.py` | new — `digest()` + renderers |
| `tests/unit/test_controller_news_digest.py` | new — scheduling |
| `frontend/src/lib/types.ts` | **modify** — `NewsBlock` type |
| `frontend/src/components/market/NewsPanel.tsx` + `.test.tsx` | new — the panel |
| `frontend/src/sections/OverviewPage.tsx` | **modify** — mount the panel |
| `frontend/src/components/PositionsTable.tsx` | **modify** — blocked badge |

---

### Task 1: `NewsManager.digest()` — plain data for rendering

**Files:**
- Modify: `src/analysis/news/manager.py`
- Test: `tests/unit/test_news_digest.py`

**Interfaces:**
- Consumes: `CalendarStore.events()`, `NewsPolicy` (`mapped_symbols`, `currencies_for`).
- Produces: `NewsManager.digest(now=None) -> dict` shaped:
  ```python
  {"date": "2026-07-30",            # ISO date, UTC
   "count": 2,
   "events": [{"when_utc": "2026-07-30T12:30:00+00:00",
               "currency": "USD", "title": "Core PCE Price Index m/m",
               "forecast": "0.3%", "previous": "0.2%",
               "affects": ["EURUSD", "XAUUSD"]}]}
  ```

**Invariants (these win over the sample code):**
- Only `importance == "HIGH"` events appear. Medium/low never do.
- Only events falling on the SAME UTC calendar date as `now`.
- Events sorted by `when_utc` ascending.
- `affects` lists only symbols configured in `news.symbol_currencies` that are exposed to the
  event's currency; it may be empty and that is fine.
- `digest()` must never raise — on any internal error return
  `{"date": ..., "count": 0, "events": [], "status": "unavailable"}`.
- Pure with respect to the clock: `now` is injectable.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_news_digest.py`:

```python
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.manager import NewsManager
from src.analysis.news.models import CalendarEvent, make_key
from src.analysis.news.store import CalendarStore

DAY = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
CONFIG = {"news": {"symbol_currencies": {
    "EURUSD": ["EUR", "USD"], "GBPJPY": ["GBP", "JPY"], "XAUUSD": ["USD"]}}}


class _StubLogger:
    def log_event(self, *args, **kwargs):
        pass


def _event(title, currency="USD", importance="HIGH", when=DAY,
           forecast=None, previous=None):
    return CalendarEvent(key=make_key(currency, title, when), when_utc=when,
                         currency=currency, importance=importance, title=title,
                         forecast=forecast, previous=previous)


def _manager(events):
    store = CalendarStore(os.devnull)
    store.merge(events, "forexfactory", DAY)
    return NewsManager(_StubLogger(), config=CONFIG, source=object(), store=store)


class DigestContents(unittest.TestCase):
    def test_lists_todays_high_impact_events(self):
        d = _manager([_event("Core PCE", forecast="0.3%", previous="0.2%")]).digest(now=DAY)
        self.assertEqual(d["count"], 1)
        self.assertEqual(d["events"][0]["title"], "Core PCE")
        self.assertEqual(d["events"][0]["forecast"], "0.3%")
        self.assertEqual(d["events"][0]["previous"], "0.2%")

    def test_excludes_medium_and_low(self):
        d = _manager([_event("ifo", importance="MEDIUM"),
                      _event("M3", importance="LOW")]).digest(now=DAY)
        self.assertEqual(d["count"], 0)

    def test_excludes_other_days(self):
        d = _manager([_event("Tomorrow", when=DAY + timedelta(days=1))]).digest(now=DAY)
        self.assertEqual(d["count"], 0)

    def test_events_are_sorted_by_time(self):
        d = _manager([_event("Later", when=DAY + timedelta(hours=3)),
                      _event("Earlier", when=DAY - timedelta(hours=3))]).digest(now=DAY)
        self.assertEqual([e["title"] for e in d["events"]], ["Earlier", "Later"])

    def test_affects_lists_only_exposed_symbols(self):
        d = _manager([_event("Core PCE")]).digest(now=DAY)
        self.assertEqual(sorted(d["events"][0]["affects"]), ["EURUSD", "XAUUSD"])

    def test_gbp_event_affects_gbpjpy_only(self):
        d = _manager([_event("BOE Rate", currency="GBP")]).digest(now=DAY)
        self.assertEqual(d["events"][0]["affects"], ["GBPJPY"])

    def test_empty_day_is_a_valid_digest(self):
        d = _manager([]).digest(now=DAY)
        self.assertEqual(d["count"], 0)
        self.assertEqual(d["events"], [])
        self.assertEqual(d["date"], "2026-07-30")


class DigestNeverRaises(unittest.TestCase):
    def test_internal_error_degrades_to_unavailable(self):
        manager = _manager([_event("Core PCE")])

        def boom():
            raise RuntimeError("store exploded")

        manager.store.events = boom
        d = manager.digest(now=DAY)
        self.assertEqual(d["status"], "unavailable")
        self.assertEqual(d["events"], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_news_digest -v`
Expected: FAIL — `AttributeError: 'NewsManager' object has no attribute 'digest'`

- [ ] **Step 3: Implement**

Add to `NewsManager` in `src/analysis/news/manager.py`:

```python
    def digest(self, now=None) -> dict:
        """Today's red-folder events as plain data, for Telegram and the GUI.
        Never raises -- a rendering aid must not be able to break a caller."""
        now = now or datetime.now(timezone.utc)
        try:
            day = now.date()
            symbols = self.policy.mapped_symbols()
            events = []
            for event in self.store.events():
                if event.importance != "HIGH" or event.when_utc.date() != day:
                    continue
                events.append({
                    "when_utc": event.when_utc.isoformat(),
                    "currency": event.currency,
                    "title": event.title,
                    "forecast": event.forecast,
                    "previous": event.previous,
                    "affects": [s for s in symbols
                                if event.currency in self.policy.currencies_for(s)],
                })
            return {"date": day.isoformat(), "count": len(events), "events": events}
        except Exception as exc:
            self.logger.log_event("WARN", "NEWS", f"Digest failed: {exc}")
            return {"date": now.date().isoformat(), "count": 0, "events": [],
                    "status": "unavailable"}
```

`store.events()` is already sorted by `when_utc`, so no re-sort is needed — confirm that is
still true before relying on it.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_news_digest -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/news/manager.py tests/unit/test_news_digest.py
git commit -m "feat(news): NewsManager.digest() — today's red-folder events as plain data"
```

---

### Task 2: `news` block in the GUI snapshot

**Files:**
- Modify: `src/ops/web/state_view.py`
- Test: `tests/unit/test_gui_news.py`

**Interfaces:**
- Consumes: `NewsManager.snapshot()` (built in Session 1).
- Produces: `_news_block(controller) -> dict`, wired as `"news": _news_block(controller)` in
  `build_snapshot`.

**Invariants:**
- Mirrors `_dollar_block` exactly in spirit: **never raises**, degrades to
  `{"status": "unavailable"}`.
- Degrades when: the controller has no `news_manager`, `snapshot()` raises, or `snapshot()`
  returns a non-dict.
- Adds no computation of its own — the manager owns the shape.

Read `_dollar_block` in the same file first and match its defensive style.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_gui_news.py`:

```python
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.ops.web.state_view import _news_block


class _Manager:
    def __init__(self, payload=None, raises=False):
        self.payload = payload
        self.raises = raises

    def snapshot(self, now=None):
        if self.raises:
            raise RuntimeError("news exploded")
        return self.payload


class _Controller:
    def __init__(self, manager=None):
        if manager is not None:
            self.news_manager = manager


class NewsBlockDegrades(unittest.TestCase):
    def test_missing_news_manager_is_unavailable(self):
        self.assertEqual(_news_block(_Controller()), {"status": "unavailable"})

    def test_snapshot_raising_is_unavailable(self):
        self.assertEqual(_news_block(_Controller(_Manager(raises=True))),
                         {"status": "unavailable"})

    def test_non_dict_snapshot_is_unavailable(self):
        self.assertEqual(_news_block(_Controller(_Manager(payload=["nope"]))),
                         {"status": "unavailable"})

    def test_none_snapshot_is_unavailable(self):
        self.assertEqual(_news_block(_Controller(_Manager(payload=None))),
                         {"status": "unavailable"})


class NewsBlockPassesThrough(unittest.TestCase):
    def test_valid_snapshot_is_returned_verbatim(self):
        payload = {"status": "ok", "cache_age_min": 12,
                   "next": {"title": "Core CPI m/m", "in_min": 47},
                   "blocked_symbols": {"GBPJPY": "BOE in 22m"}}
        self.assertEqual(_news_block(_Controller(_Manager(payload))), payload)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_news -v`
Expected: FAIL — `ImportError: cannot import name '_news_block'`

- [ ] **Step 3: Implement**

In `src/ops/web/state_view.py`, add `"news": _news_block(controller),` to the dict returned by
`build_snapshot`, and add:

```python
def _news_block(controller) -> dict:
    """Economic-calendar snapshot for the GUI. Defensive by the same rule as
    _dollar_block: a news fault must never break the whole payload, so any
    problem degrades to "unavailable" rather than propagating."""
    try:
        manager = getattr(controller, "news_manager", None)
        if manager is None:
            return {"status": "unavailable"}
        data = manager.snapshot()
        if not isinstance(data, dict):
            return {"status": "unavailable"}
        return data
    except Exception:
        return {"status": "unavailable"}
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_gui_news tests.unit.test_gui_state_view -v`
Expected: PASS — 5 new tests plus the existing state_view module still green.

- [ ] **Step 5: Commit**

```bash
git add src/ops/web/state_view.py tests/unit/test_gui_news.py
git commit -m "feat(gui): additive, degrading news block in the state snapshot"
```

---

### Task 3: Telegram digest + alert renderers (pure)

**Files:**
- Modify: `src/ops/telegram_format.py`
- Test: `tests/unit/test_news_digest.py` (append a new class)

**Interfaces:**
- Consumes: the dict from `NewsManager.digest()` (Task 1).
- Produces: `format_news_digest(digest: dict, tz_offset_h: float = 3.0) -> str` and
  `format_news_alert(event: dict, tz_offset_h: float = 3.0) -> str`.

**Invariants:**
- Pure: no I/O, no clock. Input dict in, string out.
- An empty day renders **one explicit line saying so** — silence is indistinguishable from a
  broken job.
- Events are grouped by currency, in the order they occur.
- Times render in the operator's local offset (default +3, Africa/Kampala) with the UTC time
  alongside, because every log and the feed itself are UTC and mixing them silently is the
  bug class this whole workstream exists to kill.
- Never raises on a malformed digest — render what is present.

Read the existing helpers in `src/ops/telegram_format.py` first and match their style and
escaping conventions.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_news_digest.py`:

```python
from src.ops.telegram_format import format_news_alert, format_news_digest

_DIGEST = {
    "date": "2026-07-30", "count": 2,
    "events": [
        {"when_utc": "2026-07-30T12:30:00+00:00", "currency": "USD",
         "title": "Core PCE Price Index m/m", "forecast": "0.3%",
         "previous": "0.2%", "affects": ["EURUSD", "XAUUSD"]},
        {"when_utc": "2026-07-30T18:00:00+00:00", "currency": "GBP",
         "title": "BOE Official Bank Rate", "forecast": "4.00%",
         "previous": "4.25%", "affects": ["GBPJPY"]},
    ],
}


class DigestRendering(unittest.TestCase):
    def test_includes_every_event_title(self):
        text = format_news_digest(_DIGEST)
        self.assertIn("Core PCE Price Index m/m", text)
        self.assertIn("BOE Official Bank Rate", text)

    def test_shows_local_and_utc_times(self):
        text = format_news_digest(_DIGEST)
        self.assertIn("15:30", text)   # 12:30Z at +3
        self.assertIn("12:30Z", text)

    def test_groups_by_currency(self):
        text = format_news_digest(_DIGEST)
        self.assertIn("USD", text)
        self.assertIn("GBP", text)

    def test_shows_forecast_and_previous(self):
        text = format_news_digest(_DIGEST)
        self.assertIn("0.3%", text)
        self.assertIn("0.2%", text)

    def test_names_affected_pairs(self):
        self.assertIn("GBPJPY", format_news_digest(_DIGEST))

    def test_empty_day_says_so_explicitly(self):
        text = format_news_digest({"date": "2026-07-30", "count": 0, "events": []})
        self.assertTrue(text.strip())
        self.assertIn("No high-impact", text)

    def test_malformed_digest_does_not_raise(self):
        self.assertIsInstance(format_news_digest({}), str)
        self.assertIsInstance(format_news_digest({"events": [{}]}), str)


class AlertRendering(unittest.TestCase):
    def test_alert_names_event_currency_and_pairs(self):
        text = format_news_alert(_DIGEST["events"][0])
        self.assertIn("Core PCE Price Index m/m", text)
        self.assertIn("USD", text)
        self.assertIn("EURUSD", text)

    def test_alert_shows_forecast_and_previous(self):
        text = format_news_alert(_DIGEST["events"][0])
        self.assertIn("0.3%", text)
        self.assertIn("0.2%", text)

    def test_alert_on_malformed_event_does_not_raise(self):
        self.assertIsInstance(format_news_alert({}), str)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_news_digest -v`
Expected: FAIL — `ImportError: cannot import name 'format_news_digest'`

- [ ] **Step 3: Implement**

Add to `src/ops/telegram_format.py`:

```python
from datetime import datetime, timedelta, timezone


def _local(iso_utc: str, tz_offset_h: float):
    """(local_hhmm, utc_hhmm) or (None, None) if unparseable."""
    try:
        when = datetime.fromisoformat(iso_utc)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        local = when.astimezone(timezone(timedelta(hours=tz_offset_h)))
        return local.strftime("%H:%M"), when.astimezone(timezone.utc).strftime("%H:%MZ")
    except Exception:
        return None, None


def format_news_digest(digest: dict, tz_offset_h: float = 3.0) -> str:
    """Today's red-folder events, grouped by currency. Never raises."""
    try:
        events = list((digest or {}).get("events") or [])
        date = (digest or {}).get("date", "today")
        if not events:
            return f"📅 <b>News {date}</b>\nNo high-impact events scheduled."
        lines = [f"📅 <b>News {date}</b> — {len(events)} high-impact"]
        by_currency: dict = {}
        for event in events:
            by_currency.setdefault(event.get("currency", "?"), []).append(event)
        for currency, group in by_currency.items():
            lines.append(f"\n<b>{currency}</b>")
            for event in group:
                local, utc = _local(event.get("when_utc", ""), tz_offset_h)
                stamp = f"{local} ({utc})" if local else "time unknown"
                lines.append(f"  • {stamp} — {event.get('title', 'untitled')}")
                fc, pv = event.get("forecast"), event.get("previous")
                if fc or pv:
                    lines.append(f"    forecast {fc or '—'} · previous {pv or '—'}")
                affects = event.get("affects") or []
                if affects:
                    lines.append(f"    affects: {', '.join(affects)}")
        return "\n".join(lines)
    except Exception:
        return "📅 News digest unavailable."


def format_news_alert(event: dict, tz_offset_h: float = 3.0) -> str:
    """One-line heads-up before a red-folder release. Never raises."""
    try:
        event = event or {}
        local, utc = _local(event.get("when_utc", ""), tz_offset_h)
        stamp = f"{local} ({utc})" if local else "shortly"
        parts = [f"⚠️ <b>{event.get('currency', '?')} {event.get('title', 'event')}</b> at {stamp}"]
        fc, pv = event.get("forecast"), event.get("previous")
        if fc or pv:
            parts.append(f"forecast {fc or '—'} · previous {pv or '—'}")
        affects = event.get("affects") or []
        if affects:
            parts.append(f"holding: {', '.join(affects)}")
        return "\n".join(parts)
    except Exception:
        return "⚠️ News alert unavailable."
```

Check the existing file's import block before adding a duplicate `datetime` import.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m unittest tests.unit.test_news_digest -v`
Expected: PASS (18 tests total in the module)

- [ ] **Step 5: Commit**

```bash
git add src/ops/telegram_format.py tests/unit/test_news_digest.py
git commit -m "feat(news): pure Telegram renderers for the daily digest and pre-event alert"
```

---

### Task 4: Controller scheduling — daily digest + pre-event alert

**Files:**
- Modify: `src/core/system_controller.py`, `config/config.yaml`
- Test: `tests/unit/test_controller_news_digest.py`

**Interfaces:**
- Consumes: `NewsManager.digest`, `format_news_digest`, `format_news_alert`.
- Produces: `SystemController._maybe_send_news_digest(now_local)` and
  `SystemController._maybe_send_news_alerts(now_utc)`, both awaited from the main loop.

**Invariants:**
- Mirror the EXISTING daily-report pattern in the loop (`now_uganda.hour == 23 and
  now_uganda.minute == 45` guarded by `self.report_sent_today`, reset at `hour == 0`). Read
  it before writing anything and follow it exactly.
- The digest fires once per day. The reset must be independent of the performance-report flag.
- A pre-event alert fires **once per event**, tracked by the event's `when_utc`+title, and the
  set is pruned so it cannot grow forever.
- **Neither may raise into the loop.** The loop's `except Exception` re-raises — wrap both.
- Sending must be skipped entirely when `news.digest.enabled` is false.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_controller_news_digest.py`:

```python
import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.core.system_controller import SystemController


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Telemetry:
    def __init__(self):
        self.sent = []

    async def send_message(self, text, parse_mode="HTML"):
        self.sent.append(text)


class _News:
    def __init__(self, digest=None, raises=False):
        self._digest = digest or {"date": "2026-07-30", "count": 0, "events": []}
        self.raises = raises

    def digest(self, now=None):
        if self.raises:
            raise RuntimeError("digest exploded")
        return self._digest


class _Logger:
    def log_event(self, *a, **k):
        pass


def _controller(news=None, enabled=True):
    c = object.__new__(SystemController)
    c.telemetry = _Telemetry()
    c.news_manager = news or _News()
    c.logger = _Logger()
    c.config = {"news": {"digest": {"enabled": enabled, "hour": 7, "minute": 0,
                                    "alert_lead_min": 15}}}
    c.news_digest_sent_today = False
    c.news_alerts_sent = set()
    return c


AT_7 = datetime(2026, 7, 30, 7, 0)
AT_8 = datetime(2026, 7, 30, 8, 0)


class DailyDigest(unittest.TestCase):
    def test_sends_at_the_configured_time(self):
        c = _controller()
        _run(c._maybe_send_news_digest(AT_7))
        self.assertEqual(len(c.telemetry.sent), 1)

    def test_does_not_send_twice_in_one_day(self):
        c = _controller()
        _run(c._maybe_send_news_digest(AT_7))
        _run(c._maybe_send_news_digest(AT_7))
        self.assertEqual(len(c.telemetry.sent), 1)

    def test_does_not_send_at_other_times(self):
        c = _controller()
        _run(c._maybe_send_news_digest(AT_8))
        self.assertEqual(c.telemetry.sent, [])

    def test_empty_day_still_sends_a_message(self):
        """Silence is indistinguishable from a broken job."""
        c = _controller()
        _run(c._maybe_send_news_digest(AT_7))
        self.assertIn("No high-impact", c.telemetry.sent[0])

    def test_disabled_sends_nothing(self):
        c = _controller(enabled=False)
        _run(c._maybe_send_news_digest(AT_7))
        self.assertEqual(c.telemetry.sent, [])

    def test_digest_failure_does_not_raise_into_the_loop(self):
        c = _controller(news=_News(raises=True))
        _run(c._maybe_send_news_digest(AT_7))   # must not raise
        self.assertEqual(c.telemetry.sent, [])


RELEASE = datetime(2026, 7, 30, 12, 30, tzinfo=timezone.utc)
EVENT = {"when_utc": RELEASE.isoformat(), "currency": "USD", "title": "Core PCE",
         "forecast": "0.3%", "previous": "0.2%", "affects": ["EURUSD"]}


class PreEventAlert(unittest.TestCase):
    def _c(self):
        return _controller(news=_News({"date": "2026-07-30", "count": 1,
                                       "events": [EVENT]}))

    def test_alerts_inside_the_lead_window(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        self.assertEqual(len(c.telemetry.sent), 1)
        self.assertIn("Core PCE", c.telemetry.sent[0])

    def test_does_not_alert_before_the_lead_window(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=45)))
        self.assertEqual(c.telemetry.sent, [])

    def test_does_not_alert_after_the_release(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE + timedelta(minutes=5)))
        self.assertEqual(c.telemetry.sent, [])

    def test_alerts_only_once_per_event(self):
        c = self._c()
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=9)))
        self.assertEqual(len(c.telemetry.sent), 1)

    def test_alert_failure_does_not_raise_into_the_loop(self):
        c = _controller(news=_News(raises=True))
        _run(c._maybe_send_news_alerts(RELEASE - timedelta(minutes=10)))
        self.assertEqual(c.telemetry.sent, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m unittest tests.unit.test_controller_news_digest -v`
Expected: FAIL — `AttributeError: 'SystemController' object has no attribute
'_maybe_send_news_digest'`

- [ ] **Step 3: Implement**

In `SystemController.__init__`, beside `self.report_sent_today = False`, add:

```python
        self.news_digest_sent_today = False
        self.news_alerts_sent = set()
```

Add these methods (place them next to `_check_news_status`):

```python
    def _news_digest_cfg(self):
        return ((self.config.get("news", {}) or {}).get("digest", {}) or {})

    async def _maybe_send_news_digest(self, now_local):
        """Once-a-day red-folder summary. Mirrors the 23:45 performance report;
        never raises -- the main loop's handler re-raises."""
        cfg = self._news_digest_cfg()
        if not cfg.get("enabled", True):
            return
        if now_local.hour != int(cfg.get("hour", 7)):
            return
        if now_local.minute != int(cfg.get("minute", 0)):
            return
        if self.news_digest_sent_today:
            return
        try:
            from src.ops.telegram_format import format_news_digest
            digest = self.news_manager.digest()
            await self.telemetry.send_message(format_news_digest(digest), parse_mode="HTML")
            self.news_digest_sent_today = True
        except Exception as exc:
            self.logger.log_event("WARN", "NEWS", f"Digest send failed: {exc}")

    async def _maybe_send_news_alerts(self, now_utc):
        """One heads-up per red-folder event, `alert_lead_min` before it."""
        cfg = self._news_digest_cfg()
        if not cfg.get("enabled", True):
            return
        lead = timedelta(minutes=int(cfg.get("alert_lead_min", 15)))
        try:
            from src.ops.telegram_format import format_news_alert
            for event in (self.news_manager.digest().get("events") or []):
                when = datetime.fromisoformat(event["when_utc"])
                delta = when - now_utc
                if not (timedelta(0) < delta <= lead):
                    continue
                marker = f"{event['when_utc']}|{event.get('title', '')}"
                if marker in self.news_alerts_sent:
                    continue
                await self.telemetry.send_message(format_news_alert(event), parse_mode="HTML")
                self.news_alerts_sent.add(marker)
        except Exception as exc:
            self.logger.log_event("WARN", "NEWS", f"News alert failed: {exc}")
```

Wire both into the main loop next to the existing Uganda reporting block, and reset the
daily flag and prune the alert set alongside `self.report_sent_today = False`:

```python
                await self._maybe_send_news_digest(now_uganda)
                await self._maybe_send_news_alerts(datetime.now(timezone.utc))

                if now_uganda.hour == 0:
                    self.news_digest_sent_today = False
                    self.news_alerts_sent.clear()
```

Confirm `timezone` and `timedelta` are imported in that module; add them if not.

Add to the `news:` block in `config/config.yaml`:

```yaml
  # Telegram summary. The digest fires once a day in local (Africa/Kampala) time;
  # alerts fire `alert_lead_min` before each red-folder release.
  digest:
    enabled: true
    hour: 7
    minute: 0
    alert_lead_min: 15
```

- [ ] **Step 4: Run to verify it passes**

Run:
```
.venv/bin/python -m unittest tests.unit.test_controller_news_digest -v
.venv/bin/python -m unittest tests.unit.test_controller_news_gate tests.unit.test_controller_routing tests.unit.test_risk_manager_exposure_cap
```
Expected: 11 new tests pass; the controller regression modules stay green.

- [ ] **Step 5: Commit**

```bash
git add src/core/system_controller.py config/config.yaml tests/unit/test_controller_news_digest.py
git commit -m "feat(news): daily Telegram digest + per-event pre-release alert"
```

---

### Task 5: `NewsPanel` React component

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Create: `frontend/src/components/market/NewsPanel.tsx`, `NewsPanel.test.tsx`

**Interfaces:**
- Consumes: `Snapshot["news"]`.
- Produces: `export function NewsPanel({ data, className }: { data?: NewsBlock; className?: string })`

**Invariants:**
- Renders an explicit unavailable state when `data` is undefined or
  `data.status === "unavailable"` — modelled on `DollarBias`'s empty state. Read that
  component first and match its structure and Tailwind token usage.
- Never crashes on a partial payload: `next` may be null, `blocked_symbols` may be empty.
- Shows a `stale` treatment when `status === "stale"` and a degraded hint when
  `status === "degraded"`.
- Uses semantic tokens (`text-warning`, `text-muted-foreground`, `bg-surface-1/2`), never raw
  colours, and never profit/loss tones — this is not P&L.

Add to `frontend/src/lib/types.ts`:

```ts
export interface NewsEventSummary {
  in_min: number; title: string; currency: string; importance: string;
  forecast?: string | null; previous?: string | null; affects: string[];
}
export interface NewsBlock {
  status: "ok" | "degraded" | "stale" | "unavailable";
  cache_age_min?: number | null;
  sources?: Record<string, string>;
  next?: NewsEventSummary | null;
  blocked_symbols?: Record<string, string>;
}
```
and add `news?: NewsBlock;` to `Snapshot`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/market/NewsPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NewsPanel } from "./NewsPanel";
import type { NewsBlock } from "@/lib/types";

const OK: NewsBlock = {
  status: "ok",
  cache_age_min: 12,
  next: { in_min: 47, title: "Core CPI m/m", currency: "USD", importance: "HIGH",
          forecast: "0.3%", previous: "0.2%", affects: ["EURUSD", "XAUUSD"] },
  blocked_symbols: { GBPJPY: "GBP BOE Rate Decision in 22m" },
};

describe("NewsPanel", () => {
  it("shows an explicit unavailable state with no data", () => {
    render(<NewsPanel />);
    expect(screen.getByTestId("news-panel-empty")).toBeInTheDocument();
  });

  it("shows unavailable when the backend degraded", () => {
    render(<NewsPanel data={{ status: "unavailable" }} />);
    expect(screen.getByTestId("news-panel-empty")).toBeInTheDocument();
  });

  it("renders the next event title and countdown", () => {
    render(<NewsPanel data={OK} />);
    expect(screen.getByText(/Core CPI m\/m/)).toBeInTheDocument();
    expect(screen.getByText(/47m/)).toBeInTheDocument();
  });

  it("lists the affected pairs", () => {
    render(<NewsPanel data={OK} />);
    expect(screen.getByText("EURUSD")).toBeInTheDocument();
    expect(screen.getByText("XAUUSD")).toBeInTheDocument();
  });

  it("names blocked symbols with their reason", () => {
    render(<NewsPanel data={OK} />);
    expect(screen.getByText(/GBPJPY/)).toBeInTheDocument();
    expect(screen.getByText(/BOE Rate Decision/)).toBeInTheDocument();
  });

  it("renders with no next event and no blocks", () => {
    render(<NewsPanel data={{ status: "ok", next: null, blocked_symbols: {} }} />);
    expect(screen.getByTestId("news-panel")).toBeInTheDocument();
  });

  it("marks a stale calendar", () => {
    render(<NewsPanel data={{ status: "stale", cache_age_min: 3000 }} />);
    expect(screen.getByTestId("news-panel-stale")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/market/NewsPanel.test.tsx`
Expected: FAIL — cannot resolve `./NewsPanel`

- [ ] **Step 3: Implement**

Write `frontend/src/components/market/NewsPanel.tsx` following `DollarBias.tsx`'s structure:
a bordered `bg-surface-1` container with a header (calendar icon + "Economic Calendar"), an
unavailable branch returning a `news-panel-empty` testid, a `news-panel-stale` marker when
`status === "stale"`, the next event as title + `{in_min}m` countdown + forecast/previous, the
`affects` array as small chips, and `blocked_symbols` as rows of `symbol — reason`. Root
element carries `data-testid="news-panel"`.

Keep it under ~120 lines. Do not add charts or animation.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/market/NewsPanel.test.tsx`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/market/NewsPanel.tsx frontend/src/components/market/NewsPanel.test.tsx frontend/src/lib/types.ts
git commit -m "feat(gui): NewsPanel component with unavailable/stale states"
```

---

### Task 6: Mount the panel and badge blocked positions

**Files:**
- Modify: `frontend/src/sections/OverviewPage.tsx`, `frontend/src/sections/OverviewPage.test.tsx`
- Modify: `frontend/src/components/PositionsTable.tsx`, `PositionsTable.test.tsx`

**Interfaces:**
- Consumes: `NewsPanel` (Task 5), `useController()`'s snapshot.
- Produces: no new exports; `PositionsTable` gains an optional
  `blockedSymbols?: Record<string, string>` prop.

**Invariants:**
- `PositionsTable` must render identically when `blockedSymbols` is omitted — every existing
  test must stay green without modification.
- The badge appears only for symbols present in `blockedSymbols`.
- Overview renders normally when `snapshot.news` is undefined.

Read `OverviewPage.tsx` to see how `DollarBias` is mounted and follow the same placement
conventions.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/PositionsTable.test.tsx`:

```tsx
  it("badges a symbol that news is holding", () => {
    render(<PositionsTable positions={[POSITION_FIXTURE]}
                           blockedSymbols={{ [POSITION_FIXTURE.symbol]: "USD CPI in 20m" }} />);
    expect(screen.getByTestId("news-blocked-badge")).toBeInTheDocument();
  });

  it("shows no badge when the symbol is not blocked", () => {
    render(<PositionsTable positions={[POSITION_FIXTURE]} blockedSymbols={{}} />);
    expect(screen.queryByTestId("news-blocked-badge")).toBeNull();
  });

  it("shows no badge when blockedSymbols is omitted", () => {
    render(<PositionsTable positions={[POSITION_FIXTURE]} />);
    expect(screen.queryByTestId("news-blocked-badge")).toBeNull();
  });
```

(Use the fixture name already present in that test file; do not invent a new one.)

Append to `frontend/src/sections/OverviewPage.test.tsx` a test asserting the Overview renders
`news-panel` when the snapshot carries a `news` block, and still renders without one.

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/components/PositionsTable.test.tsx src/sections/OverviewPage.test.tsx`
Expected: FAIL — no `news-blocked-badge`, no `news-panel` in Overview.

- [ ] **Step 3: Implement**

Add the optional `blockedSymbols` prop to `PositionsTable`, defaulting to `{}`, and render a
small warning-toned badge with `data-testid="news-blocked-badge"` and the reason as its
`title` for symbols present in the map. Mount `<NewsPanel data={snapshot?.news} />` on
`OverviewPage` beside the existing market-context widgets, and pass
`blockedSymbols={snapshot?.news?.blocked_symbols}` where `PositionsTable` is rendered.

- [ ] **Step 4: Run to verify they pass**

Run: `cd frontend && npm test`
Expected: the whole frontend suite green, including all pre-existing tests.

- [ ] **Step 5: Run the full Python suite, detached**

```bash
L=/tmp/news_s2.log
setsid nohup bash -c ".venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py' \
  > $L 2>&1; echo \"EXIT=\$?\" >> $L" < /dev/null > /dev/null 2>&1 &
until grep -q '^EXIT=' $L; do sleep 15; done; grep -E '^(Ran|OK|FAILED|EXIT=)' $L
```

Expected: `OK`. Baseline is 819 tests on `main`; this plan adds 8 + 5 + 10 + 11 = 34, so
expect **853**. Do not proceed on a red suite.

- [ ] **Step 6: Commit**

```bash
git add frontend/src src/ tests/ config/
git commit -m "feat(gui): mount NewsPanel on Overview + badge news-blocked positions"
```

---

## Self-Review

**Spec coverage.** Design spec §5 (dashboard) → Tasks 2, 5, 6. §6 (Telegram digest) →
Tasks 1, 3, 4. §2.x, §3, §4 are Session 1 and already shipped. MT5 fallback (§2.2) is
Session 3 and correctly absent.

**Type consistency.** `digest()`'s dict shape (Task 1) is consumed verbatim by the renderers
(Task 3) and the scheduler (Task 4) — `when_utc`, `currency`, `title`, `forecast`, `previous`,
`affects` appear identically in all three. `NewsBlock` (Task 5) matches the `snapshot()` shape
Session 1 shipped, which Task 2 passes through untouched. `blockedSymbols` is
`Record<string, string>` in Tasks 5 and 6 and `blocked_symbols` in the Python payload.

**Known risk.** Task 4 touches the live trading loop, though only additively — two awaits and
a flag reset. Both new methods swallow their own exceptions, and that is the property to test
hardest, because the loop's own handler re-raises.

**Deliberately out of scope.** MT5 `actual` values, the run-card browser, journal explorer,
and any change to blocking behaviour.
