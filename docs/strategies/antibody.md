# ANTIBODY — immune-system anomaly sentinel (defensive overlay)

> **Status:** v1 EXECUTED, RECORD-ONLY · **Family:** immunology / intrusion-detection anomaly
> scoring (defensive overlay, not an entry generator) · **Timeframe:** cross-timeframe scoring
> (study run at bar-level; not tied to one strategy's TF) ·
> **Origin:** `docs/research/2026-07-12-novel-arsenal-brainstorm.md` §10; study executed on branch
> `feat/antibody-study` (commits `14064ab`..`3755fe3`), results in
> `docs/research/2026-07-14-antibody-study-results.md` on that branch · **Doc version:** 2026-08-01

## 1. Thesis and return source

Antibody is not an entry generator. It is a defensive sentinel modelled on negative-selection
immunology and intrusion detection: learn the joint distribution of "normal market microbehaviour"
per symbol/session from bar-shape features (range/ATR, body/range, gap size, tick-volume z,
spread z, bar-to-bar overlap), maintain a deterministic anomaly score (Mahalanobis distance or
isolation-forest score) against that learned "self" model, and flag sustained anomaly as a
book-wide derate/lockout signal. The claimed value is not alpha from trading anomalies — it is
avoided tail loss from detecting "we are off the map" (a market state absent from the training
distribution: flash events, broker feed pathologies, liquidity holes) in real time and cutting
exposure before it costs money, rather than after (brainstorm §10 item 4).

A secondary, offensive form (fading resolved single-bar anomalies) was noted in the source
brainstorm as testable but explicitly "not the point" (§10 item 3). v1, as actually built and
studied, tested the **defensive lockout premise only**: does SilverBullet's realized performance
differ inside vs. outside ALERT windows, in a way that would justify blocking new entries during an
alert.

## 2. Evidence base

v1 was executed as a pre-registered study (branch `feat/antibody-study`, commits `14064ab..3755fe3`;
results doc `docs/research/2026-07-14-antibody-study-results.md`, on that branch). Per the brief,
these are the study's real results:

| Criterion | Pre-registered bar | Result | Verdict |
|---|---|---|---|
| #1 — Alert rate cap | Pooled alert rate ≪ 2% of scored bars | **0.05%** (58/116,856 scored bars) | **PASS** |
| #2 — Minimum overlap sample | n ≥ 30 SilverBullet trades inside ALERT windows | **n = 1** (of 1,386 total SilverBullet trades) | **FAIL** |
| #3 — Inside-vs-outside expectancy | (contingent on #2 passing) | Inside +1.98R vs outside +0.044R, n=1 inside | **Moot** — statistically meaningless on n=1 |

Covariance conditioning (a numerical-stability precondition for the Mahalanobis-distance scorer,
not one of the three headline gates) was well-conditioned across all 9 symbols studied, worst
condition number ≈3,000 — the scorer's underlying math is stable and not itself the reason for the
outcome below.

**Verdict, as recorded: "the scorer works; the overlap doesn't exist."** The anomaly detector
correctly identifies a small, disciplined slice of bars as anomalous (criterion #1 passed cleanly —
it is not over-firing), but SilverBullet's session-timed entries essentially never coincide with
the geometric anomalies Antibody flags. The two systems are watching different things: Antibody
watches bar-shape geometry; SilverBullet fires on a session-timing + displacement condition that,
empirically, almost never overlaps with a geometric anomaly window.

**Adverse framing, stated plainly:** this is a clean, pre-registered NO-GO for the *lockout*
premise as applied to SilverBullet specifically. The study did exactly what a TVP-disciplined study
should — record a null result rather than search for a way to rescue it. v1's code exists **only**
on the unmerged `feat/antibody-study` branch (`src/analysis/antibody.py`,
`scripts/antibody_study.py` and their tests) — nothing has been merged to `main`, and this
document does not treat the branch as already integrated.

**EXP-0 implication.** EXP-0 (brief) found the exit engine amplifies real entry edge (+0.231R on
real SilverBullet entries) but does not subsidise random entries (+0.075R on placebo). Antibody's
result is consistent with, and reinforces, that finding from a different angle: a defensive overlay
that *would* have blocked SilverBullet's one anomaly-window trade contributes nothing measurable
either way (n=1, statistically meaningless per criterion #3) — there is no free lunch from bolting
a generic anomaly filter onto an entry system whose edge comes from a specific, unrelated
mechanism (session timing + displacement, per `docs/strategies/silver-bullet.md` §1). A lockout
overlay only earns its keep against entry logic that actually intersects the anomalies it detects
— which v1 shows SilverBullet's does not.

## 3. Signal specification

As executed in v1 (the study protocol, not a live-code contract — v1 emits no `{signal, type,
price, sl, tp}` decision dict; it is a per-bar score plus a state machine):

- **Self-model:** per symbol/session, a fitted distribution over bar-shape features: range/ATR,
  body/range, gap size, tick-volume z-score, spread z-score, bar-to-bar overlap. Fit quarterly,
  frozen between refits (mirrors the anti-overfitting discipline used elsewhere in the arsenal —
  see `trinity.md` §3 for the same pattern applied to an HMM fit).
- **Score:** Mahalanobis distance (or isolation-forest score) against the self-model, per bar.
  Condition-number-stable on all 9 symbols tested (worst ≈3,000).
- **State machine (brainstorm §10 item 5–8):**
  ```
  SELF-MODEL (quarterly fit) → PATROL (score each bar) → ALERT (score > q99 for 2+ bars)
  → RESPONSE (block new entries; optionally tighten stops on open trades)
  → ALL-CLEAR (score normal for n bars) → PATROL
  ```
- **No entries of its own in v1** — confirmed both by design (§10 item 5) and by the study, which
  measured only the effect of ALERT windows on SilverBullet's *existing* entries, never generated
  any trade itself.
- **Alert rate, as measured:** 0.05% of scored bars (58/116,856) — a genuinely rare, disciplined
  signal, well inside its own 2% design cap.

## 4. Architecture integration

Antibody v1 is a study script (`scripts/antibody_study.py` on the unmerged branch), not a
`BaseStrategy` subclass, and this remains the correct shape if it is ever promoted: it has no
`on_new_candle` decision to make. If integrated live, it is closer to `NewsManager` than to a
strategy — a book-wide gate consulted at execution time, not a signal source routed through the
grader/arbiter.

- **Precedent already in the codebase:** `SystemController._news_blocks_symbol`
  (src/core/system_controller.py:480) is checked at the top of `_execute_signal`
  (system_controller.py:491, `news_blocked, news_reason = self._news_blocks_symbol(symbol)`) and
  short-circuits the trade before sizing. `NewsManager.is_globally_blocked()`
  (called at system_controller.py:1045) is the existing book-wide-lockout precedent. Antibody's
  ALERT→RESPONSE transition (§3) would plug into exactly this shape: a
  `self._antibody_blocks_symbol(symbol)` (or a book-wide `is_globally_alert()` for the "derate the
  whole arsenal" mode described in the brainstorm) checked alongside the existing news gate in
  `_execute_signal`, before `RiskManager.calculate_lot_size` is called.
- **Manifest:** none needed for this shape — like `NewsManager`, it is a controller-level service,
  not a `StrategyManifest` entry with an FSM state.
- **Class placement (if promoted from the study branch):** `src/analysis/antibody.py` (already
  exists on `feat/antibody-study`, unmerged) — the scorer and state machine, pure/stateless-in per
  the same design pattern as `src/analysis/kalman_drift.py` (Gyroscope). A thin controller-level
  consumer (`src/core/system_controller.py`) would call it once per bar per symbol, analogous to
  `news_manager.update_calendar()`.
- **FeatureBus resources:** none consumed or required — Antibody's inputs (bar-shape features, tick
  volume, spread) are available from the raw OHLC + bridge data already, not from the SMC pack.
- **Order types:** none — Antibody places no orders.
- **Grading path (P8):** not applicable — no `Intent` is submitted.
- **HTF-bias stance:** not applicable.
- **Exit profile:** the brainstorm's secondary note — "optionally tighten stops on open trades"
  during RESPONSE — is a real management-path change if ever built, not just an entry lockout; it
  would need to route through the existing `SystemController._dispatch_mgmt_command` path (`MODIFY`
  command, fire-and-forget PUSH, per the platform contract) rather than the REQ socket, same
  constraint every other trade-management action in this repo observes.
- **Risk interaction:** purely protective — entry lockouts and (optionally) stop tightening, never
  a size increase. Composes with, but is logically independent of, the existing news lockout, the
  v15.2 drawdown throttle, and the RISK-01 daily breaker; as with Trinity's multiple size-reducing
  mechanisms (`trinity.md` §7), a live implementation would need to make sure Antibody's block and
  the news block don't produce confusing double-attribution in logs/Telegram when both fire on the
  same bar.
- **Telemetry — the concrete, immediate item.** ALERT-state Telegram notification is an ops win
  independent of the lockout's trading value (confirmed null for SilverBullet by the study, §2).
  `src/ops/telemetry.py` already has the exact pattern to extend: `notify_signal`,
  `notify_execution`, `notify_close`, `notify_management` are all thin wrappers around
  `telegram_format.*` + `send_message` (telemetry.py:55-78). A `notify_antibody_alert(symbol,
  score, session)` following the same shape is a small, low-risk addition that gives the operator
  real-time visibility into flash events, feed pathologies, and liquidity holes — the exact
  situations Antibody is designed to catch — regardless of whether the lockout is ever wired into
  `_execute_signal`.

## 5. Infrastructure prerequisites

| Item | What | Why it matters here | Effort |
|---|---|---|---|
| Merge `feat/antibody-study` code (or port it) | `src/analysis/antibody.py`, `scripts/antibody_study.py` + tests exist only on the unmerged branch | Nothing from v1 is on `main` today; this document does not assume otherwise | Not sized; branch exists, needs an integration decision |
| New: `_antibody_blocks_symbol` / `is_globally_alert()` gate | Mirror `NewsManager`'s existing block pattern (system_controller.py:480, :1045) | The only way ALERT state actually affects trading; does not exist today even on the study branch (the study measured the *effect* of hypothetical blocking, not live blocking) | Small — the news-gate precedent is a direct template |
| New: `notify_antibody_alert` Telegram wrapper | Extend `src/ops/telemetry.py` following the `notify_signal`/`notify_execution` pattern (telemetry.py:55-78) | Immediate ops win, independent of the lockout's (currently null) trading value | Small |
| P6 | Ask price captured; spread gate live (`docs/audit-2026-07-30/05-STRATEGY-ARSENAL.md:418`) | v2's proposed spread-z feature needs real spread capture; today `context['spread']` does not exist in the live path (audit RISK-07) | 1 h (audit estimate) — but is a real blocker for v2 specifically |
| Stop-tightening management path (optional RESPONSE behaviour) | Route through `_dispatch_mgmt_command` (`MODIFY`, fire-and-forget PUSH) | Only needed if RESPONSE is extended beyond entry lockout to open-trade stop tightening | Not sized; optional scope |

## 6. Validation plan

v1's validation is complete for the question it asked (SilverBullet lockout premise) and the
result is recorded above (§2) — no further work is needed to close that question; the honest
answer is NO-GO for that specific pairing, not "inconclusive, needs more data." Re-running the same
study with more history would not change the structural finding: SilverBullet's session-timed
entry condition and Antibody's geometric-anomaly condition are close to independent processes: more
bars would very likely still produce n≈1-2 overlap trades, not the 30 required, because the
mechanisms don't coincide by construction, not by bad luck of sample size. Re-testing is not
pre-registered as a next step for v1 as scoped.

**Pre-registered next step (v2), not yet executed:** add tick-volume z and spread z as scorer
features (brainstorm §10 hints at this via `Walclock`-adjacent effort/flow signals; this document's
brief specifies it directly). This needs real spread capture (P6, §5) — v2 cannot be honestly run
without it, since a spread-z feature computed from a placeholder or stale spread value would not be
measuring what it claims to.

**What cannot be validated with current data:** v2's tick-volume-z and spread-z features are
blocked, not by history depth, but by the missing live spread-capture path (P6). Tick volume itself
is already available via the bridge (brief item 8; `data/history/` and the bridge's `HISTORY`
message both carry it), so that half of v2 could be studied today; the spread half cannot until P6
lands.

**The sequencing question this document must state honestly:** v1's lockout premise failed for
SilverBullet *specifically*, not for anomaly-based lockouts as a category. SilverBullet's edge is
session-timed (fires inside a configured or wide-open NY-time window per
`docs/strategies/silver-bullet.md` §3) — its entries are scheduled by clock, not by market
geometry, so they have little reason to coincide with a geometric-anomaly flag in the first place.
v2's value proposition rises specifically as the arsenal adds strategies whose entries are *not*
session-timed but geometry- or breakout-timed — the brainstorm's own Coil, Tide, and Aftershock
concepts (Aftershock in particular: brainstorm §2, a Hawkes cascade trader that fires on
range-expansion events, which is structurally close to the bar-shape anomalies Antibody scores) are
exactly the kind of entries that would overlap with anomaly windows by construction, unlike
SilverBullet. Until at least one such non-session-timed strategy exists and is live or in backtest,
a v2 overlap study has nothing better to test against than v1 already tested, and would likely
reproduce the same n≈1 problem for the same structural reason.

## 7. Failure modes and monitoring

- **False alarms during benign vol expansion** (brainstorm §10 item 10) — costs opportunity (a
  blocked entry that would have been fine), not capital; asymmetrically safe by design. The 0.05%
  measured alert rate (vs a 2% design cap) suggests this is not currently a practical concern, but
  that was measured on the geometric-only v1 feature set — v2's added features could shift the rate
  and must be re-checked against the same 2% cap criterion.
- **Feature drift** — quarterly refit is the designed mitigation (matches the discipline used for
  Trinity's HMM, `trinity.md` §3, §7).
- **Anomaly detected after the damage** — a single flash bar can only be flagged *after* it closes;
  Antibody protects subsequent bars, not the flash bar itself. This is stated as an honest,
  accepted limitation in the source brainstorm (§10 item 10), not a defect to fix.
- **Benefit is hard to measure** (brainstorm §10 item 11) — avoided losses are counterfactual; if
  ever wired into live blocking, the only real evidence of value will be comparing realized drawdown
  in ALERT-adjacent periods against a shadow-mode run where Antibody scored but did not block,
  logged for later comparison.
- **Live self-audit metrics (if wired into blocking):** ALERT frequency vs the 2% design cap (a
  live version of criterion #1); count of entries actually blocked vs would-have-been-taken, logged
  so the counterfactual in the point above is measurable rather than purely hypothetical; Telegram
  delivery of every ALERT transition (§4) as a standing ops signal independent of any blocking
  decision.

## 8. Verdict and sequencing

**Record v1 as complete and NO-GO for the SilverBullet lockout premise specifically** — the scorer
works (criterion #1 passed cleanly, covariance well-conditioned across all 9 symbols), the overlap
with SilverBullet's entries does not exist (criterion #2 failed at n=1 of 1,386, criterion #3 moot).
Do not re-run v1 against SilverBullet expecting a different answer from more data; the finding is
structural, not a sample-size artefact.

**Ship the Telegram alert-state telemetry now**, independent of everything else in this document —
it is a small, low-risk addition to `src/ops/telemetry.py` (§4, §5) with immediate operational value
(visibility into flash events, feed pathologies, liquidity holes) and does not depend on the lockout
premise ever being adopted for any strategy.

**Defer v2 (tick-volume z + spread z) until two things are true:** (1) P6 (real spread capture)
lands, and (2) at least one non-session-timed strategy (Coil, Tide, or Aftershock-shaped) exists in
backtest or live, giving v2's overlap study something structurally different to test than what v1
already tested and NO-GO'd. Building v2 before either is ready would likely reproduce v1's n≈1
result for the same underlying reason and waste the study cycle. This document does not assume
v1's code is merged; that is a separate, small integration decision (§5) independent of the v2
research question.
