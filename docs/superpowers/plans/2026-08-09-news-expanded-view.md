# News Expanded View Implementation Plan (sub-project C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the maximized Economic Calendar dialog a filterable, week-ahead table of all impact levels, fed by a new endpoint that does not touch the 2-second `/api/state` hot path.

**Architecture:** `ForexFactoryCsvSource.fetch()` fetches `thisweek` **and** `nextweek` and returns their union, so `NewsManager.update_calendar()`'s failure ladder is untouched. A new `GET /api/news/calendar` serves the forward-only calendar. The frontend keeps all filter/group/sort logic in a pure, React-free module and renders a dense table in the existing maximized dialog.

**Tech Stack:** Python 3.10+ / FastAPI / stdlib `unittest` · React 18 / TypeScript / Tailwind / Radix Dialog / Vitest + Testing Library

**Spec:** `docs/superpowers/specs/2026-08-08-news-expanded-view-design.md` (commit `90cba9a`)

---

## Global Constraints

- **Never run in the main checkout.** A live trading bot serves `frontend/dist` from it (pid 304062, ports 8770 / 32768 / 32769). `npm run build` in the main checkout swaps the GUI the running bot is serving.
- **Do not run `npm install` / `npm ci`** (>10 min, leaves nothing behind if interrupted). Symlink `node_modules` — see Pre-flight.
- `export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"` before any node command, every session.
- **Do not restart the bot.** The Python changes are inert until the owner restarts it. Ask; do not act.
- **Do not merge to `main`.** Sub-project D is unmerged with a measurement outstanding.
- **Do not stage files you did not create.** Another session has uncommitted work in `docs/sessions/` and `docs/session-reviews/`. Always `git add` explicit paths, never `git add -A` or `git add .`.
- **Port 8899 is occupied** by another session's devserver (pid 1019418). Use **8901**.
- **jsdom computes no layout and resolves no colour.** Never assert a Tailwind class string, a hex, an HSL literal, a width, or "the text fits". Colour and layout are verified in a browser only.
- **Every new guard must be proved to bite:** apply the mutation, capture the FAIL output, restore, capture the PASS output. Report both.
- **Non-emptiness first.** Before asserting anything about a collection's members, assert the collection is non-empty.
- **Use only Tailwind keys that exist in `tailwind.config.ts`.** An invented utility (`ring-focus-ring`, `text-impact`, …) generates *no CSS at all* — Tailwind emits nothing and the element silently loses the style. jsdom cannot see it and neither can a class-string assertion. The real keys here are `ring-ring` (not `ring-focus-ring`), `text-impact-high|medium|low`, `bg-impact-high|medium|low`, `bg-surface-1|2`, `border-border`, `text-muted-foreground`, `bg-accent/20`. Grep an existing component before inventing one.
- Commit after every task. Conventional-commit prefixes (`feat(news):`, `test(news):`, `refactor(news):`).

### Naming and copy (verbatim — do not paraphrase)

| thing | exact value |
|---|---|
| Impact labels | `High` · `Med` · `Low` |
| Truncated-horizon note | `Next week's calendar is unavailable — showing through {date}.` |
| Filtered-to-zero heading | `No events match these filters` |
| Reset control | `Reset filters` |
| Horizon options | `Today` · `3d` · `7d` · `All` |
| Affects-my-book toggle | `Affects my book` |
| Overflow counter | `+{N} more` where **N is the remainder** |
| Time format | `HH:MMZ`, UTC (e.g. `12:30Z`) |

### Defaults

Impact **HIGH + MEDIUM on, LOW off**. Horizon **`7d`**. Affects-my-book **off**.

---

## Pre-flight (do this once, before Task 1)

```bash
cd /home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro
git worktree add -b feat/news-expanded ../titan-news-expanded main
cd ../titan-news-expanded
ln -sfn /home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/frontend/node_modules frontend/node_modules
export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"
git branch --show-current   # MUST print: feat/news-expanded
```

`git worktree add -b <name> <path> main` — **the explicit `main` start-point is required.** Without it the worktree branches off whatever HEAD the shared checkout is parked on, which may be another session's branch.

Worktrees carry only tracked files, so there is no `.venv` there. Use the main checkout's interpreter by absolute path:

```bash
PY=/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python
$PY -m unittest discover -s tests/unit -p 'test_*.py'
```

---

## File Structure

| file | responsibility |
|---|---|
| `src/analysis/news/sources/forexfactory.py` | **modify** — two-URL fetch, `next_week_ok` |
| `src/analysis/news/manager.py` | **modify** — expose `horizon_truncated` |
| `src/ops/web/news_view.py` | **create** — assemble `/api/news/calendar`, defensively |
| `src/ops/web/server.py` | **modify** — register the route |
| `tests/unit/test_news_forexfactory_fetch.py` | **modify** — migrate 6 `_get` sites to the URL-aware signature |
| `tests/unit/test_news_two_week_horizon.py` | **create** — the three source rules + the freshness-isolation guard |
| `tests/unit/test_gui_news_calendar.py` | **create** — endpoint shape, memo, isolation |
| `frontend/src/lib/types.ts` | **modify** — `CalendarEventRow`, `NewsCalendar` |
| `frontend/src/lib/newsCalendar.ts` | **create** — **pure** filter / group / sort / decorate |
| `frontend/src/lib/newsCalendar.test.ts` | **create** — the real coverage (no jsdom) |
| `frontend/src/lib/api.ts` | **modify** — `getNewsCalendar()` |
| `frontend/src/lib/useNewsCalendar.ts` | **create** — fetch + 60s poll, gated on `enabled` |
| `frontend/src/components/market/ImpactChip.tsx` | **create** — the `--impact-*` token consumer |
| `frontend/src/components/market/CalendarFilters.tsx` | **create** — impact / book / horizon controls |
| `frontend/src/components/market/CalendarTable.tsx` | **create** — day-grouped table |
| `frontend/src/components/market/CalendarExpanded.tsx` | **create** — composition + states |
| `frontend/src/sections/OverviewPage.tsx:358` | **modify** — swap the dialog body |

`frontend/src/components/market/NewsPanel.tsx` is **NOT touched** (spec §4.6).

---

### Task 1: Two-week fetch with freshness isolation

**Files:**
- Modify: `src/analysis/news/sources/forexfactory.py:36-145`
- Modify: `src/analysis/news/manager.py` (add one property)
- Modify: `tests/unit/test_news_forexfactory_fetch.py:40,55,69,76,84,99`
- Test: `tests/unit/test_news_two_week_horizon.py` (create)

**Interfaces:**
- Produces: `ForexFactoryCsvSource.NEXT_URL: str`; `ForexFactoryCsvSource.next_week_ok: bool`; `ForexFactoryCsvSource._get(self, url: str)` (signature change); `NewsManager.horizon_truncated -> bool`.
- Consumes: nothing.

**Why this shape:** `NewsManager.update_calendar()` decides whether a live bot halts trading. Putting the union inside the source means that ladder is not edited at all. The one rule that is easy to get wrong: a `thisweek` that yields **0 events from non-empty rows** is a *broken feed*, and `manager.py:70`'s guard (`if rows_seen and not events`) is what catches it. If next week's events were appended in that case, `events` would be non-empty, the guard would never fire, and the cache would be stamped fresh while the bot traded blind through this week's red folders.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_news_two_week_horizon.py`:

```python
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.manager import NewsManager
from src.analysis.news.sources.forexfactory import ForexFactoryCsvSource, NewsFetchError
from src.analysis.news.store import CalendarStore

THIS_URL = ForexFactoryCsvSource.URL
NEXT_URL = ForexFactoryCsvSource.NEXT_URL

HEADER = "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"
THIS_CSV = HEADER + "FOMC Statement,USD,08-05-2026,6:00pm,High,,,https://e.test/1\n"
NEXT_CSV = HEADER + "Non-Farm Employment Change,USD,08-14-2026,12:30pm,High,85K,57K,https://e.test/2\n"
# Rows present, but the date format has drifted -> every row fails to parse.
DRIFTED = HEADER + "CPI m/m,USD,2026/08/05,8:30 AM,High,,,https://e.test/3\n"


class _StubLogger:
    def __init__(self):
        self.events = []

    def log_event(self, level, tag, message):
        self.events.append((level, tag, message))


class _Response:
    def __init__(self, status_code, body=""):
        self.status_code = status_code
        self.content = body.encode("utf-8")


def _router(bodies, failures=()):
    """url -> body. Urls named in `failures` raise, as a dead endpoint would."""
    def _get(url):
        if url in failures:
            raise OSError("connection refused")
        return _Response(200, bodies.get(url, HEADER))
    return _get


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _source(bodies, failures=(), logger=None):
    src = ForexFactoryCsvSource(logger or _StubLogger())
    src.backoff_base_s = 0          # keep the retry ladder instant in tests
    src._get = _router(bodies, failures)
    return src


class UnionCoversBothWeeks(unittest.TestCase):
    def test_returns_events_from_this_week_and_next_week(self):
        src = _source({THIS_URL: THIS_CSV, NEXT_URL: NEXT_CSV})
        events = _run(src.fetch())
        titles = sorted(e.title for e in events)
        self.assertTrue(titles, "fetch returned nothing; the rest of this test is vacuous")
        self.assertEqual(titles, ["FOMC Statement", "Non-Farm Employment Change"])
        self.assertTrue(src.next_week_ok)

    def test_an_event_present_in_both_files_is_not_duplicated(self):
        # The week-boundary overlap: the same release in both CSVs.
        src = _source({THIS_URL: THIS_CSV, NEXT_URL: THIS_CSV})
        events = _run(src.fetch())
        keys = {e.key for e in events}
        self.assertTrue(keys)
        self.assertEqual(len(keys), 1, "make_key must collapse the boundary duplicate")


class ThisWeekGovernsFailure(unittest.TestCase):
    def test_this_week_down_raises_even_when_next_week_is_healthy(self):
        src = _source({NEXT_URL: NEXT_CSV}, failures=(THIS_URL,))
        with self.assertRaises(NewsFetchError):
            _run(src.fetch())

    def test_next_week_down_returns_this_week_and_flags_truncation(self):
        logger = _StubLogger()
        src = _source({THIS_URL: THIS_CSV}, failures=(NEXT_URL,), logger=logger)
        events = _run(src.fetch())
        self.assertTrue(events)
        self.assertEqual([e.title for e in events], ["FOMC Statement"])
        self.assertFalse(src.next_week_ok)
        self.assertTrue(any(lvl == "WARN" for lvl, _, _ in logger.events))

    def test_a_broken_this_week_is_not_rescued_by_next_week(self):
        # THE load-bearing rule. rows_seen>0 and events==[] is how
        # NewsManager detects a date-format drift; appending next week's
        # events would make `events` non-empty and silence that guard.
        src = _source({THIS_URL: DRIFTED, NEXT_URL: NEXT_CSV})
        events = _run(src.fetch())
        self.assertEqual(events, [])
        self.assertGreater(src.last_rows_seen, 0)

    def test_last_rows_seen_reports_this_week_only(self):
        src = _source({THIS_URL: THIS_CSV, NEXT_URL: NEXT_CSV})
        _run(src.fetch())
        self.assertEqual(src.last_rows_seen, 1)


class FreshnessIsolation(unittest.TestCase):
    """End-to-end: a broken this-week must never stamp the cache fresh."""

    def _manager(self, src):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as fh:
            path = fh.name
        os.unlink(path)
        return NewsManager(_StubLogger(), config={"news": {"cache_path": path}},
                           source=src, store=CalendarStore(path))

    def test_healthy_next_week_does_not_refresh_a_broken_this_week(self):
        src = _source({THIS_URL: DRIFTED, NEXT_URL: NEXT_CSV})
        mgr = self._manager(src)
        _run(mgr.update_calendar())
        now = datetime.now(timezone.utc)
        self.assertIsNone(mgr.store.age(now),
                          "a broken this-week stamped the cache fresh")
        self.assertEqual(mgr.store.events(), [])

    def test_a_good_refresh_does_stamp(self):
        # The counterpart — without this, the test above passes trivially
        # if update_calendar were broken outright.
        src = _source({THIS_URL: THIS_CSV, NEXT_URL: NEXT_CSV})
        mgr = self._manager(src)
        _run(mgr.update_calendar())
        self.assertIsNotNone(mgr.store.age(datetime.now(timezone.utc)))
        self.assertEqual(len(mgr.store.events()), 2)

    def test_horizon_truncated_follows_the_source(self):
        src = _source({THIS_URL: THIS_CSV}, failures=(NEXT_URL,))
        mgr = self._manager(src)
        _run(mgr.update_calendar())
        self.assertTrue(mgr.horizon_truncated)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

```bash
PY=/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python
$PY -m unittest tests.unit.test_news_two_week_horizon -v
```

Expected: FAIL — `AttributeError: type object 'ForexFactoryCsvSource' has no attribute 'NEXT_URL'`.

- [ ] **Step 3: Implement the two-URL fetch**

In `src/analysis/news/sources/forexfactory.py`, add `NEXT_URL` beside `URL`:

```python
class ForexFactoryCsvSource:
    NAME = "forexfactory"
    URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.csv"
    # Spec 2026-08-08 §3.1. thisweek alone decays to ~0 days of lookahead by
    # Friday, so the expanded view would be empty for much of its life.
    NEXT_URL = "https://nfs.faireconomy.media/ff_calendar_nextweek.csv"
```

Extend `__init__` (keep every existing line; add two):

```python
    def __init__(self, logger, url: str | None = None, tz=timezone.utc,
                 next_url: str | None = None):
        self.logger = logger
        self.url = url or self.URL
        self.next_url = next_url or self.NEXT_URL
        self.tz = tz
        self.max_retries = 3
        self.backoff_base_s = 1.0
        self.timeout_s = 15
        self.last_rows_seen = 0
        # False only after an OBSERVED next-week failure. Optimistic before any
        # attempt: absence of evidence of truncation, not a claim of success.
        self.next_week_ok = True
```

Change `_get` to take the url:

```python
    def _get(self, url: str):
        """Blocking HTTP. Isolated so tests can substitute it."""
        return requests.get(url, headers=self._headers(), timeout=self.timeout_s)
```

Replace `fetch()` with a per-url helper plus the union:

```python
    async def _fetch_one(self, url: str) -> list[CalendarEvent]:
        """One URL through the retry ladder. Raises if it never answered."""
        last = "no attempt made"
        for attempt in range(self.max_retries):
            body = None
            try:
                response = await asyncio.to_thread(self._get, url)
                if response.status_code == 200:
                    body = response.content.decode("utf-8", "replace")
                else:
                    last = f"HTTP {response.status_code}"
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
            if body is not None:
                # Deliberately outside the except above: a bug in parse() must
                # surface as itself, never be retried and relabelled an outage.
                return self.parse(body)
            self.logger.log_event("WARN", "NEWS", f"Attempt {attempt + 1} ({url}): {last}")
            if attempt < self.max_retries - 1 and self.backoff_base_s:
                await asyncio.sleep(self.backoff_base_s * (2 ** attempt))
        raise NewsFetchError(last)

    async def fetch(self) -> list[CalendarEvent]:
        """This week UNION next week.

        Three rules (spec §3.1), in priority order:
          1. this week fails            -> raise, exactly as before
          2. this week is BROKEN        -> return it alone, so NewsManager's
             (rows>0, events==0)           `if rows_seen and not events` guard fires
          3. next week fails            -> return this week, flag truncation
        """
        events = await self._fetch_one(self.url)     # rule 1: propagates
        this_rows = self.last_rows_seen
        if this_rows and not events:                 # rule 2
            self.next_week_ok = True
            return events
        try:
            upcoming = await self._fetch_one(self.next_url)
        except NewsFetchError as exc:                # rule 3
            self.next_week_ok = False
            self.logger.log_event(
                "WARN", "NEWS",
                f"Next-week calendar unavailable ({exc}); horizon limited to this week.")
            self.last_rows_seen = this_rows
            return events
        self.next_week_ok = True
        # last_rows_seen must describe THIS week only -- it is the input to the
        # broken-feed guard, and next week's row count would mask a drift.
        self.last_rows_seen = this_rows
        return events + upcoming
```

In `src/analysis/news/manager.py`, add after `is_globally_blocked`:

```python
    @property
    def horizon_truncated(self) -> bool:
        """The last completed refresh could not reach next week (spec §3.2).
        Display-only: it never implies the trading calendar is unhealthy --
        that is `status` / `cache_age_min`."""
        return not getattr(self.source, "next_week_ok", True)
```

- [ ] **Step 4: Migrate the 6 `_get` injection sites**

`_get` now takes a url, so every existing stub is arity-wrong. In `tests/unit/test_news_forexfactory_fetch.py`, add near `_Response`:

```python
HEADER_ONLY = "Title,Country,Date,Time,Impact,Forecast,Previous,URL\n"


def _only_this_week(body, status=200):
    """Answer the this-week URL with `body`; next-week gets an empty calendar.

    Keeps these tests about the retry ladder rather than the union -- a stub
    that returned the same CSV for both URLs would double every event count.
    """
    def _get(url):
        if url == ForexFactoryCsvSource.URL:
            return _Response(status, body)
        return _Response(200, HEADER_ONLY)
    return _get
```

Then rewrite each site:

| line | before | after |
|---|---|---|
| 40 | `src._get = lambda: _Response(200, CSV)` | `src._get = _only_this_week(CSV)` |
| 76 | `src._get = lambda: _Response(503)` | `src._get = _only_this_week("", status=503)` |
| 84 | `src._get = lambda: _Response(200, header_only)` | `src._get = _only_this_week(header_only)` |

For the three closures (`flaky` at 55, `dead` at 69, `counted` at 99), give each a `url` parameter and count **only the this-week URL**, e.g.:

```python
        def flaky(url):
            if url != ForexFactoryCsvSource.URL:
                return _Response(200, HEADER_ONLY)
            calls["n"] += 1
            if calls["n"] < 2:
                raise OSError("boom")
            return _Response(200, CSV)
```

Apply the same `url`-first guard to `dead` and `counted`.

- [ ] **Step 5: Run both suites to verify they pass**

```bash
$PY -m unittest tests.unit.test_news_two_week_horizon tests.unit.test_news_forexfactory_fetch \
                tests.unit.test_news_forexfactory_parse tests.unit.test_news_manager_failure_ladder -v
```

Expected: PASS, all four modules.

- [ ] **Step 6: Prove the load-bearing guard bites**

Mutation — in `fetch()`, delete rule 2 (the `if this_rows and not events:` early return). Run:

```bash
$PY -m unittest tests.unit.test_news_two_week_horizon -v 2>&1 | tail -20
```

Expected: **FAIL** on `test_a_broken_this_week_is_not_rescued_by_next_week` *and* `test_healthy_next_week_does_not_refresh_a_broken_this_week`. Capture the output, restore the lines, re-run, capture the PASS. Report both.

- [ ] **Step 7: Commit**

```bash
git add src/analysis/news/sources/forexfactory.py src/analysis/news/manager.py \
        tests/unit/test_news_two_week_horizon.py tests/unit/test_news_forexfactory_fetch.py
git commit -m "feat(news): fetch next week's calendar without weakening the freshness ladder"
```

---

### Task 2: `GET /api/news/calendar`

**Files:**
- Create: `src/ops/web/news_view.py`
- Modify: `src/ops/web/server.py:18` (import), `:69` (route, after `/api/equity`)
- Test: `tests/unit/test_gui_news_calendar.py` (create)

**Interfaces:**
- Consumes: `NewsManager.horizon_truncated` (Task 1).
- Produces: `build_calendar(controller) -> dict` with keys `status`, `cache_age_min`, `horizon_truncated`, `events`; each event has `when_utc`, `currency`, `importance`, `title`, `forecast`, `previous`, `url`, `affects`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_gui_news_calendar.py`:

```python
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.analysis.news.models import CalendarEvent, make_key
from src.ops.web.news_view import build_calendar

NOW = datetime.now(timezone.utc)
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "USDCAD"]
CURRENCIES = {"EURUSD": ["EUR", "USD"], "GBPUSD": ["GBP", "USD"],
              "USDJPY": ["USD", "JPY"], "XAUUSD": ["USD"], "USDCAD": ["USD", "CAD"]}


def _event(offset_h, currency, importance, title):
    when = NOW + timedelta(hours=offset_h)
    return CalendarEvent(key=make_key(currency, title, when), when_utc=when,
                         currency=currency, importance=importance, title=title,
                         forecast="1.0%", previous="0.9%", url="https://e.test")


class _Policy:
    def __init__(self):
        self.calls = []

    def mapped_symbols(self):
        return list(SYMBOLS)

    def currencies_for(self, symbol):
        self.calls.append(symbol)
        return CURRENCIES[symbol]

    def is_stale(self, age):
        return False


class _Store:
    def __init__(self, events, raises=False):
        self._events = events
        self.raises = raises

    def events(self):
        if self.raises:
            raise RuntimeError("store exploded")
        return sorted(self._events, key=lambda e: e.when_utc)

    def age(self, now):
        return timedelta(minutes=42)


class _Manager:
    def __init__(self, events, raises=False, truncated=False):
        self.store = _Store(events, raises)
        self.policy = _Policy()
        self.feed_degraded = False
        self.horizon_truncated = truncated


class _Controller:
    def __init__(self, manager=None):
        if manager is not None:
            self.news_manager = manager


EVENTS = [
    _event(-30, "USD", "HIGH", "Past Release"),
    _event(2, "USD", "HIGH", "Non-Farm Employment Change"),
    _event(3, "EUR", "MEDIUM", "German Factory Orders m/m"),
    _event(4, "CHF", "LOW", "SECO Consumer Climate"),
    _event(5, "USD", "LOW", "Consumer Credit m/m"),
]


class CalendarShape(unittest.TestCase):
    def test_drops_past_events_and_keeps_future_ones(self):
        out = build_calendar(_Controller(_Manager(EVENTS)))
        self.assertTrue(out["events"], "no events survived; later assertions would be vacuous")
        titles = [e["title"] for e in out["events"]]
        self.assertNotIn("Past Release", titles)
        self.assertEqual(len(titles), 4)

    def test_carries_every_impact_level(self):
        out = build_calendar(_Controller(_Manager(EVENTS)))
        self.assertEqual({e["importance"] for e in out["events"]},
                         {"HIGH", "MEDIUM", "LOW"})

    def test_events_are_ordered_by_time(self):
        out = build_calendar(_Controller(_Manager(EVENTS)))
        stamps = [e["when_utc"] for e in out["events"]]
        self.assertEqual(stamps, sorted(stamps))

    def test_affects_lists_every_symbol_the_currency_touches(self):
        out = build_calendar(_Controller(_Manager(EVENTS)))
        usd = next(e for e in out["events"] if e["title"] == "Non-Farm Employment Change")
        self.assertTrue(usd["affects"])
        self.assertEqual(sorted(usd["affects"]),
                         ["EURUSD", "GBPUSD", "USDCAD", "USDJPY", "XAUUSD"])

    def test_affects_is_empty_for_a_currency_this_book_never_trades(self):
        out = build_calendar(_Controller(_Manager(EVENTS)))
        chf = next(e for e in out["events"] if e["currency"] == "CHF")
        self.assertEqual(chf["affects"], [])

    def test_affects_is_memoised_per_currency_not_per_event(self):
        # 3 distinct forward currencies x 5 symbols = 15 lookups.
        # Without the memo it is 4 events x 5 symbols = 20.
        mgr = _Manager(EVENTS)
        build_calendar(_Controller(mgr))
        self.assertEqual(len(mgr.policy.calls), 15)

    def test_reports_cache_age_and_truncation(self):
        out = build_calendar(_Controller(_Manager(EVENTS, truncated=True)))
        self.assertEqual(out["cache_age_min"], 42)
        self.assertTrue(out["horizon_truncated"])
        self.assertEqual(out["status"], "ok")


class CalendarDegrades(unittest.TestCase):
    def test_missing_news_manager_is_unavailable(self):
        out = build_calendar(_Controller())
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["events"], [])

    def test_a_raising_store_is_unavailable_not_an_exception(self):
        out = build_calendar(_Controller(_Manager(EVENTS, raises=True)))
        self.assertEqual(out["status"], "unavailable")
        self.assertEqual(out["events"], [])

    def test_the_unavailable_payload_is_a_fresh_dict_each_call(self):
        first = build_calendar(_Controller())
        first["events"].append("mutated")
        self.assertEqual(build_calendar(_Controller())["events"], [])


class StateEndpointIsUnaffected(unittest.TestCase):
    def test_state_snapshot_does_not_carry_the_calendar(self):
        # The whole point of a separate endpoint: /api/state is polled every
        # 2s and must not grow by 46-93 KB (spec §3.3).
        from src.ops.web.state_view import _news_block
        block = _news_block(_Controller(_Manager(EVENTS)))
        self.assertNotIn("events", block)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

```bash
$PY -m unittest tests.unit.test_gui_news_calendar -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.ops.web.news_view'`.

- [ ] **Step 3: Implement `news_view.py`**

Create `src/ops/web/news_view.py`:

```python
"""Read-only assembly of the /api/news/calendar response (spec 2026-08-08 §3.2).

Deliberately NOT folded into build_snapshot: /api/state is polled every 2s
(useLiveState.ts:97) and a full forward calendar is 46-93 KB of JSON that
changes at most hourly. Serving it there would ship ~2-4 GB/day out of the
live trading process for data with an hourly refresh interval.

Same defensive contract as state_view._news_block: any fault degrades to
"unavailable" rather than propagating to the caller.
"""
from datetime import datetime, timezone


def _unavailable() -> dict:
    # A fresh dict per call -- a shared module constant could be mutated by a
    # caller and would then poison every later response.
    return {"status": "unavailable", "cache_age_min": None,
            "horizon_truncated": False, "events": []}


def build_calendar(controller) -> dict:
    try:
        manager = getattr(controller, "news_manager", None)
        if manager is None:
            return _unavailable()
        now = datetime.now(timezone.utc)
        age = manager.store.age(now)
        symbols = manager.policy.mapped_symbols()

        cache: dict[str, list[str]] = {}

        def affects_for(currency: str) -> list[str]:
            """Memoised per CURRENCY. Without this it is one currencies_for()
            call per (event, symbol) pair -- ~2400 calls on a real 197-event
            cache to produce at most 10 distinct answers."""
            hit = cache.get(currency)
            if hit is None:
                hit = [s for s in symbols
                       if currency in manager.policy.currencies_for(s)]
                cache[currency] = hit
            return hit

        events = []
        for event in manager.store.events():
            if event.when_utc < now:          # forward-only; the store never prunes
                continue
            events.append({
                "when_utc": event.when_utc.isoformat(),
                "currency": event.currency,
                "importance": event.importance,
                "title": event.title,
                "forecast": event.forecast,
                "previous": event.previous,
                "url": event.url,
                "affects": list(affects_for(event.currency)),
            })
        return {
            "status": "stale" if manager.policy.is_stale(age)
                      else ("degraded" if manager.feed_degraded else "ok"),
            "cache_age_min": None if age is None else int(age.total_seconds() // 60),
            "horizon_truncated": bool(getattr(manager, "horizon_truncated", False)),
            "events": events,
        }
    except Exception:  # the GUI must never break on news
        return _unavailable()
```

- [ ] **Step 4: Register the route**

In `src/ops/web/server.py`, extend the existing import at line 18:

```python
from .state_view import build_snapshot, history_rows
from .news_view import build_calendar
```

And add the route immediately after the `/api/equity` handler:

```python
    @app.get("/api/news/calendar", dependencies=read)
    def get_news_calendar():
        # Separate from /api/state on purpose (spec §3.3): the 2s snapshot poll
        # must not carry a payload that only changes hourly.
        return build_calendar(controller)
```

- [ ] **Step 5: Run to verify it passes**

```bash
$PY -m unittest tests.unit.test_gui_news_calendar tests.unit.test_gui_news -v
```

Expected: PASS, both modules.

- [ ] **Step 6: Prove the memo and the forward filter bite**

Mutation A — inline `affects_for` so it recomputes per event (replace the `affects` value with the list comprehension directly). Expect `test_affects_is_memoised_per_currency_not_per_event` to FAIL with `20 != 15`.

Mutation B — delete the `if event.when_utc < now: continue` line. Expect `test_drops_past_events_and_keeps_future_ones` to FAIL with `5 != 4`.

Capture FAIL output for each, restore, capture PASS. Report all four outputs.

- [ ] **Step 7: Commit**

```bash
git add src/ops/web/news_view.py src/ops/web/server.py tests/unit/test_gui_news_calendar.py
git commit -m "feat(news): serve the forward calendar on /api/news/calendar, off the 2s hot path"
```

---

### Task 3: Pure calendar logic (`newsCalendar.ts`)

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Create: `frontend/src/lib/newsCalendar.ts`
- Test: `frontend/src/lib/newsCalendar.test.ts`

**Interfaces:**
- Consumes: the Task 2 payload shape.
- Produces:
  - `type Impact = "HIGH" | "MEDIUM" | "LOW"`
  - `type Horizon = "today" | "3d" | "7d" | "all"`
  - `interface CalendarFilterState { impacts: Impact[]; affectsMyBookOnly: boolean; horizon: Horizon }`
  - `const DEFAULT_FILTERS: CalendarFilterState`
  - `interface DecoratedRow` — `CalendarEventRow` + `orderedAffects: string[]`, `heldAffects: string[]`, `isHeld: boolean`
  - `interface DayGroup { dayIso: string; rows: DecoratedRow[]; tally: Record<Impact, number> }`
  - `function buildCalendarView(events, filters, nowMs, heldSymbols): DayGroup[]`
  - `function horizonEndMs(nowMs: number, horizon: Horizon): number`

**Why pure:** every consequential rule becomes a plain function test that runs with no jsdom, no DOM, and no mocking. This is where the real coverage lives.

- [ ] **Step 1: Add the types**

Append to `frontend/src/lib/types.ts`:

```ts
export interface CalendarEventRow {
  when_utc: string;
  currency: string;
  importance: "HIGH" | "MEDIUM" | "LOW";
  title: string;
  forecast?: string | null;
  previous?: string | null;
  url?: string | null;
  affects: string[];
}

/** GET /api/news/calendar. Separate from NewsBlock, which rides the 2s
 *  /api/state poll and stays deliberately lean (spec §3.3). */
export interface NewsCalendar {
  status: "ok" | "degraded" | "stale" | "unavailable";
  cache_age_min?: number | null;
  horizon_truncated?: boolean;
  events: CalendarEventRow[];
}
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/lib/newsCalendar.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { buildCalendarView, horizonEndMs, DEFAULT_FILTERS,
         type CalendarFilterState } from "./newsCalendar";
import type { CalendarEventRow } from "./types";

const NOW = Date.parse("2026-08-07T10:00:00Z");
const DAY = 86_400_000;

function ev(when: string, importance: CalendarEventRow["importance"],
            title: string, currency = "USD", affects: string[] = ["XAUUSD", "EURUSD"]):
            CalendarEventRow {
  return { when_utc: when, currency, importance, title, affects,
           forecast: "1.0", previous: "0.9" };
}

const ALL: CalendarFilterState = { impacts: ["HIGH", "MEDIUM", "LOW"],
                                   affectsMyBookOnly: false, horizon: "all" };

describe("horizonEndMs", () => {
  it("ends 'today' at the last instant of the current UTC day", () => {
    expect(horizonEndMs(NOW, "today")).toBe(Date.parse("2026-08-07T23:59:59.999Z"));
  });
  it("counts 3d and 7d forward from now", () => {
    expect(horizonEndMs(NOW, "3d")).toBe(NOW + 3 * DAY);
    expect(horizonEndMs(NOW, "7d")).toBe(NOW + 7 * DAY);
  });
  it("makes 'all' unbounded", () => {
    expect(horizonEndMs(NOW, "all")).toBe(Infinity);
  });
});

describe("buildCalendarView — filtering", () => {
  it("keeps only the selected impact levels", () => {
    const rows = [ev("2026-08-07T12:00:00Z", "HIGH", "H"),
                  ev("2026-08-07T13:00:00Z", "MEDIUM", "M"),
                  ev("2026-08-07T14:00:00Z", "LOW", "L")];
    const out = buildCalendarView(rows, { ...ALL, impacts: ["HIGH", "MEDIUM"] }, NOW, new Set());
    const titles = out.flatMap(g => g.rows.map(r => r.title));
    expect(titles.length).toBeGreaterThan(0);
    expect(titles).toEqual(["H", "M"]);
  });

  it("drops events whose currency reaches none of the traded symbols", () => {
    const rows = [ev("2026-08-07T12:00:00Z", "HIGH", "USD one", "USD", ["XAUUSD"]),
                  ev("2026-08-07T13:00:00Z", "HIGH", "CHF one", "CHF", [])];
    const out = buildCalendarView(rows, { ...ALL, affectsMyBookOnly: true }, NOW, new Set());
    const titles = out.flatMap(g => g.rows.map(r => r.title));
    expect(titles.length).toBeGreaterThan(0);
    expect(titles).toEqual(["USD one"]);
  });

  it("includes an event landing exactly on the horizon boundary", () => {
    const rows = [ev(new Date(NOW + 3 * DAY).toISOString(), "HIGH", "boundary")];
    const out = buildCalendarView(rows, { ...ALL, horizon: "3d" }, NOW, new Set());
    expect(out.flatMap(g => g.rows.map(r => r.title))).toEqual(["boundary"]);
  });

  it("excludes an event one millisecond past the horizon", () => {
    const rows = [ev(new Date(NOW + 3 * DAY + 1).toISOString(), "HIGH", "past-edge")];
    const out = buildCalendarView(rows, { ...ALL, horizon: "3d" }, NOW, new Set());
    expect(out).toEqual([]);
  });
});

describe("buildCalendarView — grouping", () => {
  it("splits events across the UTC midnight seam", () => {
    const rows = [ev("2026-08-07T23:59:00Z", "HIGH", "late"),
                  ev("2026-08-08T00:01:00Z", "HIGH", "early")];
    const out = buildCalendarView(rows, ALL, NOW, new Set());
    expect(out.map(g => g.dayIso)).toEqual(["2026-08-07", "2026-08-08"]);
    expect(out[0].rows.map(r => r.title)).toEqual(["late"]);
    expect(out[1].rows.map(r => r.title)).toEqual(["early"]);
  });

  it("tallies the FILTERED rows, so the header cannot contradict the body", () => {
    const rows = [ev("2026-08-07T12:00:00Z", "HIGH", "H1"),
                  ev("2026-08-07T13:00:00Z", "HIGH", "H2"),
                  ev("2026-08-07T14:00:00Z", "LOW", "L1")];
    const out = buildCalendarView(rows, { ...ALL, impacts: ["HIGH"] }, NOW, new Set());
    expect(out).toHaveLength(1);
    expect(out[0].tally).toEqual({ HIGH: 2, MEDIUM: 0, LOW: 0 });
    expect(out[0].rows).toHaveLength(2);
  });
});

describe("buildCalendarView — ordering and held symbols", () => {
  it("orders simultaneous events deterministically regardless of input order", () => {
    // The real NFP case: five releases share 12:30Z. Under a 60s poll an
    // unstable comparator would reshuffle these rows on every refresh.
    const a = ev("2026-08-07T12:30:00Z", "HIGH", "Average Hourly Earnings m/m");
    const b = ev("2026-08-07T12:30:00Z", "HIGH", "Non-Farm Employment Change");
    const c = ev("2026-08-07T12:30:00Z", "HIGH", "Unemployment Rate", "CAD", []);
    const first = buildCalendarView([a, b, c], ALL, NOW, new Set());
    const second = buildCalendarView([c, b, a], ALL, NOW, new Set());
    expect(first[0].rows.map(r => r.title)).toEqual(second[0].rows.map(r => r.title));
    expect(first[0].rows).toHaveLength(3);
  });

  it("sorts held symbols to the front of orderedAffects", () => {
    const rows = [ev("2026-08-07T12:00:00Z", "HIGH", "NFP", "USD",
                     ["EURUSD", "GBPUSD", "XAUUSD"])];
    const out = buildCalendarView(rows, ALL, NOW, new Set(["XAUUSD"]));
    expect(out[0].rows[0].orderedAffects[0]).toBe("XAUUSD");
    expect(out[0].rows[0].heldAffects).toEqual(["XAUUSD"]);
    expect(out[0].rows[0].isHeld).toBe(true);
  });

  it("marks a row unheld when no affected symbol is open", () => {
    const rows = [ev("2026-08-07T12:00:00Z", "HIGH", "NFP", "USD", ["EURUSD"])];
    const out = buildCalendarView(rows, ALL, NOW, new Set(["XAUUSD"]));
    expect(out[0].rows[0].isHeld).toBe(false);
    expect(out[0].rows[0].heldAffects).toEqual([]);
  });
});

describe("DEFAULT_FILTERS", () => {
  it("hides LOW, spans 7d, and does not pre-narrow to the book", () => {
    expect(DEFAULT_FILTERS.impacts).toEqual(["HIGH", "MEDIUM"]);
    expect(DEFAULT_FILTERS.horizon).toBe("7d");
    expect(DEFAULT_FILTERS.affectsMyBookOnly).toBe(false);
  });
});
```

- [ ] **Step 3: Run to verify it fails**

```bash
export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"
cd frontend && npx vitest run src/lib/newsCalendar.test.ts
```

Expected: FAIL — cannot resolve `./newsCalendar`.

- [ ] **Step 4: Implement**

Create `frontend/src/lib/newsCalendar.ts`:

```ts
import type { CalendarEventRow } from "./types";

export type Impact = "HIGH" | "MEDIUM" | "LOW";
export type Horizon = "today" | "3d" | "7d" | "all";

export const IMPACT_ORDER: Impact[] = ["HIGH", "MEDIUM", "LOW"];
export const HORIZONS: { id: Horizon; label: string }[] = [
  { id: "today", label: "Today" }, { id: "3d", label: "3d" },
  { id: "7d", label: "7d" }, { id: "all", label: "All" },
];

export interface CalendarFilterState {
  impacts: Impact[];
  affectsMyBookOnly: boolean;
  horizon: Horizon;
}

/** LOW is 76% of the feed, so it is off by default. `affectsMyBookOnly` is
 *  OFF: narrowing is one click, but a filter that silently hides 14% of the
 *  calendar before the operator touches anything gets blamed after a surprise. */
export const DEFAULT_FILTERS: CalendarFilterState = {
  impacts: ["HIGH", "MEDIUM"],
  affectsMyBookOnly: false,
  horizon: "7d",
};

export interface DecoratedRow extends CalendarEventRow {
  /** Affected symbols with an open position — always a prefix of orderedAffects. */
  heldAffects: string[];
  /** `affects` with held symbols first, so truncation never hides an open one. */
  orderedAffects: string[];
  isHeld: boolean;
}

export interface DayGroup {
  dayIso: string;                    // "2026-08-07"
  rows: DecoratedRow[];
  tally: Record<Impact, number>;
}

const DAY_MS = 86_400_000;

export function horizonEndMs(nowMs: number, horizon: Horizon): number {
  if (horizon === "all") return Infinity;
  if (horizon === "today") {
    // The rest of the current UTC day, not now+24h — "Today" is a calendar
    // day, and the whole surface is UTC (spec §4.2).
    const d = new Date(nowMs);
    return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate(),
                    23, 59, 59, 999);
  }
  return nowMs + (horizon === "3d" ? 3 : 7) * DAY_MS;
}

/** The UTC day, taken from the ISO STRING rather than a Date.
 *  `new Date(x).getDate()` would resolve in the viewer's local timezone and
 *  would move events across day boundaries west of UTC. */
function utcDayOf(whenUtc: string): string {
  return whenUtc.slice(0, 10);
}

function decorate(event: CalendarEventRow, held: Set<string>): DecoratedRow {
  const affects = event.affects ?? [];
  const heldAffects = affects.filter(s => held.has(s));
  const rest = affects.filter(s => !held.has(s));
  return { ...event, heldAffects, orderedAffects: [...heldAffects, ...rest],
           isHeld: heldAffects.length > 0 };
}

export function buildCalendarView(
  events: CalendarEventRow[],
  filters: CalendarFilterState,
  nowMs: number,
  heldSymbols: Set<string>,
): DayGroup[] {
  const impacts = new Set(filters.impacts);
  const end = horizonEndMs(nowMs, filters.horizon);

  const kept = (events ?? []).filter(e => {
    if (!impacts.has(e.importance)) return false;
    if (filters.affectsMyBookOnly && (e.affects ?? []).length === 0) return false;
    const at = Date.parse(e.when_utc);
    if (!Number.isFinite(at)) return false;      // a malformed stamp is not a row
    return at <= end;
  });

  // Explicit tiebreak on (time, currency, title). The backend sorts by time
  // alone, and CalendarStore.events() sorts a dict's values — so two events
  // sharing a timestamp have no stable relative order upstream. Five releases
  // really do share 12:30Z on an NFP day; without this they reshuffle on
  // every 60s poll.
  kept.sort((a, b) =>
    Date.parse(a.when_utc) - Date.parse(b.when_utc) ||
    a.currency.localeCompare(b.currency) ||
    a.title.localeCompare(b.title));

  const groups = new Map<string, DayGroup>();
  for (const event of kept) {
    const dayIso = utcDayOf(event.when_utc);
    let group = groups.get(dayIso);
    if (!group) {
      group = { dayIso, rows: [], tally: { HIGH: 0, MEDIUM: 0, LOW: 0 } };
      groups.set(dayIso, group);
    }
    group.rows.push(decorate(event, heldSymbols));
    group.tally[event.importance] += 1;          // tallies the FILTERED set
  }
  return [...groups.values()];
}
```

- [ ] **Step 5: Run to verify it passes**

```bash
cd frontend && npx vitest run src/lib/newsCalendar.test.ts
```

Expected: PASS, 13 tests.

- [ ] **Step 6: Prove three guards bite**

| mutation | must fail |
|---|---|
| drop the `||` tiebreaks from the comparator, leaving time only | `orders simultaneous events deterministically` |
| change `utcDayOf` to `new Date(whenUtc).toISOString().slice(0,10)`… then to a local-time `getDate()` formulation | `splits events across the UTC midnight seam` |
| move `group.tally[...] += 1` above the filter (tally the raw set) | `tallies the FILTERED rows` |
| change `at <= end` to `at < end` | `includes an event landing exactly on the horizon boundary` |

Capture FAIL, restore, capture PASS for each. Report all outputs.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/newsCalendar.ts frontend/src/lib/newsCalendar.test.ts frontend/src/lib/types.ts
git commit -m "feat(news): pure calendar filter/group/order logic with a stable comparator"
```

---

### Task 4: API method and `useNewsCalendar` hook

**Files:**
- Modify: `frontend/src/lib/api.ts:1` (import type), `:31` (after `getEquity`)
- Create: `frontend/src/lib/useNewsCalendar.ts`
- Test: `frontend/src/lib/useNewsCalendar.test.ts`

**Interfaces:**
- Consumes: `NewsCalendar` (Task 3).
- Produces: `api.getNewsCalendar(): Promise<NewsCalendar>`; `useNewsCalendar(api, enabled, opts?) -> { data: NewsCalendar | null; loading: boolean; error: ApiError | null }`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/useNewsCalendar.test.ts`:

```ts
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useNewsCalendar } from "./useNewsCalendar";
import type { NewsCalendar } from "./types";

const PAYLOAD: NewsCalendar = {
  status: "ok", cache_age_min: 12, horizon_truncated: false,
  events: [{ when_utc: "2026-08-07T12:30:00Z", currency: "USD", importance: "HIGH",
             title: "Non-Farm Employment Change", affects: ["XAUUSD"] }],
};

describe("useNewsCalendar", () => {
  it("does not touch the api while disabled", async () => {
    const getNewsCalendar = vi.fn().mockResolvedValue(PAYLOAD);
    renderHook(() => useNewsCalendar({ getNewsCalendar }, false));
    await new Promise(r => setTimeout(r, 20));
    expect(getNewsCalendar).not.toHaveBeenCalled();
  });

  it("fetches once when enabled", async () => {
    const getNewsCalendar = vi.fn().mockResolvedValue(PAYLOAD);
    const { result } = renderHook(() => useNewsCalendar({ getNewsCalendar }, true));
    await waitFor(() => expect(result.current.data).not.toBeNull());
    expect(getNewsCalendar).toHaveBeenCalledTimes(1);
    expect(result.current.data?.events).toHaveLength(1);
  });

  it("keeps the last good payload when a refresh fails", async () => {
    const getNewsCalendar = vi.fn()
      .mockResolvedValueOnce(PAYLOAD)
      .mockRejectedValue({ status: 500, kind: "error", detail: "boom" });
    const { result } = renderHook(() =>
      useNewsCalendar({ getNewsCalendar }, true, { pollMs: 10 }));
    await waitFor(() => expect(result.current.data).not.toBeNull());
    await waitFor(() => expect(result.current.error).not.toBeNull());
    // An empty calendar reads as "quiet week" — a lie. Keep the last good one.
    expect(result.current.data?.events).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd frontend && npx vitest run src/lib/useNewsCalendar.test.ts
```

Expected: FAIL — cannot resolve `./useNewsCalendar`.

- [ ] **Step 3: Add the api method**

In `frontend/src/lib/api.ts`, add `NewsCalendar` to the type import on line 1, then add after `getEquity`:

```ts
    getNewsCalendar: () => req<NewsCalendar>("/api/news/calendar"),
```

- [ ] **Step 4: Implement the hook**

Create `frontend/src/lib/useNewsCalendar.ts`:

```ts
import { useEffect, useRef, useState } from "react";
import type { Api, ApiError } from "./api";
import type { NewsCalendar } from "./types";

const DEFAULT_POLL_MS = 60_000;

/**
 * The expanded calendar's data source.
 *
 * Gated on `enabled` so a CLOSED dialog never polls — this endpoint exists
 * precisely to keep calendar bytes off the 2s hot path, and a background poll
 * for an invisible surface would give some of that back.
 *
 * 60s, not 2s: the underlying feed refreshes hourly (news.refresh_interval_min).
 * A failed refresh keeps the last good payload, because a blank table reads as
 * "no events scheduled" — the one thing an economic calendar must never imply
 * by accident.
 */
export function useNewsCalendar(
  api: Pick<Api, "getNewsCalendar">,
  enabled: boolean,
  opts: { pollMs?: number } = {},
) {
  const pollMs = opts.pollMs ?? DEFAULT_POLL_MS;
  const [data, setData] = useState<NewsCalendar | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  // Read through a ref (updated every render, NOT in the dep array) so an
  // inline `api` literal from the caller cannot restart the poll every render.
  const apiRef = useRef(api);
  apiRef.current = api;

  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    setLoading(true);

    const load = async () => {
      try {
        const next = await apiRef.current.getNewsCalendar();
        if (!alive) return;
        setData(next);
        setError(null);
      } catch (e) {
        if (!alive) return;
        setError(e as ApiError);        // keep the last good `data`
      } finally {
        if (alive) setLoading(false);
      }
    };

    void load();
    if (pollMs <= 0) return () => { alive = false; };
    const id = setInterval(() => { void load(); }, pollMs);
    return () => { alive = false; clearInterval(id); };
  }, [enabled, pollMs]);

  return { data, loading, error };
}
```

- [ ] **Step 5: Run to verify it passes**

```bash
cd frontend && npx vitest run src/lib/useNewsCalendar.test.ts && npx tsc -b
```

Expected: PASS (3 tests) and a clean typecheck.

- [ ] **Step 6: Prove the gate bites**

Mutation — delete `if (!enabled) return;`. Expect `does not touch the api while disabled` to FAIL. Capture, restore, capture PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/useNewsCalendar.ts frontend/src/lib/useNewsCalendar.test.ts
git commit -m "feat(news): calendar api method and a poll gated on dialog visibility"
```

---

### Task 5: `ImpactChip` and `CalendarFilters`

**Files:**
- Create: `frontend/src/components/market/ImpactChip.tsx`
- Create: `frontend/src/components/market/CalendarFilters.tsx`
- Test: `frontend/src/components/market/ImpactChip.test.tsx`, `CalendarFilters.test.tsx`

**Interfaces:**
- Consumes: `Impact`, `Horizon`, `CalendarFilterState`, `HORIZONS`, `IMPACT_ORDER` (Task 3).
- Produces: `<ImpactChip impact={Impact} />`; `<CalendarFilters value={CalendarFilterState} onChange={(next: CalendarFilterState) => void} />`.

**The binding rule (spec §5):** `--impact-high` (hue 10) sits ~12° from `--loss` (hue 358). Colour is redundant encoding; the **text label is the carrier**. The chip renders `High` / `Med` / `Low` unconditionally.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/market/ImpactChip.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ImpactChip } from "./ImpactChip";

describe("ImpactChip", () => {
  // jsdom resolves no colour, so the colour is NOT asserted here — it is
  // measured in the browser (plan Task 8). What jsdom CAN prove is the half
  // of spec §5 that matters most: the text label always exists.
  it.each([["HIGH", "High"], ["MEDIUM", "Med"], ["LOW", "Low"]] as const)(
    "renders the text label for %s so colour is never the only channel",
    (impact, label) => {
      render(<ImpactChip impact={impact} />);
      expect(screen.getByText(label)).toBeInTheDocument();
    });
});
```

Create `frontend/src/components/market/CalendarFilters.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CalendarFilters } from "./CalendarFilters";
import { DEFAULT_FILTERS } from "@/lib/newsCalendar";

describe("CalendarFilters", () => {
  it("reflects the active impact levels as pressed toggles", () => {
    render(<CalendarFilters value={DEFAULT_FILTERS} onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "High" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Med" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Low" })).toHaveAttribute("aria-pressed", "false");
  });

  it("removes an active impact when its toggle is clicked", async () => {
    const onChange = vi.fn();
    render(<CalendarFilters value={DEFAULT_FILTERS} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "High" }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ impacts: ["MEDIUM"] }));
  });

  it("adds an inactive impact when its toggle is clicked", async () => {
    const onChange = vi.fn();
    render(<CalendarFilters value={DEFAULT_FILTERS} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Low" }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ impacts: ["HIGH", "MEDIUM", "LOW"] }));
  });

  it("toggles the affects-my-book filter", async () => {
    const onChange = vi.fn();
    render(<CalendarFilters value={DEFAULT_FILTERS} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Affects my book" }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ affectsMyBookOnly: true }));
  });

  it("selects a horizon and marks the active one pressed", async () => {
    const onChange = vi.fn();
    render(<CalendarFilters value={DEFAULT_FILTERS} onChange={onChange} />);
    expect(screen.getByRole("button", { name: "7d" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Today" }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ horizon: "today" }));
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd frontend && npx vitest run src/components/market/ImpactChip.test.tsx src/components/market/CalendarFilters.test.tsx
```

Expected: FAIL — modules not found.

- [ ] **Step 3: Implement `ImpactChip`**

```tsx
import type { Impact } from "@/lib/newsCalendar";
import { cn } from "@/lib/utils";

/** Consumer of the --impact-* tokens A2 left with no consumer.
 *
 *  --impact-high (hue 10) sits ~12deg from --loss (hue 358) — deliberately,
 *  both are red by convention. So "high-impact release" and "losing money"
 *  could be confused at a glance and would be indistinguishable to a
 *  red-green colour-blind operator. The LABEL is the carrier; the colour is
 *  redundant. Never render this chip without its text. */
const LABEL: Record<Impact, string> = { HIGH: "High", MEDIUM: "Med", LOW: "Low" };
const TEXT: Record<Impact, string> = {
  HIGH: "text-impact-high", MEDIUM: "text-impact-medium", LOW: "text-impact-low",
};
const DOT: Record<Impact, string> = {
  HIGH: "bg-impact-high", MEDIUM: "bg-impact-medium", LOW: "bg-impact-low",
};

export function ImpactChip({ impact, className }: { impact: Impact; className?: string }) {
  return (
    <span
      data-impact={impact}
      className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-[10px] font-bold uppercase tracking-wide",
                    TEXT[impact], className)}
    >
      <span className={cn("size-1.5 rounded-[2px]", DOT[impact])} aria-hidden />
      {LABEL[impact]}
    </span>
  );
}
```

- [ ] **Step 4: Implement `CalendarFilters`**

```tsx
import { HORIZONS, IMPACT_ORDER, type CalendarFilterState, type Impact }
  from "@/lib/newsCalendar";
import { cn } from "@/lib/utils";

const LABEL: Record<Impact, string> = { HIGH: "High", MEDIUM: "Med", LOW: "Low" };

function Toggle({ label, pressed, onClick }:
                { label: string; pressed: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-0.5 text-xs transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        pressed
          ? "border-accent bg-accent/20 text-foreground"
          : "border-border bg-surface-2 text-muted-foreground hover:text-foreground")}
    >
      {label}
    </button>
  );
}

export function CalendarFilters({ value, onChange }:
    { value: CalendarFilterState; onChange: (next: CalendarFilterState) => void }) {
  const toggleImpact = (impact: Impact) => {
    const has = value.impacts.includes(impact);
    // Rebuilt from IMPACT_ORDER rather than push/splice, so the array order is
    // canonical no matter which sequence the operator clicked them in.
    const next = IMPACT_ORDER.filter(i =>
      i === impact ? !has : value.impacts.includes(i));
    onChange({ ...value, impacts: next });
  };

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5 border-b border-border bg-surface-1 px-4 py-2.5">
      {IMPACT_ORDER.map(impact => (
        <Toggle key={impact} label={LABEL[impact]}
                pressed={value.impacts.includes(impact)}
                onClick={() => toggleImpact(impact)} />
      ))}
      <span className="w-2" aria-hidden />
      <Toggle label="Affects my book" pressed={value.affectsMyBookOnly}
              onClick={() => onChange({ ...value, affectsMyBookOnly: !value.affectsMyBookOnly })} />
      <span className="flex-1" aria-hidden />
      <div className="flex overflow-hidden rounded-md border border-border">
        {HORIZONS.map(h => (
          <button
            key={h.id}
            type="button"
            aria-pressed={value.horizon === h.id}
            onClick={() => onChange({ ...value, horizon: h.id })}
            className={cn(
              "border-r border-border px-2.5 py-0.5 text-xs last:border-r-0 transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              value.horizon === h.id
                ? "bg-accent/20 text-foreground"
                : "text-muted-foreground hover:text-foreground")}
          >
            {h.label}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run to verify they pass**

```bash
cd frontend && npx vitest run src/components/market/ImpactChip.test.tsx src/components/market/CalendarFilters.test.tsx
```

Expected: PASS, 8 tests.

- [ ] **Step 6: Prove the label guard bites**

Mutation — in `ImpactChip`, replace `{LABEL[impact]}` with `{null}`. Expect all three `renders the text label for …` cases to FAIL. This is the enforceable half of spec §5. Capture, restore, capture PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/market/ImpactChip.tsx frontend/src/components/market/ImpactChip.test.tsx \
        frontend/src/components/market/CalendarFilters.tsx frontend/src/components/market/CalendarFilters.test.tsx
git commit -m "feat(news): impact chip (label-carried) and calendar filter controls"
```

---

### Task 6: `CalendarTable`

**Files:**
- Create: `frontend/src/components/market/CalendarTable.tsx`
- Test: `frontend/src/components/market/CalendarTable.test.tsx`

**Interfaces:**
- Consumes: `DayGroup`, `DecoratedRow` (Task 3); `ImpactChip` (Task 5).
- Produces: `<CalendarTable groups={DayGroup[]} />`.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CalendarTable } from "./CalendarTable";
import { buildCalendarView, DEFAULT_FILTERS } from "@/lib/newsCalendar";
import type { CalendarEventRow } from "@/lib/types";

const NOW = Date.parse("2026-08-07T10:00:00Z");

const ROWS: CalendarEventRow[] = [
  { when_utc: "2026-08-07T12:30:00Z", currency: "USD", importance: "HIGH",
    title: "Non-Farm Employment Change", forecast: "85K", previous: "57K",
    affects: ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"] },
  { when_utc: "2026-08-07T14:00:00Z", currency: "CAD", importance: "MEDIUM",
    title: "Ivey PMI", forecast: "55.4", previous: "56.2", affects: ["USDCAD"] },
];

function view(held: string[] = []) {
  return buildCalendarView(ROWS, { ...DEFAULT_FILTERS, horizon: "all" },
                           NOW, new Set(held));
}

describe("CalendarTable", () => {
  it("renders a row per event with its time in UTC", () => {
    render(<CalendarTable groups={view()} />);
    const rows = screen.getAllByTestId("calendar-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("12:30Z")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Non-Farm Employment Change")).toBeInTheDocument();
    expect(within(rows[0]).getByText("85K")).toBeInTheDocument();
  });

  it("shows a day header carrying the filtered tally", () => {
    render(<CalendarTable groups={view()} />);
    const header = screen.getByTestId("calendar-day-header");
    expect(within(header).getByText(/Friday 7 August/)).toBeInTheDocument();
    expect(within(header).getByText(/1 high · 1 med/)).toBeInTheDocument();
  });

  it("truncates a long affects list with a remainder counter", () => {
    render(<CalendarTable groups={view()} />);
    // 4 affected symbols, 2 chips shown -> "+2 more", NOT "+4".
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("names the held symbol in accessible text, not colour alone", () => {
    render(<CalendarTable groups={view(["XAUUSD"])} />);
    const row = screen.getAllByTestId("calendar-row")[0];
    expect(within(row).getByText(/Open position in XAUUSD/)).toBeInTheDocument();
  });

  it("puts a held symbol in the visible chips even when it sorted last", () => {
    // XAUUSD is 4th in `affects`; only 2 chips render. If held symbols were
    // not hoisted, the position that costs money would hide behind "+2 more".
    render(<CalendarTable groups={view(["XAUUSD"])} />);
    const row = screen.getAllByTestId("calendar-row")[0];
    expect(within(row).getByTestId("affect-chip-XAUUSD")).toBeInTheDocument();
  });

  it("renders no held marker when nothing is open", () => {
    render(<CalendarTable groups={view()} />);
    expect(screen.queryByText(/Open position in/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd frontend && npx vitest run src/components/market/CalendarTable.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```tsx
import { ImpactChip } from "./ImpactChip";
import type { DayGroup, DecoratedRow } from "@/lib/newsCalendar";
import { cn } from "@/lib/utils";

const MAX_CHIPS = 2;

const dayFormatter = new Intl.DateTimeFormat("en-GB", {
  weekday: "long", day: "numeric", month: "long", timeZone: "UTC",
});
const timeFormatter = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC",
});

/** UTC everywhere, matching the collapsed card (NewsPanel.tsx:136-142), so the
 *  two surfaces can never disagree about when an event is. */
function formatTime(whenUtc: string): string {
  const at = new Date(whenUtc);
  return Number.isNaN(at.getTime()) ? "--:--" : `${timeFormatter.format(at)}Z`;
}

function formatDay(dayIso: string): string {
  const at = new Date(`${dayIso}T00:00:00Z`);
  return Number.isNaN(at.getTime()) ? dayIso : dayFormatter.format(at);
}

function tallyText(tally: DayGroup["tally"]): string {
  const parts: string[] = [];
  if (tally.HIGH) parts.push(`${tally.HIGH} high`);
  if (tally.MEDIUM) parts.push(`${tally.MEDIUM} med`);
  if (tally.LOW) parts.push(`${tally.LOW} low`);
  return parts.join(" · ");
}

function Affects({ row }: { row: DecoratedRow }) {
  const shown = row.orderedAffects.slice(0, MAX_CHIPS);
  const rest = row.orderedAffects.length - shown.length;
  const held = new Set(row.heldAffects);
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1"
         title={row.orderedAffects.join(", ")}>
      {shown.map(symbol => (
        <span
          key={symbol}
          data-testid={`affect-chip-${symbol}`}
          className={cn(
            "inline-flex items-center gap-1 rounded-full border px-1.5 py-px font-mono text-[10px]",
            held.has(symbol)
              ? "border-accent bg-accent/20 text-foreground"
              : "border-border bg-surface-2 text-muted-foreground")}
        >
          {held.has(symbol) && <span className="size-1 rounded-full bg-accent" aria-hidden />}
          {symbol}
        </span>
      ))}
      {rest > 0 && <span className="text-[10px] text-muted-foreground">+{rest} more</span>}
    </div>
  );
}

export function CalendarTable({ groups }: { groups: DayGroup[] }) {
  return (
    <table className="w-full table-fixed border-collapse text-xs">
      <caption className="sr-only">
        Upcoming economic releases, grouped by UTC day
      </caption>
      <thead>
        <tr className="sticky top-0 z-10 bg-surface-1">
          <th scope="col" className="w-[68px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Time</th>
          <th scope="col" className="w-[76px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Impact</th>
          <th scope="col" className="w-[52px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Cur</th>
          <th scope="col" className="px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Event</th>
          <th scope="col" className="w-[80px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Forecast</th>
          <th scope="col" className="w-[80px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Previous</th>
          <th scope="col" className="w-[176px] px-2 py-1.5 text-left text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Affects</th>
        </tr>
      </thead>
      {groups.map(group => (
        <tbody key={group.dayIso}>
          <tr>
            <th
              scope="colgroup"
              colSpan={7}
              data-testid="calendar-day-header"
              className="sticky top-[26px] z-[9] border-y border-border bg-surface-2 px-4 py-1 text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground"
            >
              <span className="flex items-center justify-between gap-2">
                <span>{formatDay(group.dayIso)}</span>
                <span className="font-normal normal-case tracking-normal">
                  {tallyText(group.tally)}
                </span>
              </span>
            </th>
          </tr>
          {group.rows.map(row => (
            <tr
              key={`${row.when_utc}-${row.currency}-${row.title}`}
              data-testid="calendar-row"
              className={cn("border-b border-border/60", row.isHeld && "bg-accent/[0.07]")}
            >
              <td className="px-2 py-1.5 font-mono tabnum text-muted-foreground">{formatTime(row.when_utc)}</td>
              <td className="px-2 py-1.5"><ImpactChip impact={row.importance} /></td>
              <td className="px-2 py-1.5 font-mono text-muted-foreground">{row.currency}</td>
              <td className="min-w-0 px-2 py-1.5">
                <span className="block truncate text-foreground" title={row.title}>
                  {row.url ? (
                    <a href={row.url} target="_blank" rel="noopener noreferrer"
                       className="underline-offset-2 hover:underline">{row.title}</a>
                  ) : row.title}
                </span>
                {row.isHeld && (
                  // The third channel. Tint + outlined chip are both colour;
                  // this is the one a colour-blind operator can still read.
                  <span className="sr-only">
                    Open position in {row.heldAffects.join(", ")}
                  </span>
                )}
              </td>
              <td className="px-2 py-1.5 font-mono tabnum text-muted-foreground">{row.forecast ?? "—"}</td>
              <td className="px-2 py-1.5 font-mono tabnum text-muted-foreground">{row.previous ?? "—"}</td>
              <td className="px-2 py-1.5"><Affects row={row} /></td>
            </tr>
          ))}
        </tbody>
      ))}
    </table>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

```bash
cd frontend && npx vitest run src/components/market/CalendarTable.test.tsx
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Prove two guards bite**

| mutation | must fail |
|---|---|
| render `row.affects` instead of `row.orderedAffects` in `Affects` | `puts a held symbol in the visible chips even when it sorted last` |
| change `+{rest} more` to `+{row.orderedAffects.length} more` | `truncates a long affects list with a remainder counter` |
| delete the `<span className="sr-only">Open position in …` block | `names the held symbol in accessible text` |

Capture FAIL, restore, capture PASS for each.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/market/CalendarTable.tsx frontend/src/components/market/CalendarTable.test.tsx
git commit -m "feat(news): day-grouped calendar table with held-first affects"
```

---

### Task 7: `CalendarExpanded` and dialog wiring

**Files:**
- Create: `frontend/src/components/market/CalendarExpanded.tsx`
- Modify: `frontend/src/sections/OverviewPage.tsx:353-360`
- Test: `frontend/src/components/market/CalendarExpanded.test.tsx`

**Interfaces:**
- Consumes: everything from Tasks 3–6.
- Produces: `<CalendarExpanded open={boolean} api={Pick<Api,"getNewsCalendar">} positions={Position[] | undefined} />`.

**The states that matter (spec §4.4):** a truncated horizon and an over-narrow filter both render a near-empty body. Both must be visibly distinct from a genuinely quiet week and from a dead feed.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CalendarExpanded } from "./CalendarExpanded";
import type { NewsCalendar, Position } from "@/lib/types";

const soon = (h: number) => new Date(Date.now() + h * 3600_000).toISOString();

const OK: NewsCalendar = {
  status: "ok", cache_age_min: 12, horizon_truncated: false,
  events: [
    { when_utc: soon(2), currency: "USD", importance: "HIGH",
      title: "Non-Farm Employment Change", forecast: "85K", previous: "57K",
      affects: ["EURUSD", "XAUUSD"] },
    { when_utc: soon(3), currency: "CHF", importance: "LOW",
      title: "SECO Consumer Climate", affects: [] },
  ],
};

const POSITIONS = [{ symbol: "XAUUSD" }] as unknown as Position[];
const apiFor = (payload: NewsCalendar) => ({ getNewsCalendar: vi.fn().mockResolvedValue(payload) });

describe("CalendarExpanded", () => {
  it("renders rows once the calendar loads", async () => {
    render(<CalendarExpanded open api={apiFor(OK)} positions={POSITIONS} />);
    await waitFor(() => expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0));
    expect(screen.getByText("Non-Farm Employment Change")).toBeInTheDocument();
  });

  it("distinguishes a filtered-to-zero result from an unavailable feed", async () => {
    render(<CalendarExpanded open api={apiFor(OK)} positions={[]} />);
    await waitFor(() => expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0));
    // Turn every impact off -> zero rows, but the feed is healthy.
    await userEvent.click(screen.getByRole("button", { name: "High" }));
    await userEvent.click(screen.getByRole("button", { name: "Med" }));
    expect(screen.getByTestId("calendar-no-match")).toBeInTheDocument();
    expect(screen.queryByTestId("calendar-unavailable")).not.toBeInTheDocument();
  });

  it("restores every row via Reset filters", async () => {
    render(<CalendarExpanded open api={apiFor(OK)} positions={[]} />);
    await waitFor(() => expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0));
    await userEvent.click(screen.getByRole("button", { name: "High" }));
    await userEvent.click(screen.getByRole("button", { name: "Med" }));
    await userEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0);
  });

  it("shows the unavailable state when the backend degrades", async () => {
    const payload: NewsCalendar = { status: "unavailable", events: [] };
    render(<CalendarExpanded open api={apiFor(payload)} positions={[]} />);
    await waitFor(() => expect(screen.getByTestId("calendar-unavailable")).toBeInTheDocument());
    expect(screen.queryByTestId("calendar-no-match")).not.toBeInTheDocument();
  });

  it("warns when the horizon is truncated", async () => {
    const payload: NewsCalendar = { ...OK, horizon_truncated: true };
    render(<CalendarExpanded open api={apiFor(payload)} positions={[]} />);
    await waitFor(() => expect(screen.getByTestId("calendar-truncated")).toBeInTheDocument());
    expect(screen.getByText(/Next week's calendar is unavailable/)).toBeInTheDocument();
  });

  it("shows no truncation warning when the horizon is whole", async () => {
    render(<CalendarExpanded open api={apiFor(OK)} positions={[]} />);
    await waitFor(() => expect(screen.getAllByTestId("calendar-row").length).toBeGreaterThan(0));
    expect(screen.queryByTestId("calendar-truncated")).not.toBeInTheDocument();
  });

  it("does not fetch while closed", async () => {
    const api = apiFor(OK);
    render(<CalendarExpanded open={false} api={api} positions={[]} />);
    await new Promise(r => setTimeout(r, 20));
    expect(api.getNewsCalendar).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd frontend && npx vitest run src/components/market/CalendarExpanded.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```tsx
import { useMemo, useState } from "react";
import { CalendarFilters } from "./CalendarFilters";
import { CalendarTable } from "./CalendarTable";
import { buildCalendarView, DEFAULT_FILTERS, type CalendarFilterState }
  from "@/lib/newsCalendar";
import { useNewsCalendar } from "@/lib/useNewsCalendar";
import type { Api } from "@/lib/api";
import type { Position } from "@/lib/types";

function EmptyState({ testId, title, hint, action }:
    { testId: string; title: string; hint: string; action?: React.ReactNode }) {
  return (
    <div data-testid={testId}
         className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
      <span className="text-sm text-muted-foreground">{title}</span>
      <span className="text-xs text-muted-foreground/70">{hint}</span>
      {action}
    </div>
  );
}

/**
 * The maximized Economic Calendar body (spec §4).
 *
 * Two of the states here exist purely because they would otherwise be
 * indistinguishable from good news: a truncated horizon and a filter that
 * matched nothing both render an almost-empty table, and "nothing is
 * scheduled" is the one conclusion an economic calendar must never invite by
 * accident.
 */
export function CalendarExpanded({ open, api, positions }: {
  open: boolean;
  api: Pick<Api, "getNewsCalendar">;
  positions?: Position[];
}) {
  const [filters, setFilters] = useState<CalendarFilterState>(DEFAULT_FILTERS);
  const { data, loading } = useNewsCalendar(api, open);

  const held = useMemo(
    () => new Set((positions ?? []).map(p => p.symbol)),
    [positions]);

  const groups = useMemo(
    () => buildCalendarView(data?.events ?? [], filters, Date.now(), held),
    [data, filters, held]);

  const unavailable = !data || data.status === "unavailable";
  const rowCount = groups.reduce((n, g) => n + g.rows.length, 0);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <CalendarFilters value={filters} onChange={setFilters} />

      {data?.status === "stale" && (
        <div data-testid="calendar-stale"
             className="border-b border-warning/40 bg-warning/10 px-4 py-1.5 text-xs text-warning">
          Calendar data is stale
          {data.cache_age_min != null ? ` (${data.cache_age_min}m old)` : ""}.
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && !data ? (
          <EmptyState testId="calendar-loading" title="Loading calendar…"
                      hint="Fetching upcoming releases." />
        ) : unavailable ? (
          <EmptyState
            testId="calendar-unavailable"
            title="Economic calendar unavailable"
            hint="No news feed is connected yet — populated once the calendar source is live." />
        ) : rowCount === 0 ? (
          <EmptyState
            testId="calendar-no-match"
            title="No events match these filters"
            hint="The feed is healthy — widen the impact levels or the date range."
            action={
              <button
                type="button"
                onClick={() => setFilters(DEFAULT_FILTERS)}
                className="mt-1 rounded-full border border-accent bg-accent/20 px-3 py-0.5 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                Reset filters
              </button>
            } />
        ) : (
          <CalendarTable groups={groups} />
        )}
      </div>

      {data?.horizon_truncated && (
        <div data-testid="calendar-truncated"
             className="border-t border-border bg-surface-1 px-4 py-2 text-xs text-warning">
          Next week&rsquo;s calendar is unavailable — showing only what this week&rsquo;s feed carries.
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Wire it into the dialog**

In `frontend/src/sections/OverviewPage.tsx`, replace the dialog body at lines 357-359:

```tsx
        <div className="min-h-0 flex-1 overflow-y-auto">
          <NewsPanel data={snapshot?.news} hideHeader />
        </div>
```

with:

```tsx
        <CalendarExpanded
          open={maximized === "news"}
          api={api}
          positions={snapshot?.positions}
        />
```

Add the import beside the existing `NewsPanel` import (line 13):

```tsx
import { CalendarExpanded } from "@/components/market/CalendarExpanded";
```

`NewsPanel` stays imported — the collapsed card at line 275 still uses it.

`api` is **already in scope**: `OverviewPage.tsx:179` destructures it —
`const { snapshot, events, connectionStatus, api } = useController();`. Add nothing.

- [ ] **Step 5: Run to verify it passes**

```bash
cd frontend && npx vitest run src/components/market/CalendarExpanded.test.tsx \
  src/sections/OverviewPage.test.tsx src/App.test.tsx && npx tsc -b
```

Expected: PASS across all three, clean typecheck. `OverviewPage.test.tsx` and `App.test.tsx` both reference `NewsPanel`; if either asserted on the *dialog's* contents it will now legitimately need updating — update the assertion to the new body, do **not** revert the wiring.

- [ ] **Step 6: Prove the state separation bites**

Mutation — collapse the two empty states into one (render `calendar-unavailable` whenever `rowCount === 0`). Expect `distinguishes a filtered-to-zero result from an unavailable feed` to FAIL. Capture, restore, capture PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/market/CalendarExpanded.tsx \
        frontend/src/components/market/CalendarExpanded.test.tsx \
        frontend/src/sections/OverviewPage.tsx
git commit -m "feat(news): expanded calendar dialog body with honest empty states"
```

---

### Task 8: Full verification

**Files:** none changed (unless a defect is found).

- [ ] **Step 1: Full frontend suite and build**

```bash
export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"
cd frontend && npx tsc -b && npm test && npm run build
```

Expected: typecheck clean, all tests pass, build succeeds. Record the test count.

- [ ] **Step 2: Full Python suite**

```bash
uptime; ps aux | grep -c '[u]nittest discover'   # confirm the box is idle FIRST
PY=/home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python
time $PY -m unittest discover -s tests/unit -p 'test_*.py'
```

Expected: OK. **This runs ~3000s (~50 min).** One deliberate run — do not loop it. A concurrent suite from another session inflates the timing and invalidates the reading, which is why the `ps` check comes first.

- [ ] **Step 3: Start the devserver on a free port**

```bash
ss -tlnp | grep -E '8770|8899|8901'   # 8901 MUST be free; 8899 is another session's
cd /home/kiyingijmc/projects/titan-news-expanded
TITAN_GUI_PORT=8901 TITAN_GUI_TOKEN=layoutcheck \
  /home/kiyingijmc/projects/Titan_ICT_Bot_v14_3pro/.venv/bin/python -m src.ops.web.devserver &
sleep 5
curl -s -H 'Authorization: Bearer layoutcheck' http://127.0.0.1:8901/api/news/calendar | head -c 400
```

- [ ] **Step 4: Drive it in a browser with injected data**

`free -g` first — headless Chromium needs a few GB. Start **one** browse daemon (`nohup bun run src/server.ts &`), wait a **fixed** interval, then measure. **Never poll `browse status` in a loop** — it spawns a daemon each time when none is healthy; doing that once drove this box to load 104.

The devserver's fake controller ships **no news manager and no positions**, so patch `window.fetch` before measuring or the table, the impact chips and the entire held-row treatment will be absent for the wrong reason:

```js
const realFetch = window.fetch;
window.fetch = async (url, init) => {
  if (String(url).includes("/api/news/calendar")) {
    return new Response(JSON.stringify({
      status: "ok", cache_age_min: 42, horizon_truncated: true,
      events: [
        { when_utc: "2026-08-14T12:30:00Z", currency: "USD", importance: "HIGH",
          title: "Non-Farm Employment Change", forecast: "85K", previous: "57K",
          affects: ["XAUUSD","EURUSD","GBPUSD","USDJPY","USDCAD","US30","US100","BTCUSD","ETHUSD","XTIUSD","AUDUSD"] },
        { when_utc: "2026-08-14T12:30:00Z", currency: "USD", importance: "HIGH",
          title: "Average Hourly Earnings m/m", forecast: "0.3%", previous: "0.3%",
          affects: ["XAUUSD","EURUSD"] },
        { when_utc: "2026-08-14T12:30:00Z", currency: "CAD", importance: "HIGH",
          title: "Employment Change", forecast: "17.8K", previous: "18.2K",
          affects: ["USDCAD"] },
        { when_utc: "2026-08-14T14:00:00Z", currency: "CAD", importance: "MEDIUM",
          title: "Ivey PMI", forecast: "55.4", previous: "56.2", affects: ["USDCAD"] },
        { when_utc: "2026-08-15T09:00:00Z", currency: "EUR", importance: "LOW",
          title: "A deliberately very long release title that must truncate rather than widen the table",
          forecast: "0.1%", previous: "0.2%", affects: ["EURUSD"] }
      ]
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  }
  return realFetch(url, init);
};
```

Then open the Economic Calendar dialog via its maximize button and measure:

| # | check | how |
|---|---|---|
| 1 | the three impact tokens resolve to **distinct** computed colours | `getComputedStyle` on each `[data-impact]`; assert 3 different values |
| 2 | the sticky day header stays fixed while the body scrolls | scroll the container, compare the header's `getBoundingClientRect().top` before/after |
| 3 | the long title truncates, not overflows | `scrollWidth > clientWidth` on the title span, and the row's width unchanged |
| 4 | the page body never scrolls horizontally | `document.body.scrollWidth <= window.innerWidth` at 1440 and 1024 |
| 5 | the three simultaneous 12:30Z rows align in Forecast/Previous | compare each cell's `getBoundingClientRect().left` — all equal |
| 6 | the truncation note is visible | `[data-testid=calendar-truncated]` is in the viewport |
| 7 | held-row treatment renders | inject a position for XAUUSD, confirm the chip is among the visible two |

Capture a screenshot. Any failure is a defect to fix, not a note to file.

- [ ] **Step 5: Confirm the live bot was never touched**

```bash
ss -tlnp | grep -E '8770|32768|32769'   # must still be pid 304062
kill %1                                  # stop the 8901 devserver
```

- [ ] **Step 6: Report**

Post: every mutation-proof pair from Tasks 1–7, the full-suite outputs from Steps 1–2, the seven browser measurements, and the screenshot. State plainly anything that did not pass.

- [ ] **Step 7: Ask about the restart**

The Python changes are inert until the bot restarts. **Ask the owner** — do not restart, and do not merge to `main`.

---

## Self-Review

**Spec coverage:**

| spec § | task |
|---|---|
| §2 / §3.1 two-week horizon, three rules | Task 1 |
| §3.1 freshness isolation | Task 1 (`FreshnessIsolation`) |
| §3.2 endpoint, memo, defensive contract | Task 2 |
| §3.3 `/api/state` untouched | Task 2 (`StateEndpointIsUnaffected`) |
| §4.1 module boundaries | Tasks 3–7 file layout |
| §4.2 table, UTC, filtered tally, truncation | Tasks 3, 6 |
| §4.3 affects, held-first, three channels | Tasks 3, 6 |
| §4.4 all five states | Task 7 |
| §4.5 filters and defaults | Tasks 3, 5 |
| §4.6 collapsed card untouched | no task modifies `NewsPanel.tsx` |
| §4.7 no row motion | no task adds animation |
| §5 colour-blind rule | Task 5 (`ImpactChip` label test) |
| §6.1–6.3 tests | Tasks 1–7 |
| §6.4 browser gate | Task 8 |
| §7 out of scope | no task prunes the store or reads `actual` |
| §8 gates | Task 8 Step 7 |

**Placeholder scan:** none — every code step carries runnable code; every mutation names the exact edit and the exact test that must fail.

**Type consistency:** `Impact`, `Horizon`, `CalendarFilterState`, `DecoratedRow`, `DayGroup`, `buildCalendarView`, `horizonEndMs`, `DEFAULT_FILTERS`, `IMPACT_ORDER`, `HORIZONS` are defined once in Task 3 and used with identical names in Tasks 5–7. `next_week_ok` (source) → `horizon_truncated` (manager, endpoint, `NewsCalendar`, `CalendarExpanded`) is consistent across Tasks 1, 2, 3, 7. `getNewsCalendar` matches between `api.ts`, `useNewsCalendar`, and every test double.

**One known follow-on:** Task 7 Step 5 may require updating existing assertions in `OverviewPage.test.tsx` / `App.test.tsx` if either asserted on the maximized dialog's old contents. That is expected and called out inline.
