# Equity time series + range selector — design

**Date:** 2026-07-31
**Status:** approved (design), pending implementation plan
**Scope:** persist an equity time series; expose it over the GUI API; add a range selector to the Overview equity panel.

---

## 1 · Problem

The Overview "Equity" panel looks like a chart of equity over time. It is not one.

`frontend/src/lib/useEquityBuffer.ts` is a 120-point buffer held in one browser's
`localStorage`. It appends only when equity changes to a distinct value, and its `t` field is a
monotonic counter, not a clock — deliberately, so tests stay deterministic.
`frontend/src/components/EquitySparkline.tsx` says so in its own docstring: *"The X axis is a
monotonic sample index and carries no meaning, so it's hidden."*

There is no server-side history to fall back on. `trade_state.db` holds `active_orders` and
`trade_history`; `titan_core.db` holds `audit_log`. `/api/history` returns closed trades.
The external audit reached the same conclusion independently (`02-AUDIT-REPORT.md` §6.7:
*"no time-series equity curve exists — only a trade-sequence one"*).

The event journal is not a substitute. `data/journal/events-*.jsonl` does record
`HeartbeatReceived` with `balance` and `equity` — roughly 5 MB across four days — but **no line
carries a timestamp**:

```json
{"balance": 1221.59, "equity": 1328.5, "n_positions": 3, "n_orders": 1, "evt": "HeartbeatReceived"}
```

`src/ops/jsonlog.py` writes the record verbatim and no caller adds a time field. The only
temporal information in the corpus is the date in the filename. Two independent history
mechanisms exist and neither records when anything happened.

**So the range selector is the small part. The feature is the time series underneath it.**

Adding timestamps to the event journal is a real defect worth fixing, but it belongs to its own
backlog row — not to this feature.

## 2 · Goals / non-goals

**Goals**

- Persist equity, balance and running-peak equity as a queryable time series that survives restarts.
- Serve any of eleven lookback ranges (15m, 30m, 1h, 4h, 12h, 1d, 1w, 1mo, 4mo, 6mo, 1y) from one endpoint.
- Render equity, balance and drawdown-from-peak on the Overview panel, defaulting to 1d.
- Never imply coverage that does not exist: ranges wider than the stored history are disabled, and
  gaps in the data render as breaks rather than straight lines.
- Accept new series later without a schema redesign.

**Non-goals**

- Backfilling history from before this ships. There is none, and none can be manufactured.
- Adding timestamps to the event journal.
- Per-strategy or per-symbol equity decomposition. The registry makes it possible later; it is not built now.
- Any change to sizing, risk gates, or the trading decision path.

## 3 · Ranges

"Timeframe" means **lookback window**, not bar size — a one-year bar would be a single point.

| Range | Seconds | Tier | Target points | Bucket |
|---|---|---|---|---|
| 15m | 900 | fine | ~90 | 10 s |
| 30m | 1 800 | fine | ~180 | 10 s |
| 1h | 3 600 | fine | ~180 | 20 s |
| 4h | 14 400 | fine | ~240 | 60 s |
| 12h | 43 200 | fine | ~240 | 180 s |
| **1d (default)** | 86 400 | coarse | ~288 | 300 s |
| 1w | 604 800 | coarse | ~224 | 2 700 s |
| 1mo | 2 592 000 | coarse | ~240 | 10 800 s |
| 4mo | 10 368 000 | coarse | ~240 | 43 200 s |
| 6mo | 15 552 000 | coarse | ~240 | 64 800 s |
| 1y | 31 536 000 | coarse | ~240 | 131 400 s |

Tier boundary: ranges ≤ 12 h read `equity_fine`, the rest read `equity_coarse`.

1d sits on the coarse tier even though the fine tier retains 48 h and could serve it. The coarse
tier already holds exactly one row per 300 s **with `equity_min`/`equity_max` preserved**, so a 1d
query reads ~288 rows instead of downsampling 8 640 — cheaper, with no fidelity lost, and it is the
default range so it runs most often.

Bucket sizes are derived (`range_seconds / target_points`), not hardcoded per range, then rounded up
to a whole multiple of the tier's storage cadence — 10 s for fine, 300 s for coarse — so a query
bucket never straddles a fraction of a stored row. That rounding is why 1w yields ~224 points rather
than 240 (2 520 s → 2 700 s); every other range divides evenly.

## 4 · Storage

New tables in `titan_core.db`, the existing ops/observability database (WAL,
`synchronous=NORMAL`, opened by `src/core/audit_logger.py:26`).

Not `trade_state.db`: the audit panel's recommendation is to move that database to
`synchronous=FULL` precisely because its write volume is tiny (~12 trades/week). Adding ~8 640
writes/day would undercut that.

```sql
CREATE TABLE equity_fine (      -- 10 s cadence, pruned at 48 h
  ts       REAL PRIMARY KEY,    -- UTC epoch seconds
  equity   REAL NOT NULL,
  balance  REAL NOT NULL,
  peak     REAL NOT NULL
);

CREATE TABLE equity_coarse (    -- 300 s buckets, retained
  bucket_ts  INTEGER PRIMARY KEY,  -- floor(ts / 300) * 300, UTC epoch seconds
  equity     REAL NOT NULL,        -- last sample in bucket
  balance    REAL NOT NULL,
  equity_min REAL NOT NULL,
  equity_max REAL NOT NULL,
  peak       REAL NOT NULL
);
```

`equity_min` / `equity_max` per bucket exist because on a six-month view one pixel covers hours.
Last-value sampling would hide the swing that actually happened.

Steady state: ~17 k rows in `equity_fine`, ~105 k rows/year in `equity_coarse`. A few megabytes.

**All timestamps are UTC epoch seconds. No naive datetimes, no local time, anywhere on this
path.** RISK-10 in the audit is a live bug in which history bars (`pd.to_datetime(unit='s')`,
UTC-naive) and live bars (`datetime.fromtimestamp()`, local) land in the same buffer three hours
apart on a UTC+3 host. This table must not reproduce it.

## 5 · Series registry (extensibility)

Columns are not hand-written. One declarative tuple in `src/ops/equity_recorder.py` is the single
source of truth for schema, rollup and query:

```python
@dataclass(frozen=True)
class Sample:                       # one accepted heartbeat, the recorder's internal unit
    ts: float                       # UTC epoch seconds
    equity: float
    balance: float
    peak: float                     # running max equity at the time of this sample

@dataclass(frozen=True)
class Series:
    name: str                       # column name in both tables
    agg: str                        # 'last' | 'min' | 'max' | 'sum' — how a bucket collapses
    source: Callable[[Sample], float]
    tier: str = "both"              # 'fine' | 'coarse' | 'both'

SERIES = (
    Series("equity",     agg="last", source=lambda s: s.equity),
    Series("balance",    agg="last", source=lambda s: s.balance),
    Series("peak",       agg="max",  source=lambda s: s.peak),
    Series("equity_min", agg="min",  source=lambda s: s.equity, tier="coarse"),
    Series("equity_max", agg="max",  source=lambda s: s.equity, tier="coarse"),
)
```

Adding `margin_level`, `open_pnl`, `day_pnl` or `exposure_pct` later is one tuple entry. On boot
the schema guard reads `PRAGMA table_info` and `ALTER TABLE … ADD COLUMN`s anything registered but
absent — the same migration pattern `src/core/state_manager.py:95-115` already uses. Rollup SQL is
generated from each series' `agg`. `equity_min`/`equity_max` are ordinary registry entries, not
special cases.

Rows written before a series was registered carry `NULL`. The API reports **per-series** coverage
so a chart never draws a line implying a series existed before it was recorded.

Schema versioning uses `PRAGMA user_version`, so migrations are ordered and detectable rather than
inferred by sniffing column lists.

## 6 · Recorder

`src/ops/equity_recorder.py`, one class, owning its own connection.

**Feed point:** `src/core/system_controller.py:713`, in the `HEARTBEAT` branch of
`_process_incoming_data`, immediately after `self._publish(HeartbeatReceived(...))`. `bal` and `eq`
are already parsed there and the `if eq > 0` guard already exists. One added call:
`self.equity_recorder.record(bal, eq)`.

**Write discipline**

- `record()` gates on a 10 s monotonic interval; heartbeats arriving faster are ignored, not queued.
- Samples accumulate in a bounded in-memory list and flush every ~60 s worth. A stalled database
  drops the oldest and increments a counter rather than growing without limit.
- The flush upserts affected `equity_coarse` buckets in the same transaction, so the coarse tier is
  maintained inline. No separate rollup job.
- Upserts use `ON CONFLICT(bucket_ts) DO UPDATE SET` naming every column explicitly. Never
  `INSERT OR REPLACE` — audit OBS-03 is exactly the bug where that silently zeroes columns the
  caller did not pass.
- `record()` and `flush()` never raise into the trading loop. Same contract as
  `src/ops/jsonlog.py:32` (`except Exception: self.drops += 1`).

**Rejection rules — each drops the sample and increments a named counter**

- `ts <= last_ts` (clock step, NTP correction, replay). Audit EXEC-06 is an out-of-order-sample
  corruption with no guard, no counter and no log; this is that lesson applied.
- `equity` or `balance` non-finite, or `<= 0`. Same fail-closed posture as the SEC-05 spec bounds.

**Counters are surfaced** in the `/api/state` health block as
`equity_recorder: {dropped_stale, dropped_invalid, dropped_overflow, dropped_db}`. Audit OBS-02
caught that `jsonlog._Writer.drops` is incremented and read by nothing; a silent-loss counter
nobody reads is not an observability mechanism.

**Peak** is a running max of equity, persisted per row so drawdown is computable from any row
without a scan. On boot it is seeded from `MAX(peak)` in `equity_coarse`, so drawdown-from-peak
survives restarts — which `risk_manager.equity_max` currently does not.

**Prune:** `DELETE FROM equity_fine WHERE ts < now - fine_retention_s`, run on the existing 60 s
reconciliation timer in `run()`.

**Config** under `gui.equity` in `config/config.yaml`, not constants:
`fine_cadence_s: 10`, `fine_retention_h: 48`, `coarse_bucket_s: 300`, `flush_interval_s: 60`,
`max_buffer_samples: 600`.

## 7 · API

`GET /api/equity?range=1d` — read dependency, alongside `/api/history` in
`src/ops/web/server.py`. Unknown or missing `range` → `1d`. Invalid → 422.

```json
{
  "range": "1d",
  "tier": "coarse",
  "bucket_s": 300,
  "series": ["equity", "balance", "peak"],
  "points": [
    {"ts": 1753900000, "equity": 1327.0, "balance": 1221.59, "peak": 1340.2},
    null,
    {"ts": 1753900600, "equity": 1329.4, "balance": 1221.59, "peak": 1340.2}
  ],
  "coverage": {
    "first_sample_ts": 1753600000,
    "n": 288,
    "series_first_ts": {"equity": 1753600000, "balance": 1753600000, "peak": 1753600000},
    "gaps": [[1753900100, 1753900590]]
  }
}
```

- A `null` entry is a gap: consecutive stored samples more than `2 × bucket_s` apart. **Gaps are
  never interpolated.** There was a ~9-hour outage on 2026-07-29; a line drawn straight across it
  would claim the account was flat and healthy through a period when the bot was dead.
- `coverage.first_sample_ts` drives range enablement. The frontend enables a range when
  `now - first_sample_ts >= range_seconds`.
- Downsampling happens in SQL using each series' declared `agg`, so the response is bounded at
  ~240 points regardless of range.

Query cost is bounded by the coarse tier's size and runs on the controller's event loop, like
`/api/history` does today. At ~105 k rows/year against an indexed primary key this is sub-millisecond;
it is noted here because the audit flags loop-blocking queries as a class (EXEC-02).

## 8 · Frontend

`RangeSelector` above the chart; `useEquitySeries(range)` fetches on change and on a slow poll;
`EquitySparkline` gains a real time X axis and multiple lines. `useEquityBuffer` survives as the
live tail: incoming WS equity appends to the right edge of the 15m–1d ranges so the panel still
feels live between polls. Its docstring is corrected — the X axis now carries meaning.

Drawdown is derived client-side as `equity - peak` (≤ 0), rendered as a muted area beneath the
lines rather than a third competing stroke.

`fake_controller.py` grows a synthetic generated series so `devserver.py` can drive all eleven
ranges, including gaps and thin-coverage states, with MT5 offline.

### 8.1 Motion

Per Emil Kowalski's framework, the governing question is how often a user sees an animation:

- **The chart does not animate.** A functional graph in a trading app is the canonical case where no
  animation beats animation. `isAnimationActive={false}` on every Recharts series. The existing
  `EquitySparkline` docstring already commits to "no entrance animation" — this preserves that.
- **Range switching does not animate the data.** It is a several-times-a-minute action; a crossfade
  between two datasets reads as two overlapping objects, and re-animating a chart the user is
  actively scanning makes the interface feel slower. The new data replaces the old immediately.
- **In-flight fetches** dip the chart to `opacity: 0.6` over `--motion-fast` (150 ms). Opacity only —
  no motion, no skeleton swap, no layout shift.
- **The active-range indicator** is the one thing that moves: a pill that slides between options,
  `transform` + `opacity` only, `--motion-fast` with `--ease-out`.
- **Press feedback**: `transform: scale(0.97)` on `:active`, 160 ms, `--ease-out`. The selector is a
  pressable control and must feel like it heard the click.
- **Disabled ranges** (4mo/6mo/1y until coverage exists) carry a tooltip — *"unlocks 28 Nov 2026"* —
  with the standard delay, and no delay on adjacent tooltips once one is open. Hover styling is gated
  behind `@media (hover: hover) and (pointer: fine)` so a tap on a touch device does not trigger it.
- **Keyboard range switching** (`[` / `]`, or ⌘K actions) is instant, with no pill transition.
  Keyboard-initiated actions are repeated and must never feel delayed.
- Transitions, not keyframes, so a rapid sequence of range clicks retargets smoothly instead of
  restarting.
- Only `transform` and `opacity` are animated.

`prefers-reduced-motion` is already handled globally in `frontend/src/index.css:20`; the pill
transition must be covered by it.

One token is added: `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)` alongside the existing
`--motion-fast`, `--motion-base` and `--ease` in `frontend/src/design/tokens.css:34`. **It must be
bound to a rule in the same change.** A previous motion-token effort on this codebase defined
tokens that were bound to nothing; a token no rule references is not a design system, it is dead CSS.

## 9 · Testing

**Python**

- Schema created from the registry; a newly registered series triggers `ALTER TABLE` on both tables
  and old rows read back `NULL`.
- `PRAGMA user_version` set and respected on re-open.
- Cadence gate: heartbeats faster than `fine_cadence_s` produce one row.
- Rejection: `ts <= last_ts`, non-finite, `<= 0` — each drops, counts, and writes nothing.
- Buffer cap: overflow drops oldest and counts.
- Rollup: each `agg` collapses a bucket correctly (`last`, `min`, `max`).
- Upsert: re-flushing an existing bucket updates only the named columns; no column is zeroed.
- Prune boundary: a row exactly at `now - retention` is kept, one second older is deleted.
- `record()` swallows a DB error, counts it, and the caller is unaffected.
- Peak seeding: recorder restarts and resumes from the stored max.
- API: tier selection per range, point count bounded, gap detection at `2 × bucket_s`, coverage
  fields, unknown range → 1d, invalid range → 422.

**Frontend**

- Eleven ranges render; `1d` is the default.
- Ranges wider than `coverage.first_sample_ts` are disabled and carry the unlock tooltip.
- A `null` point renders a break, not a connecting line.
- The live WS tail appends to short ranges but not to `1mo+`.
- Chart series have `isAnimationActive={false}`.
- Reduced-motion disables the pill transition.

**Verification:** `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` and
`npm test` in `frontend/`, both green.

## 10 · Risks

| Risk | Mitigation |
|---|---|
| Another write path on the trading event loop | 10 s cadence, batched 60 s flush, never raises; measured against the existing per-signal SQLite commit which is far hotter |
| `titan_core.db` growth | Fine tier pruned at 48 h; coarse tier ~105 k rows/year; both bounded and configurable |
| Long ranges empty for months | Ranges disable themselves until covered; unlock date shown |
| A future series added mid-flight | `NULL` for older rows plus per-series coverage; chart draws from that series' first sample only |
| Data loss on kill | Up to `flush_interval_s` of samples. Accepted: there is no shutdown handler anywhere in `src/` (audit §5.8), and this is telemetry, not position state |

## 11 · Suggested decomposition

This spec spans a recorder, an API and a UI. Under the mig one-task-per-session rule it should land
as two chained sessions rather than one:

1. **`equity-timeseries-recorder-and-api`** — §4–§7. The registry, both tables, the recorder wired
   into the `HEARTBEAT` branch, prune, counters on `/api/state`, and `GET /api/equity`. Verifiable
   entirely by the Python suite; ships without any visible change.
2. **`equity-range-selector-ui`** — §8. Selector, `useEquitySeries`, time axis, multi-series chart,
   gap rendering, coverage-driven disabling, motion. Needs (1) merged, and drives against
   `fake_controller` so it is testable with MT5 offline.

Splitting this way keeps the risky half — a new write path on the trading event loop — in a session
whose review can focus on it, instead of burying it in a diff that is mostly React.

## 12 · Out of scope, tracked elsewhere

- Event-journal timestamps (`src/ops/jsonlog.py`) — own backlog row.
- `synchronous=FULL` on `trade_state.db` — audit recommendation, unrelated to this change.
- Reading `peak` into an actual drawdown *limit*. The audit notes `equity_max` is tracked and never
  read by any control. This spec makes drawdown visible; enforcing it is a risk change, not a GUI one.
