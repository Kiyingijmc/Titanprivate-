# Port the direction-aware fill trigger into `poc_sb_stops.py` — design

**Date:** 2026-07-31
**Status:** design, not yet approved
**Parent:** `docs/superpowers/specs/2026-07-29-passive-entry-layer-design.md` §6.1
**Predecessor:** session 1, `docs/research/2026-07-30-fill-model-correction.md`
**Scope:** offline research only. No `src/` change, no `config/config.yaml` change.

---

## 1 · Why this exists

Session 1 corrected the LIMIT fill trigger in `tests/backtest/backtest_engine.py::resolve_trade`
and proved the correction bites: on EURUSD it cost **0.089R in-sample** and moved PF from 1.118
to **0.984**, on only 3 changed trades out of 143.

It then established that **the fix never reached the code that produced the adopted
`+0.19R`**:

| Fact | Evidence |
|---|---|
| `poc_sb_stops.py` has its **own** fill test | `scripts/poc_sb_stops.py:189` — `if lows[k] <= entry <= highs[k]:`, direction-blind, identical to the bug fixed in `151188b`. It does not import `resolve_trade`. |
| `research_run.py` cannot substitute for it | `grep -c "ratchet\|runner\|trail"` → **0** in `research_run.py` / `kernel_replay.py`, **18** in `poc_sb_stops.py`. `research_run` resolves at a fixed 2R, which `CLAUDE.md` records as net-negative. |

So the `+0.19R, PF 1.53` figure that justifies the live 12-pair config is still computed on the
optimistic model. This is audit finding **STRAT-01** in concrete form: the edge lives in an exit
engine the corrected harness never runs.

**The demo-forward-test is live on that config now, with a checkpoint around 2026-08-11.** This
study should land before it, so the checkpoint is read against a fill model that reflects how
MT5 actually fills.

### 1.1 A second, independent defect found while scoping this

`cost_r()` (`poc_sb_stops.py:396-403`) applies `spread_mult` to **cost only**:

```python
spread = SPREADS.get(sym, 20) * spread_mult * tick    # price units -> charged as cost
```

The fill loop at line 189 never sees `spread` or `spread_mult` at all. Therefore the study's
**"positive at 2× spread stress"** arm stresses the *charge* while leaving *fill eligibility*
unstressed — at 2× spread a buy limit still fills wherever the bid merely touched it.

This matters beyond the headline number: **that stress arm is an adoption criterion.** US100,
ETHUSD and XTIUSD were admitted to the live universe partly on "positive at 2× spread stress"
(`docs/research/2026-07-28-universe-expansion-screen.md`). Under a correct model, doubling the
spread should *also* make buy limits harder to fill, so the stress arm was never as severe as
it read. Fixing the trigger fixes the stress arm as a side effect, and the re-run therefore
re-tests the expansion decision too — that is in scope and must be reported, not buried.

---

## 2 · The change

`poc_sb_stops.py:186-193`, the limit-fill loop. Bars are **BID** OHLC. MT5 triggers BUY orders
on **ASK** (`= bid + spread`) and SELL orders on **BID**:

| order | MT5 trigger | bid-OHLC test |
|---|---|---|
| BUY LIMIT | `ask <= price` | `lows[k] <= entry - spread` |
| SELL LIMIT | `bid >= price` | `highs[k] >= entry` — unchanged |

`is_long` is already in scope at line 183, so the direction is available. Two supporting
changes are required:

1. **Thread the spread into the fill function.** It currently receives only `(signals, bars,
   model)`; `sym`, `specs` and `spread_mult` live in the caller. Add a single
   `spread=0.0` keyword in **price units** — the same shape `resolve_trade` now takes, so the
   two engines stay comparable. The caller computes it with the *existing* `cost_r` formula,
   `SPREADS[sym] * spread_mult * tick`, so cost and fill can never disagree about what the
   spread is.
2. **Default `spread=0.0` reproduces today's behaviour** apart from the gapped-limit fix (see
   §2.1), so every existing caller keeps working and the diff is auditable.

### 2.1 The gapped-limit change rides along

Replacing `lows[k] <= entry <= highs[k]` with a one-sided test also fixes bars that gap
*entirely* past the limit, which the range test wrongly skipped. On EURUSD this changed
nothing — at spread 0 the corrected engine produced identical trade counts across 3 years. It
is untested on the gap-prone instruments, which is most of what this study covers that EURUSD
does not: BTCUSD, ETHUSD, US30, US100 over weekend and session breaks. **Expect this study,
unlike session 1's, to show a non-zero gap-fill effect.** Report it separately (§4).

### 2.2 Explicitly NOT doing: unifying the two engines

Both engines now implement the same rule in two places, which is how they drifted apart in the
first place. Making `poc_sb_stops` import `resolve_trade` is tempting and **out of scope**: the
two differ in return shape, stop models, TTL and `busy_until` semantics, and this file produced
adopted results. A refactor here risks changing numbers for reasons unrelated to fills.

Instead, §5 adds a **cross-engine consistency test** so the two implementations are pinned to
each other and cannot drift again silently. Unification, if wanted, is a later task done from a
green test.

---

## 3 · Risk: this file produced adopted results

`poc_sb_stops.py` generated the study behind the live config. The change must be provably
confined to fill eligibility.

**Control:** re-run at `spread=0.0` first and require the output to be **identical** to the
pre-change run except where a bar gapped fully past a limit. Any other difference means the
edit changed something it should not have — stop and diagnose rather than explain it away.

Concretely, before the real run:

- `--sym EURUSD --quick` at `spread=0.0`, pre- vs post-change: trade count, per-trade
  `fill_idx`, `outcome` and `r` must match row-for-row, with gap-fill differences the only
  permitted exception, each one individually identified.
- Only once that holds does the priced run mean anything.

---

## 4 · Deliverable

`docs/research/2026-08-XX-poc-sb-stops-fill-port.md`, reporting:

1. **Control result** (§3) — proof the edit is fill-only.
2. **Headline:** adopted `+0.19R / PF 1.53` (managed = ratchet + runner, 1× spread) re-measured
   on the corrected trigger. State the new number plainly, whatever it is.
3. **Attribution**, three arms, since the two corrections pull in *opposite* directions and can
   mask each other:
   - `spread=0` corrected vs pre-change → isolates the **gap-fill** effect;
   - `spread=1×` corrected vs `spread=0` corrected → isolates the **haircut** effect;
   - combined → the headline.
4. **Stress arms re-run** (1×/1.5×/2×) with the spread now applied to fills *and* cost, and an
   explicit statement of whether US100 / ETHUSD / XTIUSD still clear the "positive at 2×"
   criterion they were adopted on.
5. **Per-symbol table** and the pooled figure over the same symbol set the original study used,
   so old and new are like-for-like.
6. **Fill-rate delta per symbol** — how many limits stop filling. Session 1's EURUSD answer was
   3 of 143, and that was enough to flip a sign.

### 4.1 Pre-registered interpretation

Fixed **before** the run, so the result cannot be rationalised afterwards:

- **A degraded number is the expected outcome, not a failure.** The correction removes fills
  that never should have happened; the only question is magnitude.
- The ratchet + runner may prove **less** fill-sensitive than session 1's fixed-2R harness —
  partials at 61.8% / 88.6% bank something even on a marginal fill — or **more**, if the
  phantom fills were disproportionately the runners that carry the edge. Both are plausible.
  No prediction is being made.
- **A materially degraded figure is a finding about the current live config, not a licence to
  change it.** `config/config.yaml` is out of scope. The adoption call is the owner's, informed
  by this and by the demo-forward-test's own realised fills at the 08-11 checkpoint.
- If the corrected figure lands near or below break-even, say so in the first line of the doc.

---

## 5 · Tests

`poc_sb_stops.py` is a script with no unit coverage today. Minimum viable, in
`tests/unit/test_poc_sb_stops_fill.py`:

1. **BUY LIMIT needs the haircut** — bid touches `entry`, ask does not reach it → no fill.
2. **SELL LIMIT takes no haircut** — the mirrored price fills where the buy side did not.
3. **`spread=0.0` reproduces the legacy touch behaviour** on a non-gapping fixture.
4. **A bar gapping fully past the limit fills** — the range test wrongly skipped it.
5. **Cross-engine consistency (the anti-drift pin):** over a table of (direction, entry, spread,
   bars) cases, `poc_sb_stops`'s fill decision and
   `backtest_engine.resolve_trade`'s must agree on fill / no-fill and on the fill bar index.
   This is the test that stops the two engines diverging again, which is the root cause of this
   whole session existing.

Each must fail before the change. Full suite green:
`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`

---

## 6 · Cost and sequencing

`poc_sb_stops.py` runs 11 symbols × 4 stop models over 3 years of M5. Session 1 measured
~80 min per single-symbol H1 replay in `research_run`; this script is structured differently
(one pass per symbol, vectorised numpy arrays, no per-bar kernel), so it should be **much**
faster — but that must be **measured on one symbol before committing to a full run**, not
assumed. Session 1's plan under-estimated runtime by an order of magnitude and cost a wasted
night; do not repeat it.

The machine is shared with the live demo-forward-test bot. Measure first, then choose scope.

---

## 7 · Out of scope

- Any `src/` or `config/config.yaml` change.
- Unifying the two fill engines (§2.2).
- The passive-entry layer itself — sessions 2-4 of the parent spec.
- The remaining 10 symbols of session 1's `research_run` sweep. Now known to be low value:
  that harness does not model the exit engine, so its absolute numbers answer no live question.
