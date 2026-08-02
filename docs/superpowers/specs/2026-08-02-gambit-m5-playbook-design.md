# Gambit — M5 session playbook (sub-scalping) — Design

**Date:** 2026-08-02
**Status:** Approved design (brainstorm complete); implementation plan pending
**Owner decisions baked in:** goals = diversification + intraday alpha the H1 book misses; universe = high-vol only; cadence = session-gated, flat by close; top-down = H1 BiasEngine only; playbook of independently-gated setups; v1 = 2 setups (Judas + Reprise).

## 1. What this is

Gambit is a single M5 strategy plugin holding a **playbook of independently-gated
setups** behind one shared chassis. The chassis owns everything common — session
windows, overnight-range bookkeeping, H1 top-down bias, the cost floor,
one-trade-per-symbol-per-session, flat-by-close. Setups are small detectors plugged
into it; each ships **disabled** and is only enabled by its own GO verdict.

V1 carries two mechanically complementary setups:

- **Gambit-J (Judas)** — reversal days: session-open liquidity sweep of the
  overnight range, then displacement back inside the range. Untested territory in
  this repo (zero prior mentions of Judas/Power-of-3).
- **Gambit-R (Reprise)** — trend days: the FVG-displacement continuation entry
  (gross-validated on M5: +0.415R gross, n=31,714, 2026-07-11 stop study),
  relocated to the habitat where its gross edge can survive costs.

Universe: **US30, US100, XAUUSD, BTCUSD** (ETHUSD/XTIUSD as research-only arms —
both passed the 2026-07-28 universe screen). Cadence target ≤ 2 pooled signals/day.
Diversification vs the H1 book comes from mechanism (J is a reversal model), hours
(intraday windows), and instruments.

## 2. Binding priors (why the design looks like this)

1. **M5 died on costs, not signal** (2026-07-11 SilverBullet stop study): gross
   +0.3…+0.45R on every TF; net at M5 −1.3R…−4.3R because tight ATR stops pay
   ~1.5 pips of spread+commission. Arsenal design rule: median round-trip cost
   ≤ 0.25R ⇒ stops must be **structural** (range widths, sweep extremes), never
   small ATR multiples at M5.
2. **Every prior "HTF bias → M5 entry" model was falsified**: ICT_OTE −0.158R
   (n=1,776), CRT −0.150R (n=1,882), MTF-PB −0.274R (n=11,533). Graveyard base
   rate ≈ 1 survivor in 9 attempts — expectation is set accordingly.
3. **High-vol instruments are the only realistic intraday habitat**
   (audit 2026-07-30): US30/US100/XAUUSD/BTCUSD have the best
   volatility-to-cost ratios; FX majors at M5 are the worst case.
4. **The entry must carry its own gross edge** (EXP-0, 2026-07-31): the
   ratchet/runner exit engine amplifies real signals (+0.231R) but does not
   subsidize noise (+0.075R on placebo). Gates run dual exit models.
5. **M5 is live-ready today**: M5 routing, 500-bar warmup, FeatureBus SMC
   enrichment, H1 bias context and the 12-bar (60-min) limit TTL all already work.
   No M15 CandleMaker exists, so an M5 strategy is *easier* to ship than M15.

## 3. Setup mechanics (precise rules)

### Shared chassis rules (both setups)

- Timeframe M5. Entries only inside session windows (NY time):
  **London 02:00–05:00**, **NY AM 08:30–11:00**. Windows are end-exclusive
  (matching the grader's killzone convention). Per-symbol window config:
  indices NY-only; XAUUSD and BTCUSD both windows.
- H1 bias filter: signal direction must equal the FeatureBus `smc.bias_context`
  bias (the controller's `honors_htf_bias` enforcement applies as usual).
- **Cost floor by construction:** per-symbol
  `min_stop_ticks = cost_floor_mult × (spread_ticks + commission_ticks)` with
  `cost_floor_mult = 4` — any setup whose structural stop comes out tighter is
  **skipped**, guaranteeing round-trip cost ≤ 0.25R before a trade exists.
- One trade per symbol per session window. If both setups fire on the same
  symbol in one window, first-triggered wins; on the same bar, Judas takes
  precedence (the rarer setup). The losing intent is journaled unexecuted.
- Pending-limit TTL: 12 M5 bars (existing 60-minute mechanism).
- **Flat-by-close:** every position carries a `flat_at` NY time (session end);
  the TradeManager closes anything still open at that time (new plumbing, §4).

### Gambit-J (Judas sweep-reversal)

1. Compute the **pre-session range** from the M5 frame (pure in-strategy
   computation, no new FeatureBus pack):
   - London session: prior 18:00 → 02:00 NY.
   - NY session: 02:00 → 08:30 NY.
2. After session open, price must **sweep** one range extreme — trade *strictly
   beyond* it (touching exactly is not a sweep).
3. Within **12 M5 bars** of the sweep, a **displacement candle**
   (body ≥ 0.8×ATR, SilverBullet's `BODY_MIN_ATR`) must **close back inside the
   range**, in the H1-bias direction (sweep of highs → bearish displacement →
   SELL, only when H1 bias is bearish; mirror for lows).
4. Entry: limit at the FVG edge of that displacement candle (SilverBullet's
   frozen entry mechanics).
5. Stop: **beyond the sweep extreme + 0.2×ATR buffer** — structural by
   construction.
6. Target: fixed **RR 2.0** primary. "Opposite side of range" is recorded as a
   robustness variant only, not the gated config.

### Gambit-R (SilverBullet-M5 Reprise)

The frozen, gross-validated entry — displacement candle (body ≥ 0.8×ATR)
creating an FVG in the bias direction, limit at the FVG edge, RR 2.0, TTL 12 —
with exactly three changes from the dead M5 original:

1. **STRUCT stop**: beyond the displacement structure + 0.2×ATR (the stop-study
   STRUCT model), instead of 0.2×ATR.
2. The **cost floor** above.
3. **Session windows + flat-by-close.**

R doubles as the scientific control for J: if both pass, mechanism diversity is
real; if only R passes, the habitat was the fix and J's doctrine added nothing.

## 4. Architecture & code layout

**New files:**

- `src/strategies/models/gambit.py` — the chassis. Extends `BaseStrategy`,
  `timeframe='M5'`, `pairs` = the high-vol set. `on_new_candle()`:
  session-window check → update pre-session-range state → ask each *enabled*
  setup for an intent → apply cost floor + one-per-session rule → return the
  standard decision dict (`{signal, type, price, sl, tp}` + `flat_at`).
- `src/strategies/models/gambit_setups.py` — `JudasSetup`, `RepriseSetup`; one
  small class each with a common interface
  `detect(smc_df, ctx, session_state) → intent | None`. Pure functions of their
  inputs, unit-testable in isolation. A future third setup (e.g. ORB, once
  Bell's fate is decided) is a new class + config block, no chassis change.

**Config (`config/config.yaml`):**

```yaml
gambit:
  enabled: false          # research-first; stays off until a GO
  pairs: [US30, US100, XAUUSD, BTCUSD]
  sessions: {london: ["02:00","05:00"], ny_am: ["08:30","11:00"]}
  symbol_sessions:            # which windows each symbol trades
    US30: [ny_am]
    US100: [ny_am]
    XAUUSD: [london, ny_am]
    BTCUSD: [london, ny_am]
  setups:
    judas:   {enabled: false, sweep_ttl_bars: 12, body_min_atr: 0.8, stop_buffer_atr: 0.2}
    reprise: {enabled: false, body_min_atr: 0.8, stop_buffer_atr: 0.2}
  cost_floor_mult: 4      # min stop = 4 × (spread+commission) ticks
  rr: 2.0
```

Each setup is enabled **individually** by its own GO — the chassis being on with
zero enabled setups is a valid (inert) state.

**Reused untouched:** FeatureBus `smc.enriched_df` (M5) + `smc.bias_context`
(H1 top-down), controller HTF-bias enforcement, SignalGrader journaling, the
Arbiter, RiskManager sizing, portfolio cap, TradeManager BE/partials, M5 routing
and warmup.

**New plumbing — `flat_at`:** strategies cannot close positions today (they only
emit entries). The decision dict gains an optional `flat_at` (NY-time string);
the controller stores it in `active_orders` metadata at registration (the same
send-time-metadata pattern trade management already relies on, with heartbeat
backfill), and TradeManager gains one check: if `flat_at` is set and NY now ≥
`flat_at`, issue `CLOSE_POS`. Strategy-agnostic, opt-in per trade, no schema
migration beyond a metadata field. SilverBullet never sets it and is untouched.

## 5. Risk & execution guardrails

- **Sizing/risk:** standard path — broker-spec-driven lot sizing, the 3% daily
  breaker, and the book-wide open-risk cap apply as-is. Gambit gets its own
  `risk_per_trade` at canary time (canary convention).
- **Live spread check:** at signal time, if `ctx['spread']` > 1.5× the assumed
  table spread (news blowout, open-auction spike), skip the signal — the live
  analogue of the gate's ×1.5 stress cell.
- **Overlap with the H1 book:** XAUUSD is shared with SilverBullet/Gyroscope.
  The Arbiter's per-symbol resolution plus the exposure cap govern this; no
  special-case code. Worst case: Gambit occasionally locked out of XAUUSD.
- **US100 spread gap (STRAT-04):** Phase 0 adds US100/ETHUSD/XTIUSD to the
  shared `SPREADS` table (`scripts/poc_sb_stops.py`, mirrored in
  `tests/backtest/backtest_engine.py`), closing the audit finding.
- **DST:** session windows are NY-time via the existing `time_math` machinery.

## 6. Research plan & gates

**Phase 0 — Data & harness prep.** Export 3y M5 for US100/ETHUSD/XTIUSD
(US30/XAUUSD/BTCUSD exist); add their spreads to the shared table. Build the
offline signal collector for both setups: new `scripts/poc_gambit.py` following
the `poc_sb_stops.py` pattern (its M5 path is proven; `research_run.py` stays
H1-only rather than growing a second scope now).

**Phase 1 — Kill-screen, per setup** (wave2-triage pattern): pooled N ≥ 150
(else INSUFFICIENT-N), bootstrap 95% CI on net-R excluding 0 (fixed seed),
majority of symbols positive, per-symbol cost sanity. Run separately for J and R
— a pooled screen over mixed mechanisms could hide a dead setup inside a live
one's edge.

**Phase 2 — Full 7-criterion gate, per surviving setup** (Gyroscope-2 template,
pre-registered before the run):

1. Pooled managed net > 0 at 1× spread **and OOS net ≥ +0.10R** (Bell-precedent
   higher bar for sub-H1 frequency); 70/30 chronological IS/OOS per symbol.
2. Pooled median round-trip cost ≤ 0.25R.
3. Pooled managed net ≥ 0 at ×1.5 spread.
4. Breadth ≥ 3 of 4 symbols non-negative net over the full period.
5. ±30% one-at-a-time parameter sweeps; ≤ 1 of 4 may flip the pooled-net sign.
6. Bootstrap 5% lower bound on per-trade net > −0.05R.
7. Calibration: ≤ 2.0 pooled signals/day.

**Dual exit models** (FIXED-R and MANAGED — EXP-0). Baselines: MaSlopeBaseline;
R serves as J's mechanism-vs-habitat control. **One-pass rule: any failure →
NO-GO, recorded in `docs/strategies/`, no re-tune.**

**Phase 3 — Demo canary.** Only GO'd setups get `enabled: true` on the demo
book; standard ~2-week checkpoint; grading journaled throughout. The research
gate runs without the grade filter (grades recorded); the adopt-time config
decides the live `min_grade` posture.

**Expectation:** at the graveyard base rate, the likely outcomes are one
survivor or zero. Zero survivors still yields a permanent arsenal record plus
the reusable chassis and `flat_at` plumbing.

## 7. Testing

TDD throughout, stdlib unittest, boundary-regression culture:

- **Setup detectors:** pre-session-range computation across the 18:00 NY day
  boundary and a DST transition; sweep boundary — touching the extreme exactly
  is *not* a sweep (strict inequality regression, like the Hawkes/s_lo cases);
  displacement body ≥ 0.8×ATR at the boundary; "closes back inside" strictness;
  sweep-TTL expiry at exactly 12 bars.
- **Chassis:** cost floor skips a too-tight stop; one-trade-per-symbol-per-
  session; window edges (bar at 05:00 excluded — end-exclusive); disabled
  setups never fire; both-setups-fire → first wins.
- **`flat_at` plumbing:** metadata survives registration + heartbeat backfill;
  TradeManager closes at/after `flat_at`, never before; trades without
  `flat_at` (SilverBullet) untouched — with a mutation check that deleting the
  guard turns a test red.
- **Harness:** determinism (fixed seed, same CSV → identical trade list);
  gate-criteria math unit-tested against hand-computed fixtures.

## 8. Out of scope (v1)

- ORB/Bell-on-M5 setup (kept as a possible future setup; Bell's own M15
  pre-registration is untouched).
- D1/H4 narrative stack, daily-level (PDH/PDL) draws — H1 bias only.
- Range-opposite-side targeting as the primary exit (robustness variant only).
- Any change to `research_run.py`'s H1-only scope.
- EA/MQL5 changes: none required.
