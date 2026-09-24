# SilverBullet: entry, bias, grading and exit contribution

Date: 2026-09-16. Scope: source inspection plus a new diagnostic inside the
historical stop-study model. **Not a corrected backtest, live validation, or
GO/NO-GO gate.** No strategy, risk or execution settings were changed.

**Follow-up:** the [M5 execution diagnostic](2026-09-16-silverbullet-execution-diagnostic.md)
reverses the pooled results below to negative under both tested intrabar paths.
These legacy-model figures remain here for attribution and reproducibility;
they are not the current execution-adjusted research baseline.

The evidence supports investigating the entry and management together. It does
not support treating the exit engine as an independent source of profits, or
claiming that adding more filters necessarily improves portfolio returns.

## What the current strategy actually detects

`SMCAnalyzer._detect_fvg` requires the newest closed candle's body to be at
least 1.0 ATR. It then compares that candle with the candle two bars earlier:

- BUY: newest low exceeds the earlier high; limit at the newest low.
- SELL: newest high is below the earlier low; limit at the newest high.
- Initial stop distance is 1.0 ATR; initial target distance is 2.0 ATR.

The strategy's additional 0.8-ATR requirement cannot loosen the upstream
1.0-ATR gate. Displacement is tested on the **third/newest candle**, not the
middle candle. This is a particular gap-plus-displacement construction; it
does not establish institutional activity or order flow. There is no required
liquidity sweep, structure shift, or first-gap-per-session rule. Config enables
all hours on H1.

## How bias and grading interact

`BiasEngine` uses five bars on each side to confirm swing points. Two rising
swing highs and two rising swing lows produce BULLISH; both falling produce
BEARISH; mixed structure is NEUTRAL. The five right-side bars delay confirmation;
they are not future information when the engine is given only available bars.

The controller uses H1 context. For H1 SilverBullet, the so-called HTF filter
is therefore **same-timeframe structural context**, not an H4/D1 trend filter.
It vetoes opposing direction; it does not require positive alignment, because
NEUTRAL permits either side. Bias-engine exceptions also return NEUTRAL, with
a warning, so a context failure relaxes this directional veto.

At 2R and the effective 1-ATR displacement minimum, an aligned signal scores
at least 30 + 15 + 15 = 60, exceeding the B floor of 55 even before location
or session points. After the bias veto, grading therefore mainly filters the
neutral-bias population. The two filters are not independent confirmations.

## Existing entry placebo evidence

The EXP-0 registration contains completed results, and its stored CSV was
checked in this investigation (20 repetitions, seeds 11–30):

| Exit | Real SB, recorded | Placebo mean, recomputed from CSV |
|---|---:|---:|
| Fixed 2R | -0.122R | -0.324R |
| Ratchet | +0.087R | -0.267R |
| Ratchet + runner | +0.109R | -0.249R |

These are the old **11-symbol** universe, including GBPCAD and XBRUSD, not
the nine-symbol comparison below. Real returns were read from the registered
report; the placebo means were recomputed, not regenerated.

Within that experiment, real entries beat randomized entries and management
alone does not rescue the placebo. But the result does not isolate FVG
information cleanly:

1. `gen_placebo_signals` shuffles directions separately from the sampled
   signal's in-bar entry fraction. Real BUY entries are at bar lows and real
   SELL entries at bar highs; some placebos instead buy highs or sell lows.
   It preserves separate marginals, not their joint execution geometry.
   A synthetic check using the existing test fixtures and seed 11 produced
   12 such mismatches among 40 placebos. This is a code demonstration, not
   a count from the original historical run.
2. Volatility/regime placement is not matched, and duplicate placebo bar
   draws interact with one-order-at-a-time admission.
3. Both arms inherit the legacy fill and managed-replay limitations below.
   Shared implementation does not ensure equal bias across different entry
   populations.

Consequently, zero of 20 repetitions beating real SB should not be promoted
to a clean causal or calibrated significance claim about the FVG pattern.

## New controlled filter diagnostic

Runner: `scripts/sb_component_diagnostic.py`. The historical nine-symbol
cost-screen universe is fixed: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, GBPJPY,
XAUUSD, US30, BTCUSD. Full local history, approximately June 2023–June 2026;
USDJPY/AUDUSD/US30 end June 1, most other histories end June 24.

H1, ATR10 stop, 2R target, legacy costs, 12-bar pending TTL. Four candidate
filters are each applied **before** `resolve`, so a rejected candidate cannot
occupy a pending/position slot and prevent a later eligible candidate.
The production `SignalGrader` supplies arithmetic, using the old study's
fixed broker-minus-seven-hour clock and its existing bias/liquidity context.
No parameters were tuned and no gate verdict was defined.

| Admission rule | Candidates | Resolved trades | Fixed 2R | Ratchet | Runner | Tightened runner |
|---|---:|---:|---:|---:|---:|---:|
| Raw entry | 4,493 | 1,837 | -0.0442R | +0.1703R | +0.1950R | +0.2152R |
| Bias veto | 3,287 | 1,377 | -0.0029R | +0.1950R | +0.2199R | +0.2413R |
| Grade >= B | 3,263 | 1,398 | -0.0063R | +0.2062R | +0.2306R | +0.2524R |
| Bias veto + grade >= B | 2,837 | 1,209 | +0.0093R | +0.2193R | +0.2434R | +0.2657R |

Return columns are mean net R per resolved trade, not account returns.
The tightened runner uses the historical Arm C replay with giveback=0.75
and tight trail=0.10 of initial target distance. It approximates the enabled
configuration but does not execute the live TradeManager.

The raw runner result reproduces the old nine-symbol headline approximately
(+0.195R, n=1,837, PF=1.535); that is a consistency check, not independent
validation of the headline.

### Interpretation

- **The ratchet accounts for most of the modeled exit improvement.** On raw
  entries fixed→ratchet adds 0.2145R/trade; ratchet→runner adds 0.0246R.
  With both filters those increments are 0.2100R and 0.0241R. These are
  same-entry replay differences, not separately scheduled portfolio gains.
- **Filters improve per-trade selectivity in aggregate.** Both filters raise
  runner mean by about 0.0485R and PF from 1.535 to 1.692. They cut resolved
  trades by 34.2%, and total modeled runner R falls from 358.2 to 294.3.
  This is not evidence of greater total profit or better capital efficiency.
- **The bias filter is not uniformly beneficial.** Bias-only runner mean
  falls on GBPJPY (0.1885→0.1276R) and USDCAD (0.1800→0.1560R). No symbol
  selection or filter change follows from this exploratory observation.
- The grade-only and combined rows change the admitted entry population.
  They are not paired estimates on identical trades; simple differences of
  their means should not be interpreted as additive factor alpha.
- Existing post-resolution grade slices cannot answer the admission-policy
  question: deleting a completed trade afterward never admits the candidate
  that its pending order or position previously blocked.

## Why these figures do not validate the live strategy

1. **Fill trigger remains direction-blind:** the study requires
   `low <= entry <= high` on BID bars. It does not require ASK to reach a
   BUY limit and misses some gapped-through fills. This diagnostic deliberately
   leaves the historical resolver intact to isolate filters.
2. **Managed occupancy is wrong for a portfolio simulation:** `resolve`
   sets `busy_until` using fixed SL/TP exits; managed replays reuse those
   selected entries. A runner can remain open beyond that exit, or a ratchet
   can exit sooner. Thus managed arms can overlap positions or omit trades
   they should admit. Drawdown is deliberately omitted from the diagnostic.
3. **Context differs:** the study uses up to 100 H1 bars strictly preceding
   the signal timestamp; live uses the current H1 data-store window. The
   old fixed -7h grading clock also differs from the live NY clock.
4. **Intrabar path is unknown:** stop-first processing, partials exactly at
   levels, same-bar stage progression and extremum-based trailing do not
   reproduce executable tick paths, partial acknowledgments, lot rounding,
   the live break-even buffer or command cooldowns.
5. **Incomplete outcomes and costs:** fixed unresolved trades are dropped;
   managed open tails get zero remaining return. No slippage, swaps, dynamic
   spread, news restrictions, portfolio caps or cross-strategy arbitration
   are modeled.
6. **No fresh holdout:** these data were already used for strategy design.
   This diagnostic provides neither a new out-of-sample claim nor uncertainty
   intervals. It covers nine historical symbols, not today's twelve-symbol
   SilverBullet universe.

## Next experiment required for a stronger answer

Before changing trading rules, use an execution-consistent simulator that
admits orders chronologically and releases each slot at that exit model's
actual close. Correct bid/ask eligibility and gap handling, align closed-bar
bias/clock semantics with live, and test management event order on finer data.

Then repeat the filter/exit factorial on a frozen universe and holdout. For
entry attribution, preserve the **joint direction/entry-boundary relationship**
and match session, time period and volatility in placebo sampling. To isolate
FVG information from displacement information, separately remove each gate
while retaining explicitly defined entry geometry. Current EXP-0 randomizes
the combined setup and cannot distinguish those two components.

## Artifacts and verification

```bash
.venv/bin/python scripts/sb_component_diagnostic.py \
  --out data/results/sb_component_diagnostic_20260916
.venv/bin/python -m unittest tests.unit.test_sb_component_diagnostic \
  tests.unit.test_exp0_coinflip tests.unit.test_sb_overlay
```

The runner refuses to overwrite an existing output directory; use a new
directory for reproduction. Outputs: `trades.csv`, `summary.csv`, `run.json`
under the path above. Run card records history bounds, input/source SHA-256
hashes, counts and limitations. Local `data/results` artifacts are gitignored;
the aggregate results are preserved in this document.

Verification: **19 tests passed**, including neutral-bias behavior, grading
independence and a case where vetoing an unfilled pending order correctly
admits a later candidate. Existing placebo and overlay tests also passed.

Related records: `2026-07-11-silverbullet-h1-stop-study.md`,
`2026-07-30-fill-model-correction.md`,
`2026-07-31-exp0-coinflip-preregistration.md`.
