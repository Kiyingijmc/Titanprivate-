# News Calendar: robust sourcing, per-symbol blocking, dashboard + digest

- **Date:** 2026-07-31
- **Status:** Approved (design), pending decomposition into mig sessions
- **Owner decisions captured:** ForexFactory is the PRIMARY source; MT5 calendar is a
  FALLBACK only. Only red-folder (High) events halt trading. A feed outage must not
  halt the book. News must be visible on the dashboard and summarised to Telegram.

---

## 0. Motivating defect (found during design, live on the forward test)

`src/analysis/news_manager.py` parses ForexFactory event times into a **naive**
`datetime` (line 138) and compares them against `datetime.now()` — **local** time
(line 169). The host runs `Africa/Kampala` (UTC+3); the ForexFactory CSV is in **UTC**.

CSV timezone was confirmed against three known release times:

| Event | CSV | Known release | Implies |
|---|---|---|---|
| Federal Funds Rate / FOMC Statement | 6:00pm | 14:00 ET = 18:00 UTC | UTC |
| FOMC Press Conference | 6:30pm | 14:30 ET = 18:30 UTC | UTC |
| Advance GDP q/q, Core PCE m/m | 12:30pm | 08:30 ET = 12:30 UTC | UTC |

**Consequence:** every blackout window fires exactly 3 hours early, and the real
release is unprotected. On 2026-07-30 the bot blocked 11:30–13:30 EAT and then traded
through the actual 12:30 UTC (15:30 EAT) Core PCE release. Live since 2026-07-28.

This defect alone justifies the work. It is fixed in Session 1 (or sooner as a hotfix,
at the owner's discretion).

Two secondary findings from the same investigation:

- The CSV header is `Title,Country,Date,Time,Impact,Forecast,Previous,URL`. The current
  parser keeps only `Title` and time, **discarding Forecast, Previous and URL**. A rich
  digest therefore needs no MT5 data at all — only post-release `Actual` is unavailable
  from ForexFactory.
- The weekly file carries ~92 events across all currencies and impact tiers; the current
  `Impact == High and Country == USD` filter discards roughly 90% of it.

---

## 1. Goals / Non-goals

**Goals**

1. A feed outage must never halt trading while the calendar is still known.
2. Only High ("red folder") events may halt trading.
3. Blocking must match event currency to the traded symbol.
4. News must be visible on the dashboard (currently it is absent from the GUI payload
   entirely — it only gates trading, invisibly).
5. A summarised Telegram digest, ranked by relevance to the traded pairs.

**Non-goals (explicitly declined by the owner)**

- Using actual-vs-forecast *surprise* to drive trading decisions. Blocking stays a
  simple time-window rule around red-folder events.
- Per-event tunable blackout windows. One pre/post window pair for all events.

---

## 2. Architecture

`news_manager.py` currently performs four jobs in one 185-line class: HTTP fetching,
CSV parsing, blocking policy, and (absent) caching. Each goal above needs a different
one of those to vary independently, so the module is replaced by a package:

```
src/analysis/news/
  models.py    CalendarEvent   — the contract every other unit speaks
  sources/
    forexfactory.py            — PRIMARY. Today's HTTP logic, relocated.
    mt5_calendar.py            — FALLBACK ONLY. Fed by a ZMQ CALENDAR message.
  store.py     CalendarStore   — disk cache, cross-source merge, staleness
  policy.py    NewsPolicy      — pure: (events, symbol, now) -> (blocked, reason)
  manager.py   NewsManager     — thin façade; controller changes stay minimal
```

### 2.1 `CalendarEvent` (models.py)

Frozen dataclass. The single boundary contract.

| Field | Type | Notes |
|---|---|---|
| `key` | `str` | Stable identity for dedup/merge: hash of `currency` + normalised `title` + `when_utc` rounded to 5 min |
| `when_utc` | `datetime` | **Always timezone-aware UTC.** Non-negotiable |
| `currency` | `str` | ISO code, e.g. `USD` |
| `importance` | `Literal["HIGH","MEDIUM","LOW"]` | Only `HIGH` may block |
| `title` | `str` | |
| `forecast` / `previous` / `actual` | `str \| None` | `actual` only ever populated by the MT5 fallback |
| `url` | `str \| None` | From the CSV; used for dashboard links |
| `source` | `str` | `forexfactory` or `mt5` |

Constructing `when_utc` as tz-aware at the source boundary is what permanently kills the
timezone bug class in §0. No naive datetime may exist inside the package.

### 2.2 Sources

Both implement `fetch() -> list[CalendarEvent]`.

- **`ForexFactoryCsvSource` (primary).** Retains the existing User-Agent rotation, retry
  loop and exponential backoff. Adds: explicit `csv_timezone` handling (default `UTC`,
  configurable), and extraction of `Forecast` / `Previous` / `URL`. Impact string maps
  `High -> HIGH`, `Medium -> MEDIUM`, `Low -> LOW`; `Holiday`/unknown -> `LOW`.
- **`Mt5CalendarSource` (fallback only).** Not polled while ForexFactory is healthy.
  Reads events delivered by the EA over ZMQ. Its `HIGH` importance is treated as
  equivalent to red folder, so failover does not silently change blocking behaviour.

### 2.3 `CalendarStore` — the robustness core

Persists the week to `data/news/calendar.json` via atomic write (temp file + `rename`).
Merges by `key`. **ForexFactory always wins on `importance` and `when_utc`**; MT5 may
only contribute fields ForexFactory left empty (in practice, `actual`). This preserves
"ForexFactory is authoritative" even when both have supplied data.

Note the consequence of MT5 being a strict fallback (§2.2): because it is not polled
while ForexFactory is healthy, `actual` values will normally be **absent**. They appear
only for events that occur during a ForexFactory outage. This is an accepted trade-off —
the dashboard and digest are built on `forecast`/`previous`, which ForexFactory supplies
directly, so neither depends on `actual` being present.

Tracks `last_success_utc` per source and exposes `age()`, `events_between(t0, t1)`.

Because one fetch returns the whole week, an outage is not blinding: Thursday's NFP is
already known on Monday. This is the design change that converts "retry harder" into
"the network is not on the critical path".

### 2.4 Failure ladder

| Condition | Behaviour |
|---|---|
| ForexFactory reachable | Normal. Cache refreshed. |
| ForexFactory down, cache fresh | **Trading continues.** Blackouts enforced from cache. Telegram warning only. |
| ForexFactory down, MT5 available | MT5 supplies events. `HIGH` maps to red folder. |
| Both unavailable AND cache older than `max_cache_age_hours` | Fail closed globally + Telegram naming the reason. |

`max_cache_age_hours` defaults to **48**: short enough that a stale cache cannot span a
weekend into a new trading week, long enough that a multi-hour outage is a non-event.

### 2.5 `NewsPolicy` — pure

No I/O, no ambient clock; `now` is passed in. This is what makes code that can stop the
book actually testable — the existing module has **zero tests**.

Responsibilities: the symbol→currency map, the HIGH-only rule, the pre/post windows, and
the staleness verdict.

---

## 3. Configuration

```yaml
news:
  enabled: true
  csv_timezone: "UTC"            # verified 2026-07-31; see §0
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

An unmapped symbol infers ISO codes from its name, defaulting to `[USD]` with a one-time
warning — never to an empty list, which would fail **open**.

### 3.1 The GBPJPY correctness case

`GBPJPY` contains no USD. Today a US CPI print blocks it (irrelevant) while a BOE rate
decision or BOJ intervention does not (highly relevant) — filtered on exactly the wrong
axis. The regression test asserting the inversion is the proof-of-fix for §4.

---

## 4. Controller integration

Today, [`_check_news_status`](../../../src/core/system_controller.py) is a **global**
gate: it flips the whole bot to `BotState.PAUSED`. A single global flag cannot express
"GBPJPY is blocked but US100 is fine", so per-symbol matching is meaningless without
this change.

**Decision:** news gates **per symbol at signal time**. `BotState.PAUSED` is reserved for
the one genuinely global condition — a cache too stale to trust.

`NewsManager` keeps a façade close to today's shape (`update()`,
`check_symbol(symbol) -> (bool, reason)`, `is_globally_blocked()`, `snapshot()`) so
controller churn stays small.

**Risk:** this touches the live trading path. This repo has repeatedly shipped defects
that a green suite did not catch (S004, S013), so Session 1 requires mutation-style
scrutiny, not just a passing run.

---

## 5. Dashboard

An **additive, degrading** `news` block in `state_view.build_snapshot`, following the
existing `_dollar_block` precedent (`state_view.py:41`) — a news fault must never break
the GUI payload.

```json
"news": {
  "status": "ok",
  "cache_age_min": 12,
  "sources": {"forexfactory": "ok", "mt5": "idle"},
  "next": {"in_min": 47, "title": "Core CPI m/m", "currency": "USD",
           "importance": "HIGH", "forecast": "0.3%", "previous": "0.2%",
           "affects": ["EURUSD", "XAUUSD", "US100"]},
  "blocked_symbols": {"GBPJPY": "BOE Rate Decision in 22m"},
  "today": []
}
```

`status` degrades to `"unavailable"` on any internal error.

**Panel:** a compact card — next-event countdown, affected pairs as chips, a "today"
strip — plus a block badge on affected rows in Positions. "Summarised" means: grouped by
currency, deduped, ranked by whether the event touches a traded pair, and silent when
nothing is red.

---

## 6. Telegram digest

Two messages via the existing `telemetry.py`:

1. **Morning digest** — the day's red-folder events grouped by currency, each with its
   affected pairs, forecast and previous.
2. **T-15m alert** — a one-line heads-up per red-folder event.

If a day has no red-folder events, send one line saying so. Silence is indistinguishable
from a broken job.

---

## 7. Testing

Stdlib `unittest`, per repo convention. The current module has no tests at all.

- **Timezone (the §0 regression):** frozen CSV fixture; assert a `6:00pm` FOMC row
  resolves to `18:00Z`, and that the blackout is active at 17:30Z and inactive at 14:30Z.
  This test must fail against the current implementation.
- **Currency matching:** a USD event must **not** block `GBPJPY`; a GBP or JPY event must.
- **HIGH-only:** MEDIUM/LOW events never block, at any window offset.
- **Store:** merge precedence (ForexFactory wins importance), atomic write survives a
  simulated crash, `age()` correctness.
- **Failure ladder:** source down + fresh cache still enforces blackouts and does **not**
  halt; source down + stale cache halts globally.
- **Snapshot:** `news` block degrades to `unavailable` when the manager raises.

---

## 8. Sequencing

Three chained sessions. **Nothing touches the EA until the probe proves it worthwhile.**

1. **`news-source-layer-cache-and-policy`** — the package, the timezone fix, per-symbol
   gating, full test suite. Delivers goals 1–3. No EA work.
2. **`news-on-dashboard-and-telegram-digest`** — snapshot block, GUI panel, digest.
   Delivers goals 4–5. No EA work.
3. **`mt5-calendar-fallback`** — a throwaway `Calendar_Probe.mq5` first; only if FBS
   actually serves calendar data do we add a `CALENDAR` message to `Titan_Gateway.mq5`
   and the fallback source.

Sessions 1 and 2 deliver every owner-selected goal with zero Windows work and zero risk
to the live EA. Session 3 is purely redundancy plus `actual` values.

---

## 9. Open risks

- **Session 1 touches the live trading path.** See §4.
- **FBS may not serve the MT5 calendar.** Some brokers disable it. The probe is the cheap
  way to find out; a negative result ends Session 3 with nothing wasted.
- **The EA recompile is manual** (MetaEditor on Windows) and briefly interrupts the live
  forward test. Session 3 only.
- **ForexFactory remains a scraped, unofficial endpoint.** The disk cache reduces it from
  a trading-halt dependency to a freshness concern, but it is still a third party that
  can change its schema. The existing schema-validation guard is retained.
