# Fill-model correction — re-baselining SilverBullet v14.4.2

**Date:** 2026-07-30
**Branch:** `feat/fill-model-correction`
**Spec:** `docs/superpowers/specs/2026-07-29-passive-entry-layer-design.md` §6.1
**Plan:** `docs/superpowers/plans/2026-07-30-passive-entry-s1-fill-model.md` (session 1 of 4)

**Question:** does the adopted `+0.19R/trade, PF 1.53` survive a correct BUY-LIMIT fill trigger?

> **Status: run set fixed, measurement pending.** Sections 1-3 were written *before* any
> number was produced, so the denominator could not be chosen to flatter the result. Sections
> 4-6 are filled from the runs.

---

## 1 · What changed in the model

Four corrections, all offline. No `src/` live-trading file was touched.

| # | Change | Commit |
|---|---|---|
| 1 | `resolve_trade`'s LIMIT fill became **direction-aware**. It tested `low <= entry <= high` on BID OHLC, direction-blind. MT5 triggers BUY orders on **ASK** (`= bid + spread`), so a BUY LIMIT needs bid to reach `entry - spread`; a SELL LIMIT triggers at `bid >= entry` with no haircut. | `151188b` |
| 2 | Same fix corrected **gapped-through limits**. The old range test required `entry` to sit *inside* the bar, so a bar that gapped entirely past the limit wrongly expired instead of filling. | `151188b` |
| 3 | **STOP orders** now resolve with stop semantics. Any non-`MARKET` cmd was previously resolved as a LIMIT, inverting the trigger. `Intent.kind` already admits `"STOP"` and the EA already places them. | `143bb93` |
| 4 | The per-signal spread now **reaches** `resolve_trade`. Until this landed, corrections 1-3 were **inert on the study path** — `_signals_to_trades` never stamped a spread, so the resolver saw `0.0`. | `90ec8b1` |

**The cost model is deliberately unchanged.** In bid-space OHLC accounting every trade pays
exactly one spread regardless of entry type: a long market entry buys at `ask = B + s` while
SL/TP resolve against bid; a long limit at `P` fills at `ask = P`, i.e. when `bid = P - s`, so
its bid-space entry is `s` worse than nominal; a short sells at bid and buys back at ask.
`spread_cost = spread_points * tick_value * lots` already charges exactly that. Adding an
entry-leg charge would double-count the same `s` the corrected trigger accounts for.
**Only the trigger side moved.**

### Why this had to be fixed before any passive-entry study

The old model filled buy limits one whole spread too easily — precisely the marginal region a
passive-entry policy operates in. Any "resting orders beat the spread" result measured on it
would have been partly self-confirming. That is the reason this session exists, and the reason
it runs *before* the layer is built.

---

## 2 · Run set (fixed before measurement)

Probe: a symbol runs only if it resolves a spread assumption, a broker tick spec, and has an
M5 history CSV.

| symbol | spread | tick spec source | csv | verdict |
|---|---|---|---|---|
| EURUSD | ✓ | `data/specs.json` | ✓ | **RUN** |
| GBPUSD | ✓ | `data/specs.json` | ✓ | **RUN** |
| USDJPY | ✓ | `data/specs.json` | ✓ | **RUN** |
| AUDUSD | ✓ | `data/specs.json` | ✓ | **RUN** |
| USDCAD | ✓ | `data/specs.json` | ✓ | **RUN** |
| GBPJPY | ✓ | `data/specs.json` | ✓ | **RUN** |
| XAUUSD | ✓ | `data/specs.json` | ✓ | **RUN** |
| US30 | ✓ | `data/specs.json` | ✓ | **RUN** |
| BTCUSD | ✓ | `data/specs.json` | ✓ | **RUN** |
| US100 | ✓ | `costs.RESEARCH_TICK_SPECS` | ✓ | **RUN** |
| ETHUSD | ✓ | `costs.RESEARCH_TICK_SPECS` | ✓ | **RUN** |
| **XTIUSD** | ✓ | **NONE** | ✓ | **SKIP** |

**RUN = 11 of the 12 live pairs. SKIP = XTIUSD.**

### Why XTIUSD is excluded

Its spread is well corroborated (2 points, re-measured 2026-07-29 during the London/NY overlap,
n=20, zero variance). Its **tick specs are not**: `data/results/universe_screen_20260728/candidate_probe.json["XTIUSD"]`
is `null` — it was adopted after that probe run — so `tick_value` has never been read from the
broker. The screen harness carries a hand-entered `tick_value = 10.0`; checking that in would
launder a guess into a measurement, and `tick_value` is the sizing denominator, so an error
there scales net R directly.

**This does not affect live trading.** XTIUSD gets its specs from the `HISTORY` message at
runtime. The gap is research-only. **Unblock:** run `scripts/cache_specs.py` against a live
Windows MT5 bridge, then re-run this study with 12 pairs.

**Consequence for comparability:** the pooled figure below covers 11 symbols. The adopted
`+0.19R` was itself a 9-symbol pooled figure (`docs/research/2026-07-11-silverbullet-h1-stop-study.md`),
so neither the old nor the new number is a 12-pair result, and the honest comparison is
arm-vs-arm on the **same 11 symbols**, not new-vs-published.

---

## 3 · Method

Both arms run through the identical pipeline — same data, same costs, same concurrency, same
grader — differing **only** in `tests/backtest/backtest_engine.py::resolve_trade`:

- **Baseline arm:** that file as of `5b067a1` (pre-Task-2), i.e. the direction-blind
  `low <= entry <= high` touch test. The signal dicts still carry a `spread` key; the old
  resolver simply ignores it, so the arms differ in fill logic alone and not in cost.
- **Corrected arm:** current `HEAD`.

Runner: `scripts/research_run.py --csv data/history/<SYM>_M5.csv --symbol <SYM> --tf H1
--strategy silver_bullet --spread-pips <FBS_SPREAD_TICKS[SYM]>`, which drives the **live**
`SystemController` kernel (real FeatureBus, Arbiter, SignalGrader) and resolves trades with the
validated backtest math.

Attribution: corrections 1 and 2 land in the same commit, so a symbol is additionally run at
`--spread-pips 0` on the corrected engine. That arm isolates the **gap-fill** change (which is
spread-independent) from the **spread-haircut** change. Without it the two are confounded and
the headline delta is uninterpretable.

---

## 4 · Results — EURUSD

EURUSD only. It is the reproduction anchor the universe screen used, and the runs are
expensive (~80 min each; 18,631 H1 bars driven through the live kernel bar-by-bar). Scope
decision recorded in §7.

All three arms: 388 signals, 18,631 bars, same data, same costs, same grader.

| arm | engine | spread | trades | IS n | IS exp | IS PF | OOS n | OOS exp | OOS PF | expired |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | pre-fix (`5b067a1`) | 8t | 143 | 99 | **+0.0779** | 1.118 | 44 | −0.0523 | 0.926 | 111 |
| attrib0 | corrected | 0t | 143 | 99 | +0.1171 | 1.184 | 44 | −0.0123 | 0.982 | 111 |
| corrected | corrected | 8t | 140 | 96 | **−0.0111** | 0.984 | 44 | −0.0523 | 0.926 | 114 |

### 4.1 The gap-fill correction did nothing on EURUSD

`attrib0` and `baseline` produce **identical trade counts** (143; 99 IS / 44 OOS; 111 expired).
At zero spread the corrected engine fills exactly where the pre-fix engine did, so in three
years of EURUSD H1 **no bar ever gapped fully past a resting limit**. The gapped-limit fix
(correction 2) is real but inert on this symbol. Whether it bites on the gap-prone symbols —
BTCUSD, ETHUSD, the indices over weekend breaks — is untested.

That isolation is the one thing the `attrib0` arm establishes cleanly. **It does not isolate
what it was designed to isolate** — see §7.

### 4.2 The whole delta is the BUY-LIMIT spread haircut

With the gap-fill change accounted for as nil, the entire baseline→corrected difference is
correction 1. Its effect on EURUSD:

- **3 of 143 trades stop filling.** Buy limits whose bid touched the entry but whose *ask*
  never reached it. Expired rises 111 → 114.
- **In-sample expectancy: +0.0779R → −0.0111R** (−0.089R), and **PF 1.118 → 0.984** — across
  the break-even line.
- **Out-of-sample is unchanged** (−0.0523R, PF 0.926). All three phantom fills were in-sample.

Three trades in 143 — 2% of the sample — were enough to flip the in-sample sign. That is the
signature of a thin edge: the result was never robust to a one-spread change in fill
eligibility. The phantom fills were disproportionately *winners*, which is exactly what the
adverse-selection argument in the design spec predicts — a limit that fills only because you
ignored the spread is a limit that filled at a price the market never actually offered.

---

## 5 · Verdict on `+0.19R` — NOT ANSWERED, and the plan could not have answered it

**The re-baseline this session set out to perform did not happen, because the fix never
reached the code that produces `+0.19R`.** Two verified reasons:

**(a) `scripts/poc_sb_stops.py` carries its own, separate fill logic.**
`poc_sb_stops.py:189` is `if lows[k] <= entry <= highs[k]:` — the *same* direction-blind
bid-touch test Task 2 corrected. It does not import `resolve_trade` and was untouched by this
session. The published study still runs on the uncorrected model.

**(b) `research_run.py` does not model the exit engine the adopted config depends on.**
`grep -c "ratchet|runner|trail"` → **0** in `research_run.py` and `kernel_replay.py`, **18** in
`poc_sb_stops.py`. `research_run` resolves every trade at a fixed 2R. `CLAUDE.md` records that
fixed 2R was net-negative and that "ratchet+runner is what makes SilverBullet net-positive".

So the baseline arm above (+0.078 IS / −0.052 OOS) is **not** a reproduction of `+0.19R` and
was never going to be. It is the fixed-2R configuration — the one already known to be
net-negative — and the two numbers are not comparable.

This independently confirms audit finding **STRAT-01**: the strategy's edge lives in an exit
engine the research harness never runs.

**What is established:** the fill-model correction costs EURUSD **0.089R in-sample** and moves
PF below 1.0, on the fixed-2R harness. The direction and rough magnitude are real. Whether the
same correction moves the ratchet+runner `+0.19R` figure is **unknown**.

**What it would take to answer it:** port the direction-aware trigger into
`poc_sb_stops.py:189` and re-run that study. That is a separate task with its own risk — that
file produced adopted results, so the change must be proven not to alter anything except fill
eligibility.

---

## 6 · What this does and does not imply

**Does not imply:** that `config/config.yaml` should change. Nothing here re-measures the
adopted configuration. Do not touch the live pairs list or `stop_atr` on the strength of this.

**Does imply:** any future study run through `research_run.py` is now measuring fills
correctly, and the passive-entry layer (sessions 2-4) can be gated on it without the result
being self-confirming. That was the actual prerequisite this session existed to satisfy, and
it is met.

**Raises:** the adopted `+0.19R` rests on a fill model now demonstrated to be optimistic in a
way that mattered — a 2% change in fill eligibility flipped EURUSD's in-sample sign. That is a
reason to schedule the `poc_sb_stops` port, not a reason to distrust the live config today.

---

## 7 · Scope and method limitations (stated, not buried)

1. **One symbol.** EURUSD only, of 11 eligible. Runs cost ~80 min each and the machine shares
   CPU with the live demo-forward-test bot; the owner chose the single-symbol read rather than
   a 27-hour sweep. Per-symbol and pooled figures — and gate criteria 1-4 in the design spec —
   remain unmeasured. Ten symbols are outstanding: US100, ETHUSD, XAUUSD, GBPUSD, USDJPY,
   AUDUSD, USDCAD, GBPJPY, US30, BTCUSD.

2. **The `attrib0` arm is mis-designed.** It was meant to isolate the gap-fill change by
   removing the spread haircut from the *trigger*. But `--spread-pips 0` also zeroes the
   spread *cost*, so it differs from baseline in two ways at once and its expectancy column
   (+0.1171 IS) is not a like-for-like comparison — it is simply a costless run. It happens to
   deliver the intended isolation anyway, but via **trade counts** (identical at 143), not via
   expectancy. A correct isolation arm would need a trigger-only spread override, which the
   CLI does not expose.

3. **XTIUSD excluded** (§2) — unverified tick specs. Research-only; live trading unaffected.

4. **Contended machine.** Runs executed at load 8-13 alongside other sessions. This affects
   wall-clock timings quoted here, not results — the pipeline is deterministic.

5. **Run-cards are not committed.** `data/results/` is gitignored, so the three `run.json` /
   `signals.jsonl` sets cannot ship with this document and the table in §4 is the record. They
   were written to `data/results/fillmodel_20260730/{corrected,attrib0,baseline}_EURUSD/` in
   the `feat/fill-model-correction` worktree on the machine that ran them. To regenerate:

   ```bash
   # corrected arm (HEAD)
   .venv/bin/python scripts/research_run.py --csv data/history/EURUSD_M5.csv \
       --symbol EURUSD --tf H1 --strategy silver_bullet --spread-pips 8 --out <dir>
   # baseline arm: same command with tests/backtest/backtest_engine.py from 5b067a1
   git show 5b067a1:tests/backtest/backtest_engine.py > tests/backtest/backtest_engine.py
   ```

   ~80 min per arm at 18,631 H1 bars. Restore the engine afterwards.
