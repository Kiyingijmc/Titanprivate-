# Strategy Pre-Registration Template

**Purpose:** commit your hypotheses, parameters and kill criteria to git **before** running the research rig, so the honest version of the result is timestamped.

**How to use:**
1. Copy to `docs/research/prereg/YYYY-MM-DD-<strategy>.md`
2. Fill every section. Leave nothing as "TBD."
3. **Commit it. Record the SHA.**
4. *Then* run the rig.
5. Append the results section afterwards. **Never edit the sections above it.**

> **Why this exists.** Your stop study's own "Integrity caveats" section shows you already understand selection bias. This formalises that instinct into a procedure. The two additions to your current practice worth adopting are **H5 (the Almanac comparison)** and **the predicted result** — writing down what you expect before you look is the cheapest available check on whether you are discovering or rationalising.

---

```markdown
# PRE-REGISTRATION: <strategy name>

- **Date:** YYYY-MM-DD
- **Author:**
- **Git SHA at registration:** <sha>
- **Dependency lock hash:** <sha256 of requirements.lock>
- **Rig:** scripts/research_run.py  (NOT tests/backtest/backtest_engine.py — see finding STRAT-04)
- **Status:** REGISTERED / RUNNING / COMPLETE / FALSIFIED / DEPLOYED-RESEARCH / DEPLOYED-LIVE

---

## 1. Thesis — economic, not pattern

*Why should this pay? Name the participant on the other side of the trade and why they
are willing to lose. "Price often does X after Y" is a pattern, not a thesis. If you cannot
name a mechanism, say so explicitly — that is itself information.*

**Mechanism:**

**Who is on the other side, and why do they accept the loss:**

**Why should this persist rather than be arbitraged away:**

**Prior literature or internal research, if any:**

---

## 2. Return source

*Which of these does this strategy harvest? If it is the same source as a strategy you
already run, it is not a diversifier and must be justified on standalone expectancy alone.*

- [ ] Momentum / trend (time-series)
- [ ] Momentum (cross-sectional)
- [ ] Short-horizon reversal / mean reversion
- [ ] Volatility clustering / range expansion
- [ ] Liquidity provision / session flow
- [ ] Relative value / cointegration
- [ ] Carry
- [ ] Calendar / institutional flow
- [ ] Other: __________

**How this differs from every currently live and candidate strategy:**

**Expected correlation to each live strategy's monthly P&L (state a number, it will be checked):**

| Strategy | Predicted ρ |
|---|---|
| SilverBullet | |
| | |

---

## 3. Parameters — FIXED BEFORE RUNNING

*Any change to any value below constitutes a NEW registration with a new file and a new SHA.
Editing this table after a run is the single most common way a research programme fools itself.*

| Parameter | Value | Basis for this value | Varied in the grid? |
|---|---|---|---|
| Timeframe | | | |
| Entry trigger | | | |
| Stop rule | | | |
| Target / exit | | | |
| Filters | | | |
| Position sizing | | | |
| Max hold / TTL | | | |

**Total grid size:** ___ combinations
**Multiple-comparisons adjustment:** *(e.g. Bonferroni on the OOS threshold, or an explicit statement that the grid is small enough not to need one — and why)*

**Hardcoded constants that are really untested hyperparameters:**
*(Be honest here. Displacement thresholds, buffer pips, near-touch fractions, Fibonacci
levels — anything that could have been a different number.)*

---

## 4. Universe — chosen by a-priori cost screen ONLY

*Never select symbols by expectancy. That is the fastest route to an overfit universe.
Use the same screen the stop study used: median round-trip cost ≤ 0.25R.*

**Screen applied:**

| Symbol | Spread (ticks) | Commission (tick-equiv) | Planned R (ticks) | Cost / R | Pass? |
|---|---|---|---|---|---|
| | | | | | |

**Symbols included:**
**Symbols excluded, and why (cost only):**

---

## 5. Data

- **Source file(s):**
- **SHA-256 of each source:**
- **Date range:**
- **Bars per symbol:**
- **Resampling rule, if any:**
- **IS/OOS split — decided NOW:** ___% / ___%, chronological, split date ________

**Known data defects and how they are handled:**
*(e.g. the timezone seam — finding RISK-10; the forming bar in warmup history — ENTRY-04)*

---

## 6. Hypotheses — with numbers, decided in advance

| # | Hypothesis | Threshold | Result |
|---|---|---|---|
| **H1** | OOS expectancy ≥ | ____ R net | |
| **H2** | Calendar years positive | ___ of ___ | |
| **H3** | Survives spread stress | positive at 1.5× and 2.0× | |
| **H4** | Correlation to live strategies | < ____ | |
| **H5** | **Beats ALMANAC net of costs on the same window** | strictly greater | |
| **H6** | Symbols positive | ___ of ___ | |
| **H7** | Trade count sufficient | n ≥ ____ per symbol | |

> **H5 is a standing requirement.** Almanac has zero fitted parameters. If a strategy with
> fourteen tunable parameters cannot beat a rule with none, on the same data, net of costs,
> it has not earned its complexity.

---

## 7. Kill criteria — what result makes me DELETE this

*Written now, in advance. If you find yourself negotiating with these after seeing the
numbers, that is the bias this document exists to catch.*

- [ ]
- [ ]
- [ ]

**What I will NOT do if it fails:** *(e.g. "I will not re-run with a different stop model
and report only the survivor"; "I will not extend the universe to find a symbol that works")*

---

## 8. Predicted result — write it down before you look

*Calibration matters. Over several registrations this will tell you something useful
about your own judgement that no individual result can.*

- **Predicted OOS expectancy:** ____ R
- **Predicted win rate:** ____%
- **Predicted average winner:** ____ R
- **Confidence this survives all kill criteria:** ____%
- **What would most surprise me:**

---

## 9. Infrastructure prerequisites

*What must exist before this can be tested honestly, and before it can run live?*

| Requirement | Exists? | Audit finding ID | Blocking for test / live? |
|---|---|---|---|
| | | | |

---

## 10. Deployment gate

*Conditions for `status: research` → `status: live` in the manifest.*

- [ ] All hypotheses met
- [ ] No kill criterion triggered
- [ ] Signal-parity test committed with a golden fixture
- [ ] Exit profile validated against the LIVE `TradeManager`, not an offline replay *(finding STRAT-01)*
- [ ] Portfolio-level backtest run with the real risk gates *(finding STRAT-05)*
- [ ] ≥ 4-week demo soak at live sizing, with the journal recording exit reason and ratchet level *(finding OBS-01)*
- [ ] Realised spreads within 1.5× the assumed table, or the study re-run at measured values
- [ ] Correlation to live strategies confirmed within prediction
- [ ] Risk budget allocated and aggregate ceiling re-checked

---

# ==================== BELOW THIS LINE: FILL IN AFTER THE RUN ====================
# Do not edit anything above. If a parameter changed, start a new registration.

## 11. Results

- **Run date:**
- **Git SHA at run:**
- **Run-card path:**

| Metric | IS | OOS | Pooled |
|---|---|---|---|
| Expectancy (R) | | | |
| Profit factor | | | |
| Win rate (Wilson 95%) | | | |
| n | | | |
| Max drawdown (R) | | | |
| Max losing streak | | | |
| Bootstrap expectancy LCB | | | |

**Per-year:**
**Per-symbol:**
**Spread stress (1.5× / 2.0×):**
**Beats Almanac? (H5):**

## 12. Hypothesis outcomes

| # | Threshold | Actual | Met? |
|---|---|---|---|
| H1 | | | |
| H2 | | | |
| H3 | | | |
| H4 | | | |
| H5 | | | |
| H6 | | | |
| H7 | | | |

## 13. Prediction calibration

| | Predicted | Actual | Error |
|---|---|---|---|
| OOS expectancy | | | |
| Win rate | | | |
| Average winner | | | |

**What surprised me:**
**What that implies about my priors:**

## 14. Integrity caveats

*Self-authored. Name every way this result could be wrong. The stop study's version of this
section is the reason its conclusions are credible — match that standard.*

- **Selection bias:**
- **Simulator limitations:** *(intrabar ordering, spread-at-fill, swap, fill probability on limits)*
- **Sample-size limitations:**
- **Regime coverage:**
- **Anything I chose after seeing data:**

## 15. Verdict

**GO / NO-GO / INCONCLUSIVE:**

**Reasoning:**

**If GO — the conditions attached:**

**If NO-GO — recorded so it is not re-attempted:**
*(Falsifications are results. Record them as prominently as successes; your ICT falsifications
are among the most valuable documents in this repository.)*
```

---

## Appendix: a falsification log

Maintain `docs/research/FALSIFIED.md` as a single running list. It is the cheapest way to stop yourself re-testing the same idea in eighteen months, and it is the honest record of what this research programme actually knows.

| Date | Strategy | Verdict | Why it failed | Registration |
|---|---|---|---|---|
| 2026-07 | SilverBullet M5 (0.2×ATR stop) | FALSIFIED | Cost ≈ 3.0R at that stop distance | |
| 2026-07 | SilverBullet London-open +0.33R prior | FALSIFIED | Frictionless artifact; killed by costs | stop study |
| 2026-07 | ICT Unicorn / CRT / OTE | FALSIFIED | Net-negative after costs | |
| 2026-07 | Donchian-20 D1 trend | FALSIFIED | −0.1 to −0.25R; **note: 20 days is the wrong horizon for TSMOM — see Anchor** | |
| 2026-07 | MTF-PB (4H/1H bias → 5m fib) | INCONCLUSIVE | Only metals cleared | |
