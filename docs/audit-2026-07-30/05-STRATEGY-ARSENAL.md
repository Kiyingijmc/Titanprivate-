# Titan — Strategy Arsenal Design Brief

**Seven candidate strategies and one control experiment, designed against this bot's measured constraints.**

**Companion to:** `02-AUDIT-REPORT.md` · `04-REMEDIATION-ROADMAP.md` · `06-PRE-REGISTRATION-TEMPLATE.md`
**Prepared:** 2026-07-30

> **Gating statement.** Nothing in this document should be built before Stage A of the remediation roadmap is complete, and no strategy should be deployed before Stage B. A new strategy on an unenforced risk baseline multiplies the existing exposure rather than diversifying it.

---

## 1. The three constraints that determine the menu

Everything below is derived from the repository, not from generic strategy design.

### 1.1 Your cost gate dictates a minimum stop distance, and it is larger than intuition suggests

From `scripts/poc_sb_stops.py:43` — the authoritative table both research rigs import:

```
EURUSD 8 · GBPUSD 12 · USDJPY 10 · AUDUSD 10 · USDCAD 12
GBPJPY 25 · XAUUSD 20 · US30 200 · BTCUSD 1000 · XBRUSD 30
COMMISSION_USD_PER_LOT = 7.0
```

*(US100, ETHUSD and XTIUSD are still absent — finding STRAT-04. XTIUSD's median was separately measured at 2 points, `config.yaml:126`.)*

**Worked example, EURUSD:** spread 8 ticks + commission ≈ 7 tick-equivalents ≈ **15 ticks = 1.5 pips round trip.** Your a-priori gate is cost ≤ 0.25R, therefore:

> **R ≥ 60 ticks = 6.0 pips minimum stop on EURUSD.** Anything tighter is dead before a line of code is written.

| Stop basis | EURUSD stop | Cost as fraction of R | Verdict |
|---|---|---|---|
| 1.0 × ATR(H1) ≈ 12 pips | 12 pips | **0.125R** | Comfortable |
| 1.0 × ATR(M15) ≈ 5 pips | 5 pips | 0.30R | Marginal |
| 1.0 × ATR(M5) ≈ 2.5 pips | 2.5 pips | **0.60R** | Hopeless |
| 0.2 × ATR(M5) — the original SilverBullet | 0.5 pips | **3.0R** | **This is precisely how it died** |

**The design rule that follows:** on M15 and below, the stop must be **structural and wide** — a range width, an opening-range width, a swing extreme — **never a small ATR multiple.** Your own falsified research proved this the expensive way. Every strategy below respects it by construction.

**The corollary is counter-intuitive but important:** the cost-friendliest instruments are the *high-volatility* ones. BTCUSD's 1000-tick spread sounds brutal until divided by an H1 ATR of several hundred dollars. **US30, US100, XAUUSD and BTCUSD have the best volatility-to-cost ratios in your universe and are your only realistic intraday candidates.**

### 1.2 You have three years of M5 data and nothing else

`data/lake/frozen/PROVENANCE.md`: source is `data/history/<SYM>_M5.csv`, ~2023-06 to 2026-06, resampled to H1. And `collect_signals:69` only knows `{"M15": "15min", "H1": "1h"}` — **H4 and D1 raise `KeyError` today.**

| Timeframe | Bars/symbol (3 y) | Validatable? |
|---|---|---|
| M5 | ~150,000 | n ✓, costs ✗ |
| M15 | ~50,000 | n ✓, costs marginal |
| **H1** | **~18,600** | **✓✓ — this is why H1 was the survivor** |
| H4 | ~4,650 | ✓ if the signal is frequent |
| D1 | **~775** | ✗ — cannot validate anything |

**That H1 was the timeframe that worked is not a coincidence.** It is the only band where your sample size and your cost structure are simultaneously satisfied.

> **Prerequisite project:** D1 strategies are not off the table, but they require a data acquisition project first — and it is cheap. MT5's own D1 history typically runs 15–25 years and pulls in minutes through the `GET_HISTORY` command you already have. **One afternoon unlocks an entire timeframe and three of the strategies below.**

### 1.3 Your edge is the exit engine, not the entry

The stop study is unambiguous:

| Configuration | Expectancy |
|---|---|
| Fixed 2R exits | **−0.122R** |
| Ratchet | +0.087R |
| Ratchet + runner | **+0.109R** (→ +0.194R after the cost screen) |

**The management layer contributes +0.316R — more than three times the final expectancy.**

Which means the design objective for a new entry signal is **not** "high win rate" or "clean pattern." It is:

1. **Cost ≤ 0.25R by construction** (structural stops)
2. **Positive skew potential** — the ratchet monetises trades that run; it cannot rescue trades that chop
3. **Enough n** — 300+ trades per symbol over 3 years, or the Wilson interval swallows the result
4. **A directional thesis with a defined invalidation** — the runner needs somewhere to run *to*

**Any entry meeting those four constraints inherits +0.316R of proven machinery.** That is an enormous head start, and it is why a fresh strategy on this platform is far cheaper to develop than the first one was.

---

## 2. EXP-0 — The experiment to run before anything else

### "Coin Flip": the ratchet on random entries

The hypothesis "the edge is the exit engine, not the entry" is **directly falsifiable, cheaply, with code you already have.** Generate random entries matched to SilverBullet's frequency, symbol distribution, direction balance and stop geometry, and run them through the same ratchet+runner replay.

| Outcome | Interpretation |
|---|---|
| Random + ratchet ≈ **−0.10 to −0.15R** (≈ the fixed-exit baseline) | The ratchet is a *skew transform* requiring a real signal. SilverBullet's entry is doing genuine work. **Proceed with the arsenal as designed.** |
| Random + ratchet ≈ **0.00R** | The ratchet neutralises cost drag but adds no alpha alone. The entry signal is worth ~+0.19R. **Healthy result.** |
| Random + ratchet **> 0** | **The entry is decoration.** Any signal producing the right trade frequency and stop geometry works. Every strategy below collapses into "pick a frequency and a stop width", and the research programme should pivot entirely to exit-engine parameterisation. |

**Effort: 1 day.** `poc_sb_stops.replay_managed` already exists; you need only a random signal generator with matched marginals.

**There is no other single day of work in this project with a comparable chance of reframing everything** — and the third outcome is not far-fetched, because a positively-skewed exit rule applied to a random walk with wide stops and partial banking genuinely can produce a positive R distribution in trending regimes.

---

## 3. The arsenal at a glance

Ordered by **cost of validation**, not attractiveness — your bottleneck is research throughput, not ideas.

| # | Name | TF | Return source | Entry | Aggression | Infra cost | Expected corr. to SilverBullet |
|---|---|---|---|---|---|---|---|
| 1 | **Coil** | H1 | Volatility clustering | STOP (both sides) | ●●○○○ | **Low** | Low (+0.1) |
| 2 | **Tide** | H1 | Short-horizon reversal | LIMIT | ●●●●○ | **Low** | **Negative (−0.2)** |
| 3 | **Bell** | M15 | Session liquidity / ORB | STOP | ●●●●● | Medium | Low (+0.15) |
| 4 | **Anchor** | H4 → D1 | Time-series momentum | MARKET | ●○○○○ | Medium | Moderate (+0.3) |
| 5 | **Tether** | H1 | Relative value | LIMIT ×2 | ●●○○○ | **High** | ~Zero |
| 6 | **Ledger** | D1 hold | Carry | MARKET | ●○○○○ | Medium | ~Zero |
| 7 | **Almanac** | D1 → H1 | Calendar flow | MARKET | ●○○○○ | **Trivial** | ~Zero |

---

## 4. COIL — Volatility-Compression Expansion (H1)

**Build this one first.** Best ratio of evidence base to infrastructure cost in the set.

### Thesis
Volatility clusters — the single most robust empirical regularity in asset prices, documented since Mandelbrot (1963) and underpinning the entire GARCH literature. Periods of unusually compressed range are followed by expansion, and the *direction* is revealed by which side breaks. **You do not predict direction; you let the market declare it and are positioned either way.**

### Why it fits this bot specifically
- **H1** — your validated band, existing CandleMaker, no data work
- Stop is the **compressed range width** — structurally wide. Cost gate satisfied by construction
- Breakouts have naturally fat right tails — **the best possible input to the runner.** Fixed-2R exits would waste exactly what this signal produces
- **STOP orders are already supported end to end** (`system_controller.py:640`, `Titan_Gateway.mq5:139–144`) and currently unused by any strategy

### Mechanics (pre-registration draft)
```
Setup:    ATR(14,H1) in its bottom 25th percentile of the trailing 200 bars
          AND max(high) − min(low) over the last 4 bars < 1.2 × ATR(14)
Trigger:  BUY  STOP at range_high + 0.15 × range_width
          SELL STOP at range_low  − 0.15 × range_width
Stop:     opposite side of the range, floored at 0.8 × ATR(14,H1)
Target:   ratchet + runner (inherited)
OCO:      on one fill, cancel the other        ← see prerequisite P2
Expiry:   4 bars unfilled → cancel
Filter:   spread ≤ 0.15 × planned stop distance ← needs the ask price (RISK-07)
Universe: all 12 (all pass the cost gate at H1)
```

### Expected profile
Win rate 35–42% · average winner 2.5–4R · expectancy target ≥ +0.15R net · roughly 250–400 trades/symbol over 3 years. Losses cluster in range-bound regimes — **expect long flat stretches punctuated by good months.** Decide you can tolerate that psychological profile *before* you fund it.

### Architecture prerequisite — new, and it matters
**OCO (one-cancels-other) does not exist.** Nothing pairs two pending orders. Filling one leg while the other rests means a hedged position on one symbol, which `max_positions_per_symbol: 1` will *reject* at the arbiter — so the second leg is blocked rather than cancelled, and rests until TTL. **You need explicit OCO in `state_manager` (a `sibling_ticket` column) plus cancel-on-fill in the `EXECUTION:OPENED` handler.** ~1 day. Bell needs it too.

### Kill criteria
OOS expectancy < +0.05R net · or fails at 1.5× spread · or fewer than 3 of 4 calendar years positive · or > 60% of P&L from one symbol.

---

## 5. TIDE — Intraday Overextension Reversal (H1)

**The portfolio play.** Its value is less its standalone expectancy than its **negative correlation to everything else you own.** SilverBullet is continuation, Coil is expansion, Bell is breakout — all three lose in mean-reverting chop. **Tide is the only thing in the arsenal that makes money there.**

### Thesis
Short-horizon reversal is well documented in FX (the intraday literature on order-flow-driven overshoot and subsequent correction) and is mechanically distinct from multi-day momentum. **Statistical, not pattern-based — deliberately**, because your ICT falsifications suggest pattern recognition on this data does not survive costs.

### Mechanics
```
Setup:    close in the top/bottom 5% of the developing session range
          AND session range ≥ 1.5 × ADR(20)
          AND no H4 momentum agreement (fade exhaustion, never trend)
Trigger:  LIMIT at close ± 0.3 × ATR(14,H1), retracing INTO the range
Stop:     session extreme ± 0.5 × ATR(14,H1)   ← structural
Target:   session mid-range as anchor; ratchet manages the path
Session:  exclude the first 2 bars after any major open (Bell's turf)
Universe: FX majors + XAUUSD.
          EXCLUDE indices and crypto — they trend intraday, and reversal
          signals there are on the wrong side of a real drift.
```

### Expected profile
Win rate 55–65% · average winner 1.0–1.5R · expectancy target ≥ +0.10R.

**This one deliberately violates design constraint #2.** Reversal has *negative* skew, so the runner adds little and the partial-banking stages carry the load. That is the correct trade-off for a diversifier, but it means **Tide needs its own exit variant: bank earlier, trail tighter, no runner.** Test both ways — the ratchet is calibrated on a continuation signal and must not be assumed transferable.

### Honest risk
Reversal strategies are how accounts die when a regime breaks. The stop must be absolute and position size must never scale up after a loss. **Given RISK-01 (drawdown anchor resets on restart) is still open, do not run Tide live until that is fixed.** It is the strategy most exposed to that specific bug.

### Kill criteria
Any single realised loss exceeding 1.5R (stops are not holding) · OOS expectancy < +0.05R · or correlation to SilverBullet's monthly P&L above +0.3 (defeats the entire purpose).

---

## 6. BELL — Index Session Opening-Range Breakout (M15)

**The aggressive slot,** and the only credible way to trade M15 on this broker.

### Thesis
Opening-range breakout has a genuine, recently re-documented empirical basis — Zarattini & Aziz's 2023 work on ORB in liquid equity instruments revived a strategy family that had been written off. The mechanism is plausible: overnight information accumulates and resolves into directional flow in the first period of liquid trading, and that flow exhibits short-horizon continuation.

### Why M15 works here and nowhere else in the set
The stop is the **opening-range width**, not an ATR multiple. On US30 an opening 30-minute range is routinely 60–150 index points against a 200-tick (≈2 point) spread — **a cost fraction of ~0.03R. This is your cheapest R in the entire universe.**

### Mechanics
```
Universe: US30, US100, XAUUSD, BTCUSD ONLY.
          FX majors excluded — opening ranges too narrow relative to spread.
Setup:    OR = high/low of the first 2 × M15 bars after the NY equity open
          (US/Eastern, DST-aware — get_current_ny_string is already correct)
Trigger:  STOP at OR_high + 0.1 × OR_width  /  OR_low − 0.1 × OR_width
Stop:     opposite OR extreme   ← structural, wide, cost-friendly
Filter:   OR_width between 0.5× and 2.0× the 20-day median OR
          (skip both dead opens and news-gap opens)
          AND no high-impact release within 30 min
          (news_manager exists but is USD-only — extend it)
Expiry:   unfilled 90 min after open → cancel. Time-stop at session close.
OCO:      required (shared with Coil)
```

### Expected profile
Win rate 33–40% · average winner 2.5–4R · ~1 signal per instrument per day → **~750 trades/instrument over 3 years.** Excellent n, excellent skew, ideal runner input. **Highest variance in the arsenal; also the highest ceiling.**

### Architecture prerequisites
- **M15 CandleMaker does not exist** — `data_store.py:25–28` creates M5 and H1 only, and an M15 manifest silently produces zero signals (finding ENTRY-03). A 20-minute fix that also closes an open finding.
- The session gate must key off **bar time, not wall clock** (ENTRY-02). Inert today, but Bell depends entirely on session anchoring and will diverge between live and backtest without it.
- Extend `news_manager` beyond USD.

### Kill criteria
OOS < +0.10R — **a higher bar than the others, because its variance is higher** · or median realised slippage on stop entries exceeding 0.1R. **Stop orders slip, and your backtester models none of it (STRAT-03). Measure this on demo before believing any backtest of Bell.**

---

## 7. ANCHOR — Diversified Time-Series Momentum (H4 now, D1 later)

**The most evidence-backed strategy in the set, and the one you can least validate today.**

### Thesis
Time-series momentum is arguably the best-documented anomaly in finance — Moskowitz, Ooi & Pedersen (2012) found it across 58 instruments and four asset classes; Hurst, Ooi & Pedersen extended the evidence back roughly a century; it underpins the entire managed-futures industry.

**It is not what your Donchian-20/D1 test falsified.** Your own note says that variant was "too fast, weak" and confirmed cost-robust structure at −0.1 to −0.25R. **Twenty days is short-term reversal territory; the documented momentum effect lives at 3–12 months. You tested the wrong horizon and correctly diagnosed it.**

Two further reasons your test understated it: TSMOM's edge is overwhelmingly a **portfolio** effect — it needs 10+ instruments across asset classes with **volatility-scaled sizing** so each contributes equal risk — and your rigs test per-symbol and pool R (finding STRAT-05). **Single-instrument TSMOM has a poor Sharpe even when the portfolio version works well.**

### Mechanics
```
Signal:   sign of the 63-bar (H4 ≈ 10 days) or 126-day (D1 ≈ 6 months) return
          confirmed by price above/below its own EMA(50) on the same TF
Entry:    MARKET on the confirming bar close
          (no passive entry — TSMOM cannot afford to miss the defining move)
Stop:     3.0 × ATR(20) on the signal TF   ← very wide; every symbol clears costs trivially
Sizing:   inverse-volatility weighted so each position contributes equal risk
Exit:     signal flip, or the trailing component of the ratchet.
          NO fixed target — the premise is capturing the fat right tail.
Hold:     weeks. Expect 1.5–4% of bars in a position.
Universe: all 12 — this is the one strategy that WANTS breadth
```

### The data problem, stated plainly
H4 gives ~4,650 bars/symbol over three years — enough to see something, not enough to trust it, and three years contains roughly one macro regime. D1 gives **775 bars/symbol, which cannot validate anything.**

> **Do the D1/H4 data extension before deciding whether Anchor is real.** Testing a 6-month momentum signal on three years of data and concluding it does not work would be the same category of error as the Donchian test.

### Expected profile (from the literature, not from your data)
Win rate 35–45% · average winner 3–6R · portfolio Sharpe 0.4–0.7 · **positive skew and crisis-alpha characteristics that make it the natural counterweight to everything else here.** Also the strategy with the largest gap between single-instrument and portfolio performance — exactly what your current rig cannot measure.

### Kill criteria
After the data extension: portfolio-level (not pooled) Sharpe < 0.3 on 15 years · or fewer than 60% of instruments positive · or maximum drawdown duration exceeding 24 months — **survivable for an institution, probably not for you.**

---

## 8. TETHER — Cointegration Spread Reversion (H1, paired legs)

**Genuinely orthogonal. Genuinely expensive. Include it with clear eyes.**

### Thesis
Relative-value mean reversion between economically linked instruments is a distinct return source with no directional market exposure. Your universe contains natural candidates: **US30/US100** (both US equity beta, differing sector composition), **BTCUSD/ETHUSD** (near-identical crypto beta), and more loosely **XAUUSD/XTIUSD** and the dollar-side FX cluster.

**The elegant part:** `src/analysis/kalman_drift.py` (183 LOC) **already exists** and is currently used only by the research-status Gyroscope. A Kalman filter is the textbook estimator for a *time-varying* hedge ratio — precisely what a rolling OLS beta fails at and what makes naive pairs trading break. **You have already built the hardest component of this strategy for a different purpose.**

### Mechanics
```
Spread:  log(A) − β_t × log(B), β_t Kalman-estimated (reuse kalman_drift)
Setup:   |z-score of spread| > 2.0 over a 200-bar window
         AND the pair passed an ADF / Engle-Granger cointegration test
             on the trailing 500 bars
         AND β_t stability: Kalman innovation variance within its normal band
Entry:   LIMIT on both legs, notional-matched by β_t
Stop:    |z| > 3.5 (spread divergence) OR cointegration test fails on refresh
Target:  |z| < 0.5
Sizing:  combined-leg risk counts as ONE position against the risk budget
```

### The costs — four separate problems, stated honestly

1. **Doubled transaction cost.** Two legs in, two legs out. For US30/US100 still cheap; for anything FX it likely kills the edge outright.
2. **Two-leg execution is not atomic.** Your bridge sends orders one at a time with no idempotency key (ARCH-01). **A filled leg with an unfilled sibling is a naked directional position — the opposite of the strategy's premise.** This needs a real state machine, not a patch.
3. **The correlation gate will block it.** `check_correlation` is direction-blind (RISK-04) and blocks any pair above ρ = 0.8 — **which is definitionally every Tether pair.** RISK-04 must be fixed before Tether can execute at all.
4. **Cointegration breaks without warning**, and it breaks precisely when you are maximally positioned. Every historical pairs-trading blowup has this shape.

### Verdict
High intellectual appeal, real diversification value, **and stage it last.** It requires the position-lifecycle state machine, signed correlation, and OCO-equivalent multi-leg handling — 2–3 weeks of infrastructure for one strategy. **Worth doing after two cheaper strategies have proven the pipeline works.**

### Kill criteria
OOS Sharpe < 0.5 (relative-value strategies need higher Sharpe to justify complexity) · or Kalman β unstable on more than 20% of bars · or any leg-mismatch incident in the demo soak.

---

## 9. LEDGER — Carry Harvest with a Momentum Overlay (D1 hold)

**The most diversifying idea here and the one I am most skeptical of. Cheap to falsify — do that first.**

### Thesis
The carry premium is one of the most robustly documented return sources across asset classes (Koijen, Moskowitz, Pedersen & Vrugt, 2018; the FX carry literature from Lustig & Verdelhan onward). Long high-yielders, short low-yielders, harvest the differential, accept periodic crash risk. **In an MT5 CFD account carry is expressed directly as swap, credited or debited nightly.**

### Why I doubt the retail implementation
The academic premium is computed on interbank forward points. **Your broker inserts itself:** FBS quotes swap on both sides with a markup, so the long-side credit is systematically smaller than the short-side debit, and the retail trader captures a fraction of the differential — sometimes a negative fraction. Brokers also revise swap rates without notice and apply triple swap on Wednesdays. **This is a case where a real academic anomaly usually does not survive the retail wrapper.**

### Step 0 — the falsification test (2 hours of code, 2 weeks of data)
```
Log SYMBOL_SWAP_LONG and SYMBOL_SWAP_SHORT nightly for all 12 symbols
via the EA (both are one SymbolInfo call away).
Compute, per symbol: annualised net carry if held long, and if held short.

GATE: does ANY symbol offer net positive carry exceeding 3% annualised
      after the broker's markup?

  If NO  -> stop. Delete the idea. Cost: 2 hours.
  If YES -> proceed to design.
```

### If a symbol survives
```
Signal:  net annualised carry > 3% AND D1 momentum agrees with the carry direction
         (carry without a trend filter is picking up pennies in front of a truck —
          this filter is the difference between the documented premium and 2008)
Entry:   MARKET, small size
Stop:    4 × ATR(20,D1) — very wide; you are paid to hold, not to be right quickly
Exit:    carry turns negative, or momentum flips
Hold:    weeks to months
```

### The bonus that justifies Step 0 regardless
**Your backtester models no swap at all** (finding STRAT-06), which means every current strategy holding overnight carries an unmodelled cost. **The swap survey is worth doing purely as data collection for the existing system**, whether or not Ledger ever ships. XTIUSD, ETHUSD and BTCUSD are your longest-carry exposures, and your runner deliberately holds positions past their targets.

### Kill criteria
The Step-0 gate. **Most likely outcome: it fails, you have spent two hours, and you have simultaneously produced the swap table your backtester has been missing. That is a good trade even when the strategy dies.**

---

## 10. ALMANAC — Turn-of-Month Index Overlay (D1 decision, H1 execution)

**Not really a candidate. A yardstick — and arguably the most useful item here after EXP-0.**

### Thesis
The turn-of-month effect in equity indices — outperformance concentrated in the last trading day and first three of a calendar month, attributed to pension and payroll flow — is among the oldest documented calendar anomalies (Ariel, 1987; Lakonishok & Smidt, 1988). **It has partially decayed since publication, as anomalies do, and any honest treatment must say so.**

### Mechanics
```
Signal:    long US30 and US100 from the close of the last trading day of the month
           through the close of the third trading day of the next
Entry:     MARKET at the H1 close
Stop:      2 × ATR(20,D1) — protective only, not the exit mechanism
Exit:      time-based
Frequency: 12 per year per instrument → 36 observations over 3 years of data
```

### Why to build it anyway — two reasons, both epistemic

**1. It is a complexity baseline.** Almanac has **zero fitted parameters** — a calendar rule and a protective stop. **If a strategy with fourteen tunable parameters cannot beat a rule with none, net of costs, on the same data, it has not earned its complexity.** Every future candidate should be reported *against Almanac*, and this belongs in your pre-registration template as a standing requirement. Most retail systems never adopt this discipline; it would have caught at least two of your four falsified ICT strategies faster.

**2. It is your end-to-end integration test.** Signals are known months in advance, so live-vs-backtest divergence is **unambiguously an infrastructure bug** — not a strategy question. Almanac diverging means your clock, your session logic, your order path, or your journal is wrong. **That makes it the perfect first strategy to deploy on the demo soak, because it distinguishes engineering failures from strategy failures — which nothing else in your arsenal can do.**

n = 36 means Almanac can never be *validated* on current data. With the D1 history extension from Anchor, n = 240 and it becomes a genuine if modest candidate.

**Effort: half a day. Build it for reason 2 alone.**

---

## 11. Portfolio construction

### Expected correlation structure
*(priors to be measured, not results)*

| | SilverBullet | Coil | Tide | Bell | Anchor | Tether | Ledger |
|---|---|---|---|---|---|---|---|
| **SilverBullet** | 1.0 | | | | | | |
| **Coil** | +0.1 | 1.0 | | | | | |
| **Tide** | **−0.2** | **−0.3** | 1.0 | | | | |
| **Bell** | +0.15 | +0.35 | −0.25 | 1.0 | | | |
| **Anchor** | +0.3 | +0.2 | −0.35 | +0.2 | 1.0 | | |
| **Tether** | ~0 | ~0 | +0.1 | ~0 | ~0 | 1.0 | |
| **Ledger** | ~0 | ~0 | ~0 | ~0 | **+0.4** | ~0 | 1.0 |

**The structure to notice:** Tide is negatively correlated with the entire continuation/expansion cluster, making it the **highest-value diversifier despite probably having the weakest standalone expectancy.** Meanwhile Coil, Bell and Anchor are all *long volatility and long continuation* — they will have good months together and bad months together. **Running all three at full size is one bet, not three.**

### Risk budgeting once more than one strategy is live

| Strategy | Risk/trade | Max concurrent | Notes |
|---|---|---|---|
| SilverBullet | 0.75% | 3 | Incumbent, expectancy still unmeasured (STRAT-01) |
| Coil | 0.50% | 3 | **Share the count budget with SilverBullet** — both are continuation |
| Tide | 0.50% | 2 | Never scale after losses |
| Bell | 0.35% | 2 | Highest variance; smallest unit |
| Anchor | 0.35% | 6 | Small per position, wide breadth — that is the point |
| Tether | 0.35% | 2 pairs | Counts as one position per pair |
| Ledger | 0.25% | 3 | Long hold, low urgency |
| **Aggregate ceiling** | **3.0%** | **8** | **Down from the current 5% / 6** |

**Note the reduction.** `max_total_open_risk_pct: 5.0` was calibrated for one strategy with a per-symbol cap. **Seven strategies competing for capital through an arbiter with direction-blind correlation checking (RISK-04) and count gates blind to pending orders (RISK-02) is materially riskier at the same nominal cap. Tighten the aggregate as you add breadth, not loosen it.**

---

## 12. Architecture prerequisites — the honest bill

The strategies above are not the work. **This is.**

| # | Prerequisite | Needed by | Effort | Also fixes |
|---|---|---|---|---|
| **P1** | M15 + H4 + D1 CandleMakers from configured TFs | Bell, Anchor, Tide | 4 h | **ENTRY-03** |
| **P2** | **OCO pending-order pairs** (`sibling_ticket`, cancel-on-fill) | Coil, Bell | 1 d | — |
| **P3** | Pendings counted in exposure and arbiter caps | **All** | 1 h | **RISK-02** |
| **P4** | Signed, fail-closed correlation + asset-class groups | All; **Tether cannot run without it** | 2 d | **RISK-03/04/05** |
| **P5** | Bar-time (not wall-clock) session gating | Bell, Tide | 4 h | **ENTRY-02** |
| **P6** | Ask price captured; spread gate live | All — it *is* the cost gate | 1 h | **RISK-07, STRAT-03** |
| **P7** | Per-strategy exit profiles (Tide needs no runner; Anchor no fixed target) | Tide, Anchor | 1 d | — |
| **P8** | **Grading path for non-SMC signals.** `signal_grader` is SMC-specific; a Coil or Bell signal has no grade, and `min_grade: B` gates on it | All new strategies | 1 d | — |
| **P9** | **Cross-strategy arbitration.** Two strategies wanting the same symbol; `max_positions_per_symbol: 1` currently makes that impossible | Any 2 concurrent | 2 d | — |
| **P10** | 15–20 y of D1/H4 history + `collect_signals` H4/D1 rules | Anchor, Ledger, Almanac | 1 afternoon | **Unlocks 3 strategies** |
| **P11** | Swap model in `trade_dollars` | Ledger; also corrects every existing overnight strategy | 4 h | **STRAT-06** |
| **P12** | Portfolio-level backtest (count cap, aggregate cap, correlation gate, daily breaker) | **Any multi-strategy claim** | 3 d | **STRAT-05** |
| **P13** | Position-lifecycle state machine + multi-leg | Tether only | 3 d | EXIT-01, EXIT-04, OBS-01, OBS-04 |

**Roughly two weeks of infrastructure before the first new strategy is testable, and P12 is non-negotiable before any multi-strategy expectancy claim.**

**Note how many are audit findings you already owe.** P3, P4, P5, P6 and P12 are not strategy work — they are Stage A/B work with a new justification.

---

## 13. Staging

| Stage | Duration | Content |
|---|---|---|
| **0 — Now** | 1 day | **EXP-0 (Coin Flip).** Nothing else starts until you know whether entries matter |
| **1 — With Stage A/B** | 2 weeks | P1, P3, P5, P6, P8, P10, P11 (all audit debt anyway). Build **Almanac** as the integration canary; run it on the demo soak alongside SilverBullet |
| **2 — First real candidate** | 2 weeks | P2, then **Coil.** Full pre-registration. **This is your pipeline dress rehearsal — the goal is a trustworthy process, and a falsification is a successful outcome** |
| **3 — The diversifier** | 2 weeks | P4, P7, then **Tide.** First strategy that could improve portfolio Sharpe even with mediocre standalone numbers |
| **4 — Data unlock** | 2 weeks | With P10 done: **Anchor** on 15+ years, portfolio-level, vol-scaled. Run **Ledger Step 0** in parallel — two hours, produces the swap table regardless |
| **5 — Aggression** | 2 weeks | P9, P12, then **Bell.** Only after the portfolio machinery can measure what adding it does |
| **6 — Optional** | 3 weeks | P13, then **Tether.** Only if Stages 2–5 produced at least two survivors and you want relative value |

**Calendar: ~3 months to a genuine multi-strategy portfolio.** Stages 1–3 are almost entirely work you already owe.

---

## 14. Panel disagreements

### Seven strategies, or two?

- **Risk officer:** *Two, maximum.* You have one strategy whose live expectancy is unmeasured and a history of six falsifications. Seven parallel research tracks on a platform that cannot yet verify a stop moved is how STRAT-01 stays open for another year. **Coil and Tide. Nothing else until SilverBullet has a measured live number.**
- **Systems architect:** *The count is not the risk — sequencing is.* These are seven pre-registrations, not seven live strategies, and ~90% of the prerequisite work is audit debt that pays off regardless. **What would be genuinely dangerous is running them concurrently before P12 exists**, because you would have no way to attribute a drawdown.
- **Python engineer:** The marginal cost of the *seventh pre-registration* is near zero; the marginal cost of the *second concurrent live strategy* is P9 + P12, about a week. **Write all seven. Deploy at most two.**
- **Trader:** Be honest about the base rate. You have falsified four ICT variants, a Donchian trend variant, and mostly falsified MTF-PB. That is ~6 for 1. **Expect one or two of these seven to survive.** Seven registrations to get two survivors is a reasonable funnel; two registrations to get two survivors is wishful thinking.
- **Synthesis:** write all seven pre-registrations now — cheap, and it forces the return-source thinking. **Deploy Almanac (as a canary) plus at most one real candidate at a time until P12 exists.**

### Is Anchor worth the data project?

- **Trader:** *Yes, unambiguously.* TSMOM is the most documented anomaly in the asset-management industry, the return source institutions actually allocate to, and the only thing here with genuine crisis-alpha character. **Your Donchian test measured a 20-day signal — that is not momentum, that is noise.**
- **Architect:** Agrees on merit; notes the afternoon of data work unlocks three strategies and finally lets you compute Sharpe on a real equity curve rather than a trade sequence. **Do P10 for the infrastructure alone.**
- **Risk officer:** One reservation the enthusiasm skips: **TSMOM's drawdown duration is brutal — multi-year flat periods are normal and expected.** That is an institutional tolerance, not a retail one. **Anchor is only viable if you genuinely accept 18 months of nothing, and most people discover they do not at month nine. Decide before, not during.**
- **Synthesis:** do P10 regardless. Test Anchor properly. **Then sit with the historical drawdown-duration distribution for a week before deciding whether you can hold it.**

### Is Ledger a waste of time?

- **Security auditor:** The swap survey is a **broker-behaviour audit** with value beyond the strategy — you would learn how FBS prices your overnight risk, currently an entirely unmodelled cost on every runner position you hold.
- **Engineer:** Two hours, produces a table the backtester needs, and the gate is binary. **Even total failure is a net gain.**
- **Trader:** I would bet 80% it fails the 3% gate. **Take that bet — it is two hours.**
- **Unanimous:** run Step 0. Do not design past it until it passes.

---

## 15. Two things worth knowing before you build any of this

**1. Did EXP-0 change the picture?** If random entries plus the ratchet come out positive, most of this document becomes the wrong plan. The research programme would pivot from "find signals" to "characterise the exit engine's edge" — **a much cheaper and more interesting project.**

**2. What drawdown duration can you actually hold?** Coil and Bell will have 3–4 month flat-to-negative stretches *by construction.* Anchor may have 18. **That number is a personal constraint, not a technical one, and it determines which of these seven you should even attempt.**

> **The most common way a validated strategy fails is that its operator stops running it during the drawdown the backtest predicted.**
