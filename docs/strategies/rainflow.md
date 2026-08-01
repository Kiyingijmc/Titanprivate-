# Rainflow — rainflow-counting fatigue-accumulation compression/breakout model

> **Status:** candidate (Wave 2, pending gate-triage) · **Family:** volatility-compression breakout ·
> **Timeframe:** H1 ·
> **Origin:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §4 (lines 215-273), §12 comparative
> matrix (row 4). **Not ranked in §13** — the shortlist names Gyroscope/Aftershock/Rubicon and gives
> honorable mentions to Antibody and Gumbel Fade only · **Doc version:** 2026-08-01

## 1. Thesis and return source

Family: volatility-compression breakout — a known, well-worn family (Bollinger squeeze and relatives).
The brainstorm is explicit about this: "the *family* is volatility-compression breakout (known)"
(`…brainstorm.md:226`). Rainflow's claimed novelty is not the family, it is the **statistic**: instead
of reading compression as a point-in-time volatility level (a memoryless reading — quiet now says
nothing about how it got quiet), Rainflow runs the actual rainflow-counting algorithm from mechanical
fatigue analysis on the H1 price series inside a detected range, decomposing the price path into
discrete oscillation cycles and their amplitudes. A **fatigue index** accumulates from cycles of
*decreasing* amplitude against a static boundary — "many cycles at decreasing amplitude... = resting
interest at the boundary is being consumed" (`…brainstorm.md:224`). This is explicitly a **path-integral
statistic**, not a level: it is designed to distinguish "quiet because nothing is happening" from "quiet
because a compressed spring has cycled 9 times with shrinking amplitude" (`…brainstorm.md:224`). A
secondary novel element is **boundary asymmetry**: the boundary absorbing more, or later, cycle touches
is read as the side more likely to fail (`…brainstorm.md:229`).

Return source: ranges that cycle with contracting amplitude break out more violently and more
predictably than ranges identified by low volatility alone, and targets scale with the pre-break range
and fatigue level, so — per the brainstorm's costs framing — spread is respected because target size
tracks structure (`…brainstorm.md:229`).

**This document does not claim the novel statistic adds anything over the memoryless baseline.**
Whether it does is precisely what the mandated A/B test in §6 exists to answer, and the brainstorm's own
honesty note treats a null result as a fully expected, recordable outcome (`…brainstorm.md:272`).

## 2. Evidence base

**Supporting (design-level; family-level precedent exists outside this repo, the specific statistic is
untested here):**
- Volatility-compression breakout is a long-established family with real precedent (Bollinger squeeze
  and its many derivatives), unlike, say, Rubicon's undocumented drift-persistence hypothesis.
- Rainflow's targets scale with the pre-break range, giving it the same structural cost-robustness
  property as Aftershock and Gyroscope's wide, structural stops — not an ATR multiple.
- Comparative matrix: complexity 6/10, expected robustness 3/5, cost survival 4/5, existence risk 3/5,
  adaptability 3/5 (`…brainstorm.md:620`) — a middling profile, not a standout.

**Adverse (stated plainly, per house rule):**
- The graveyard: OTE −0.158R pooled, MTF-PB v2 −0.274R pooled, original SilverBullet M5 −4.27R, and
  **Gyroscope** — the arsenal's own #1-ranked pick — NO-GO at −0.067R pooled, 4/9 symbols non-negative,
  27.1% realized false-entry rate vs a designed 5% α
  (`docs/research/2026-07-14-gyroscope-gate-results.md`).
- **The Gyroscope lesson bears directly on Rainflow's own named failure mode.** Gyroscope's sequential
  decision rule realized error rates far above its designed budget because the theory assumed i.i.d.
  behavior that autocorrelated market data violated (`…gate-results.md:38,40,44`). Rainflow's own
  weaknesses section names an analogous, well-known failure mode for this family: **false breakouts**
  — "the classic" (`…brainstorm.md:253`) — and the brainstorm's mitigation (expansion-bar trigger,
  2-close failure exit, one-attempt-per-range rule) is a deterministic decision rule whose *realized*
  false-break rate, exactly like Gyroscope's realized false-entry rate, could diverge from whatever rate
  is assumed or hoped for during design. This document treats **false-break rate as a first-class,
  monitored metric from day one of the gate** (per the brief's explicit instruction), not an
  after-the-fact diagnostic, precisely because Gyroscope showed a mechanically sound implementation can
  still miss its own advertised error budget by 5×.
- Rainflow's own weaknesses, stated in the source: "known family with a known failure mode (false
  breaks); zigzag turning-point extraction has a look-back confirmation lag; several structural
  parameters (band tolerance, D_crit) to discipline" (`…brainstorm.md:259`).
- No Rainflow-specific event study, A/B result, or backtest has been run. Every quantitative claim about
  Rainflow's own performance is **not yet measured**.
- **EXP-0 implication:** placebo entries through the live exit engine net −0.249R (0/20 reps positive)
  vs SilverBullet's real +0.109R (`docs/research/2026-07-31-exp0-coinflip-preregistration.md`); the
  exit engine amplifies real edges (+0.231R) but does not subsidise random ones (+0.075R). Rainflow's
  entries — a breakout trigger no different in kind from many known-dead intraday breakout systems —
  must independently clear the A/B baseline in §6 before any credit is given to the ratchet's
  amplification.

## 3. Signal specification

**Range identification:** ≥4 alternating turning points (zigzag on closed H1 bars) within a bounded
band (`…brainstorm.md:236`).

**Fatigue accumulation:** run the rainflow-counting algorithm on the identified range's turning points,
extracting `{amplitude, mean}` cycles; update fatigue index D on each new cycle, **requiring amplitude
contraction** — cycles must be shrinking, not merely repeating (`…brainstorm.md:237`, `…:224`).
Amplitudes normalized by ATR for cross-asset comparability (`…brainstorm.md:253`).

**Armed condition:** `D > D_crit` and range width/ATR still tradeable (`…brainstorm.md:238`).

**State machine** (`…brainstorm.md:236-241`):
```
SCANNING → RANGE IDENTIFIED (>=4 alternating turning points within a band) →
FATIGUE ACCUMULATION (update D each new cycle; require amplitude contraction) →
ARMED (D > D_crit AND width/ATR still tradeable) → TRIGGER (close beyond boundary
with range expansion bar) → ENTRY → MANAGEMENT → EXIT → RESET (D := 0)
Invalidation: range widens beyond tolerance or D stale-decays → back to SCANNING.
```

**Entry:** armed + H1 close beyond the fatigued boundary, on a bar whose range exceeds the median (the
expansion requirement filters drips) (`…brainstorm.md:244`). **Direction is determined by boundary
asymmetry** — the boundary with the higher accumulated damage/cycle count (`…brainstorm.md:244`).

**Order type:** `STOP` at the boundary ± a buffer is explicitly acceptable — the brainstorm names the
existing `STOP` command directly (`…brainstorm.md:244`). Per the brief's platform contract, `STOP` is
supported end-to-end but currently **unused by any strategy in this repo** — Rainflow going live with
the STOP variant would be the first strategy to exercise that order type in production, not just in
theory.

**Stop:** inside the range — midpoint or opposite third, i.e. the structure that failed
(`…brainstorm.md:247`).

**Target:** TP1 at 1× projected range height; runner via the standard ratchet beyond that
(`…brainstorm.md:247`).

**False-break exit — a new, deterministic exit primitive:** re-entry back inside the range for 2
consecutive closes = failed break → flatten immediately, no discretion (`…brainstorm.md:247`, `:250`).

**Attempt discipline:** one attempt per identified range; a failed break voids the range entirely — no
revenge re-entry — because false-break losses are named as "the known killer of this family" and are
capped by construction, not by hope (`…brainstorm.md:250`).

**Cost screen:** skip if range height < n× spread (`…brainstorm.md:250`).

**Universe:** H1, frozen 9-symbol gate set as the default screening universe (`data/lake/frozen/`),
consistent with the other Wave 2 candidates.

## 4. Architecture integration

**Class placement** (mirrors the Gyroscope precedent — `src/strategies/models/gyroscope.py` +
`src/analysis/kalman_drift.py`):
```
src/strategies/models/rainflow.py        # RainflowStrategy(BaseStrategy)
src/analysis/rainflow_counting.py        # zigzag extraction + rainflow cycle counting + fatigue index D
tests/unit/test_rainflow_counting.py     # cycle extraction on synthetic contracting/non-contracting paths
tests/unit/test_rainflow_strategy.py     # decision-dict contract, gating, false-break flatten, STOP order path
```

**Manifest sketch** (`config/manifests/rainflow.yaml`, format verified against the live
`config/manifests/gyroscope.yaml`):
```yaml
id: rainflow
version: "0.1.0"
class_path: "src.strategies.models.rainflow:RainflowStrategy"
family: vol_compression_breakout
timeframe: H1
requires: []
status: research
priority: 66          # illustrative placeholder; final value set at spec time
honors_htf_bias: false
```
`honors_htf_bias: false` — direction is read from boundary-cycle asymmetry within the identified range,
a signal independent of the controller's separately-computed HTF bias. Same exemption mechanism as
`gyroscope` and `ma_slope_baseline` (`src/strategies/manifest.py:33`, `src/strategies/registry.py:75`,
`src/core/system_controller.py:962`).

**Config block sketch:**
```yaml
strategies:
  rainflow:
    enabled: false
    timeframe: H1
    pairs: []
    min_turning_points: 4
    band_tolerance: 0.15        # structural parameter to discipline in the gate — brainstorm's own caution
    d_crit: 1.0                 # fatigue-index arming threshold
    expansion_bar_median_mult: 1.0
    boundary_buffer_atr_frac: 0.10
    order_type: STOP            # STOP variant; MARKET also acceptable per §3
    tp_range_multiple: 1.0
    failed_break_closes: 2
    min_range_spread_multiple: 3.0
```

**FeatureBus:** no resource required to consume for v1. `validate_data(df, min_length=warmup,
check_smc=False)` — raw OHLC only, same as Gyroscope/Aftershock/Rubicon.

**Grading path (P8):** verified against `src/analysis/signal_grader.py:1-119` rather than assumed.
Displacement (≤20) is scored from `enriched_df.iloc[-1]`'s ATR/open/close regardless of strategy family
(`system_controller.py:969`) — Rainflow's own entry trigger *requires* a bar range above median
(expansion), so displacement should score well by construction, arguably the strongest case of the
three Wave-2 candidates in this batch. Premium/discount defaults to `+5` (no liquidity concept).
Killzone (`+15`) is time-based and unrelated to fatigue state. HTF bias scores 10 (neutral) unless
coincidentally aligned. Net: this is the candidate in this batch **most likely to clear `min_grade: B`
(55) on displacement alone**, to be confirmed empirically — not a blanket "SMC-shaped grader caps this."

**HTF-bias stance:** exempted (`honors_htf_bias: false`).

**Exit profile:** the default ratchet engages normally for TP1-and-runner management once
`initial_entry`/`initial_tp` are non-zero. The **2-close false-break flatten**, like Aftershock's
λ-decay flatten and Rubicon's next-break-flatten, is a state-based exit `TradeManager.sync_positions`
cannot compute on its own — it has no concept of "closes back inside the range." It needs the same
strategy-initiated-flatten hook described in `docs/strategies/rubicon.md` §4: a new controller call
(e.g. `strategy.check_exits(open_orders_for_me, context)`) whose output routes through the existing
`_dispatch_mgmt_command` (`src/core/system_controller.py:648`) exactly as `TradeManager` output does
today — fire-and-forget `CLOSE_POS` on PUSH, verified from HEARTBEAT, never the REQ path. This is not a
new gap specific to Rainflow; it is the same missing plumbing all three Wave-2 candidates in this batch
need, and should be built once, shared.

**Risk interaction:** unchanged `RiskManager.calculate_lot_size`; stop distance is range-derived
(structurally meaningful, not an ATR multiple). The book-wide portfolio cap already aggregates risk
across strategies with no new work. Note: because Rainflow proposes `STOP` pending orders and the
platform has **no OCO** (brief item 9: "two pending orders are not paired; `max_positions_per_symbol: 1`
blocks — not cancels — the sibling"), a design choice is needed at spec time: place the `STOP` only on
the fatigue-favored boundary (this document's default, avoiding the OCO gap entirely) rather than
bracketing both boundaries, which would require pairing infrastructure that does not exist.

## 5. Infrastructure prerequisites

| Gap | Description | Effort |
|---|---|---|
| Strategy-initiated flatten hook | Shared with Aftershock and Rubicon — no mechanism today for a strategy to emit a management command outside `on_new_candle`'s single-decision contract. Needed for the 2-close false-break flatten. Build once, shared across all three Wave-2 candidates in this batch. | Medium — new controller hook + tests |
| P8 (grading) | Likely not a hard cap — plausibly the strongest displacement case of the three candidates (expansion-bar entry trigger) — but must be confirmed empirically. | Low |
| P6/RISK-07 | `context['spread']` does not exist live; the "range height < n× spread" cost screen is inert on the live path exactly as Gyroscope's `max_spread_atr_frac` is. Backtest cost modeling via `scripts/poc_sb_stops.py:43` is unaffected. | Medium — EA/bridge change |
| STRAT-01 | `poc_sb_stops.py`'s `replay_managed` models the ratchet as an upper bound but has no concept of the 2-close false-break flatten — that exit primitive is entirely unmodeled by any existing harness. FIXED-R `backtest_engine.py` resolution is the only currently-trustable number and doesn't test this strategy's most distinctive risk control. | Medium-High — new replay logic |
| P2 (no OCO) | Directly relevant if a future revision wants to bracket both boundaries rather than trade only the fatigue-favored side; this document's default design avoids the gap by construction (single-sided STOP), but the constraint should be recorded so it isn't silently reintroduced later. | None for v1; flag for any bracket-order revision |
| First live use of `STOP` orders | The brief notes `STOP` is supported end-to-end but unused by any strategy today. Rainflow would be the first production exerciser of that code path — worth calling out as new-surface-area risk even though the command itself already exists. | Low-Medium — integration testing, not new capability |
| Zigzag/rainflow implementation | No zigzag or rainflow-counting code exists in this repo yet; this is genuinely new analysis code (`src/analysis/rainflow_counting.py`), not a wrapper around existing analyzers. | Medium |

## 6. Validation plan

**This is the load-bearing section of this document.** The brainstorm mandates an A/B test against a
plain Bollinger-squeeze breakout on identical trigger/exit scaffolding — "Rainflow must beat the
memoryless baseline, else the path-dependence adds nothing and we record that" (`…brainstorm.md:272`).

**The Coil overlap must be stated plainly, per this document's own brief:** the audit-arsenal's Coil
concept (`docs/strategies/coil.md`, origin `docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md` §4) is the
memoryless-squeeze member of the same volatility-compression-breakout family — its compression
detector is a point-in-time reading (ATR(14,H1) in the bottom 25th percentile of 200 bars, plus a
4-bar range < 1.2×ATR, `coil.md` §3), which is exactly the memoryless statistic Rainflow's fatigue
index claims to improve on. **Coil and Rainflow are one research question with two detectors**, not
two independent strategies that happen to share a family. Rainflow's own mandated A/B baseline (a
memoryless squeeze reading) **is Coil's detector in all but name** — feeding the same expansion
trigger and structural exits. One genuine difference must be reconciled when the shared gate is
drafted: Coil is *direction-agnostic* (a two-sided STOP bracket, which hard-requires the missing OCO
pairing, P2), whereas Rainflow picks a side from boundary asymmetry and so needs only a single-sided
order. The shared arms must therefore fix one entry geometry — the honest choice is single-sided for
both arms, so that the compression statistic is the only variable and neither arm is blocked on P2.
Running two
separate pre-registered gates for what is functionally the same baseline-vs-treatment comparison would
duplicate the scaffolding, split the trade-count budget across two studies that both need it, and risk
the two docs silently drifting on trigger/exit details in a way that would make a later comparison
between them meaningless. **This document's recommendation is therefore explicit: Rainflow and Coil
should share one pre-registration with two arms** (arm A: memoryless squeeze / Coil's detector; arm B:
rainflow fatigue statistic), run on identical range-identification, trigger, and exit scaffolding, on
the same symbols and date range, so the only thing that differs between arms is the compression
statistic itself. This is a stronger, cleaner test of the brainstorm's own honesty note than two
separate gates could produce, and it directly resolves what would otherwise become a coordination
problem between this document and `docs/strategies/coil.md`.

Instantiating TVP for the shared two-arm study:

1. Identical range-identification, expansion-bar trigger, structural stop, TP1/runner, and false-break
   flatten scaffolding for both arms — the *only* difference is arm A's compression statistic (rolling
   Bollinger-width or equivalent memoryless vol reading) versus arm B's fatigue index D from actual
   rainflow counting.
2. Frozen 9-symbol H1 dataset (`data/lake/frozen/`, ~18,600 bars/symbol), 70/30 chronological IS/OOS,
   ±30% sweeps on each arm's own threshold parameters (arm A's squeeze threshold; arm B's `d_crit` and
   `band_tolerance`), ×1.5/×2 spread stress, bootstrap 95% CI, ≥6/9 symbols non-negative per arm
   (mirroring the criterion Gyroscope failed at 4/9).
3. **False-break rate is a first-class, gating metric for both arms**, not merely reported — per the
   brief's explicit instruction and the Gyroscope-lesson reasoning in §2. Track it exactly as
   prominently as net expectancy in the results table.
4. GO condition for shipping Rainflow specifically: arm B must clear its own net-expectancy/OOS/
   consistency bar **and** beat arm A by a pre-registered margin, not merely tie it — a tie is a
   NO-GO for the path-dependent statistic (the memoryless version would ship instead, or neither would).
5. **Cannot currently be validated:** the 2-close false-break flatten's effect on realized R (no
   harness models it — see §5 STRAT-01); live spread-based range-height filtering (P6/RISK-07 inert);
   the `STOP`-order fill/slippage characteristics in practice, since no strategy has exercised that
   order type live before.

## 7. Failure modes and monitoring

- **False breakouts — "the classic," named directly in the source** (`…brainstorm.md:253`). Mitigated
  by the expansion-bar trigger, the 2-close failure exit, and the one-attempt-per-range rule. Realized
  false-break rate is tracked live and compared against the gate-measured rate, mirroring Gyroscope's
  self-audit discipline (`…gate-results.md:38`) — a material excess should auto-pause the strategy and
  alert, the same standard applied to the other two Wave-2 candidates in this batch.
- **Fatigue index miscalibration across assets** — mitigated by ATR-normalizing amplitudes
  (`…brainstorm.md:253`); should be checked per-symbol in the gate, not assumed uniform.
- **Ranges that resolve by drift rather than break** — the range never "fails" cleanly, it just walks
  away; time-decay D and stand down (`…brainstorm.md:253`).
- **Zigzag look-back confirmation lag** — turning-point extraction inherently trails price by
  construction; this bounds how early D can possibly be computed and should be stated as a known latency
  in the gate doc, not discovered live.
- **Live self-audit:** false-break rate (2-close reversal after entry / total entries), rolling, is the
  primary live health metric — track it with the same seriousness as P&L, per §6.

## 8. Verdict and sequencing

**Recommendation:** do not write `RainflowStrategy` or `rainflow_counting.py` in isolation. Coordinate
with whoever owns `docs/strategies/coil.md` before either implementation begins, and draft the shared
two-arm pre-registration first — the scaffolding (range ID, trigger, stop, exits) is common to both and
should be built once, not twice. Given `status: candidate (Wave 2, pending gate-triage)`, this
document's disposition is to recommend the merge-of-gates described in §6 as the next concrete step,
ahead of any code.

No sequencing dependency on Aftershock or Rubicon (`docs/strategies/aftershock.md`,
`docs/strategies/rubicon.md`) beyond sharing the same to-be-built strategy-initiated-flatten controller
hook (§4/§5), which should be built once and reused by whichever of the three candidates reaches that
stage first. As with the other two documents in this batch, the EXP-0 finding is the governing caveat:
Rainflow's entries must independently beat the memoryless baseline and earn their own directional edge
before any credit is attributed to the exit engine's amplification — the ratchet cannot manufacture an
edge that the fatigue statistic doesn't actually carry over Coil's simpler detector.
