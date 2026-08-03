---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S018"
date:          "2026-07-31"
slug:          "risk-10-live-bars-and-history"
parent_session: "none"
task_domain:   "data"
spec_state:    "approved"
status:        "DRAFT"
---

# titan-ict-bot — Session S018 · 2026-07-31 · "risk-10-live-bars-and-history"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Stamp live bars in the same epoch as history bars (naive UTC), so one buffer stops holding two clocks

**Why it matters / what it unblocks:** The two bar sources disagree about what a broker epoch means, and they share one buffer. `src/core/data_store.py:79` converts history with `pd.to_datetime(df['time'], unit='s')` → **naive UTC**; `src/core/candle_maker.py:112-115` converts live ticks with `datetime.fromtimestamp(raw_time)` → **naive LOCAL time** (this host is Africa/Kampala, UTC+3). `src/core/data_store.py:92` then assigns the history frame straight onto the maker's buffer (`self.timeframes[tf].candles = df`), and live bars are appended to that same frame — so after every warmup the series carries a phantom ~3h discontinuity at the history/live seam, and the same instant is labelled two different ways depending on where the bar came from. Every strategy, indicator and journal row downstream reads that series. This is the second instance of the same naive-datetime root cause in this codebase (the news blackout was also exactly 3h off and went unnoticed for three days), which is why it is worth fixing properly rather than patching one call site.

**Exact scope (what "doing this task" means):**
- `src/core/candle_maker.py:112-115`: convert the broker epoch to **naive UTC** so it matches `pd.to_datetime(..., unit='s')` exactly — i.e. `datetime.fromtimestamp(x, tz=timezone.utc).replace(tzinfo=None)`. **Both** branches must change: the millisecond branch (`raw_time > 32503680000` → `/1000.0`) and the seconds branch. Bucket flooring, OHLCV logic and the duplicate filter keep their current behaviour; only the epoch interpretation changes.
- Sweep the rest of this data path for the same defect and fix any instance **inside these two files only**: `grep -n 'fromtimestamp\|utcnow\|datetime.now' src/core/candle_maker.py src/core/data_store.py`. Report what you found even if the answer is "nothing else".
- New test file `tests/unit/test_candle_time_epoch.py` (there is currently **no** unit coverage for `candle_maker.py` or `data_store.py` at all — confirm that before writing, and do not assume an existing harness). It must cover:
  1. **Cross-path agreement:** one fixed epoch fed through `DataStore.ingest_history` and through `CandleMaker.process_tick` yields the **same** timestamp.
  2. **Seam contiguity:** ingest history, then drive a tick belonging to the very next bucket; the gap between the last history bar and the first live bar must be exactly one timeframe interval — not one interval plus the local UTC offset.
  3. **Millisecond branch parity:** an epoch expressed in ms and the same instant in s produce the same timestamp.
  4. **Timezone independence (REQUIRED — this is what makes the test bite):** force a non-UTC zone for the duration of the test (e.g. `TZ=Africa/Kampala` via `os.environ` + `time.tzset()`, restored afterwards) and assert the results are unchanged from UTC. **Without this the test passes on a UTC machine even with the bug fully present**, because local and UTC coincide there — so a suite that is green in one environment would be meaningless in another.

**Explicitly OUT of scope (do NOT touch this session):**
- `src/ops/news_manager.py` and anything calendar/blackout related. It is the *sibling* instance of this root cause and it already has its own committed design spec (`docs/superpowers/specs/2026-07-31-news-calendar-dashboard-design.md`, commit `0fe8564`) and its own planned session. Fixing it here would collide with that work.
- `src/analysis/time_math.py`, the time engine, `ny_time`, and killzone/session-window semantics. Note for the record: the SilverBullet window gate reads `self.time_engine.get_current_ny_string()` (`src/core/system_controller.py:848`), **not** the bar timestamp — so this defect does not move the killzone, and this session must not "improve" that path.
- `config/config.yaml` `connection.broker.timezone_offset` and any change to what timezone the system *presents* to the operator.
- How timestamps are displayed anywhere (GUI, Telegram, journal formatting), and any migration/backfill of already-written journal or DB rows.
- The research/replay stack (`src/research/`), unless a test there goes red — in which case STOP and report rather than adapting it.

**Relevant project docs / decisions:** `CLAUDE.md` (bridge message flow: `HISTORY` bars vs `TICK`); `docs/audit-2026-07-30/` RISK-10 (§3 Risk) and my `07-VERIFICATION-AGAINST-LIVE-TREE.md`; the news-calendar design spec above as the explicitly-excluded sibling.

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] Premise re-confirmed in the live tree with file:line for **both** conversion sites and for the `data_store.py:92` assignment that makes them share one buffer.
- [ ] Live and history bars for the same broker epoch produce identical timestamps, in both the seconds and milliseconds branches.
- [ ] The new test **fails before the fix and passes after it**; quote the exact pre-fix failure output in the session report. A test that was never seen red is not evidence.
- [ ] The timezone-independence case is present and genuinely forces a non-UTC zone; state in the report what the test does on a UTC-only machine and why it still bites.
- [ ] The history→live seam shows exactly one timeframe interval, with no offset jump.
- [ ] Full unit suite green: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`. If it reports rc=124 or timing-flavoured failures, check `uptime` and `ps -eo args | grep '[u]nittest discover'` first — concurrent suites from other sessions have repeatedly manufactured false failures on this box.
- [ ] The report states the **operational consequence explicitly**: whether a running bot picks this up automatically or only re-stamps its buffer at the next restart + warmup, so the operator knows if a restart is required for the fix to take effect on the live demo-forward test.
- [ ] The report states whether any already-recorded data (journal rows, DB timestamps, the forward-test record since 2026-07-28) is affected, and recommends — without performing — any correction needed at the 2026-08-11 checkpoint.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
