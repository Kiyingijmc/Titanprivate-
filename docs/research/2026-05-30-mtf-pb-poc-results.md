# MTF-PB PoC results — 2026-05-30

Parameters (a-priori, **not** swept): 50-EMA (4H & 1H bias, must agree), 5-bar strict-fractal
pivot, fib pullback band [0.5, 0.705] + confirmation-close entry, structural stop 1.0×ATR(1H),
fixed target 2.5R, ATR(14), trail 2.0×ATR(1H), train/test split 0.7. M5 entry granularity
(no M1; the 1–2m "sniper" entry is deferred to a live-only layer). Costs: 2·spread/stop +
commission-in-R via `poc_trend_h4._net` over `data/specs.json` + typical-spread map.
Data: 11 instruments × ~20k M5 bars (~3 months). Tool: `scripts/poc_mtf_pb.py`
(`data/history/mtf_pb_poc.txt`).

## Output (net of costs)

### FIXED-2.5R
| Class | n | win% [CI] | net Exp R | tot R | PF | DD R | OOS test n | OOS test exp |
|---|---|---|---|---|---|---|---|---|
| FX-majors | 581 | 28.7 [25-33] | −0.361 | −210.0 | 0.63 | 213 | 175 | −0.472 |
| FX-crosses | 233 | 31.8 [26-38] | −0.321 | −74.7 | 0.67 | 75 | 70 | −0.392 |
| **metals (XAUUSD)** | 116 | 36.2 [28-45] | **+0.239** | +27.7 | 1.36 | 11 | 35 | **+0.166** |
| index (US30) | 112 | 26.8 [19-36] | −0.110 | −12.3 | 0.86 | 22 | 34 | −0.233 |
| crypto (BTCUSD) | 121 | 26.4 [19-35] | −0.150 | −18.1 | 0.81 | 22 | 37 | −0.226 |
| energy (XBRUSD) | 138 | 31.9 [25-40] | +0.052 | +7.2 | 1.07 | 14 | 42 | −0.051 |
| **POOLED-ALL** | 1301 | 29.9 [27-32] | **−0.215** | −280.1 | 0.76 | 296 | 391 | −0.299 |

### PARTIAL-1R + ATR-TRAIL
| Class | n | win% [CI] | net Exp R | tot R | PF | DD R | OOS test n | OOS test exp |
|---|---|---|---|---|---|---|---|---|
| FX-majors | 650 | 45.5 [42-49] | −0.366 | −237.7 | 0.46 | 241 | 196 | −0.392 |
| FX-crosses | 261 | 41.4 [36-47] | −0.418 | −109.0 | 0.40 | 109 | 79 | −0.439 |
| **metals (XAUUSD)** | 123 | 57.7 [49-66] | **+0.145** | +17.9 | 1.33 | 9 | 37 | **+0.104** |
| index (US30) | 131 | 52.7 [44-61] | −0.007 | −0.9 | 0.99 | 14 | 40 | −0.123 |
| crypto (BTCUSD) | 130 | 48.5 [40-57] | −0.098 | −12.7 | 0.82 | 39 | −0.061 |
| energy (XBRUSD) | 140 | 55.7 [47-64] | +0.105 | +14.7 | 1.22 | 7 | 42 | +0.090 |
| **POOLED-ALL** | 1435 | 47.7 [45-50] | **−0.228** | −327.8 | 0.63 | 431 | −0.275 |

Train-block expectancy (= full − test, reconstructed) for the standouts:
- **metals FIXED:** train +0.271 (n=81), test +0.166 (n=35) — **positive both blocks**
- **metals PARTIAL:** train +0.163 (n=86), test +0.104 (n=37) — **positive both blocks**
- energy FIXED: train +0.097, test **−0.051** — fails OOS
- energy PARTIAL: train +0.111, test +0.090 — positive both
- index PARTIAL: train +0.044, test −0.123 — fails OOS

## GO/NO-GO verdict (per spec gate)

Gate = net-of-cost expectancy positive in **both** train and test, n≥30, under **both** exit
models, in the synthesis-predicted classes (index/commodity/crypto) — **not a single lucky
instrument**.

- **Positive both train+test, n≥30, under BOTH exit models?** Only **metals (XAUUSD)** clears
  this. Fixed: train +0.271 / test +0.166. Partial: train +0.163 / test +0.104. n_test 35/37.
- **Energy (XBRUSD)** is positive both blocks under PARTIAL but **fails OOS under FIXED**
  (test −0.051) → not robust across exit models.
- **Index and crypto** — the other two classes the synthesis predicted should suit trend —
  are **negative** (index ~breakeven-negative, crypto clearly negative).
- **FX (majors + crosses)** strongly negative under both models — exactly as the synthesis
  predicted (trend works worst on FX).
- **POOLED-ALL** is clearly negative under both models (−0.215 / −0.228).

**Decision: NOT a GO for the system as designed.** The basket loses, and the only class that
robustly clears the gate is **metals = a single instrument (XAUUSD)**. The spec's explicit
anti-cherry-pick clause ("not a single lucky instrument") and a multiple-comparisons caution
(6 classes × 2 exit models tested) mean one OOS-positive instrument is **not** sufficient
evidence to build the management layers or trade live.

**But this is not a flat NO-GO like ICT.** For the **first time all project**, something
survived OOS *net of cost* under **both** independent exit models with n≥30: the trend-pullback
spine on **metals (XAUUSD)**, and to a weaker degree **energy (XBRUSD)** under the trailing exit.
That is a genuine, encouraging lead, consistent with the synthesis ("trend works best on
commodities") — and notably the structural-stop discipline did its job (costs did **not** cause
the FX losses; the edge simply isn't there on FX).

## Recommended next step (INCONCLUSIVE → gather data, don't yet build)

Do **not** proceed to the management layers on the basket. Instead, **isolate commodities and
get more history** to confirm or kill the metals/energy lead before committing:

1. Export **multi-year** history for XAUUSD + more commodity instruments (XAGUSD, WTI/XTIUSD,
   natural gas, copper if the broker offers them) — the EA supports D1/H4 cheaply; ~3 months of
   M5 is too thin for a durable conclusion (n_test ~35, and 1-of-6 multiple-comparisons risk).
2. Re-run MTF-PB on the larger commodity sample, **same a-priori parameters** (no sweeping), and
   check whether metals' positive net-of-cost OOS edge holds at n≥100+ under both exit models.
3. If it holds → *then* build the management layers (order → risk → account → compounding →
   bookkeeping → auditing; ML last) scoped to commodities. If it dissolves at scale → it was
   small-sample luck (the VALIDATED_REPORT.md lesson), and we shelve or iterate the few rules.

Honest bottom line: the design's spine is the most promising thing we've tested, and it produced
the project's first cost- and OOS-surviving signal — but on this 3-month sample it is **one
instrument**, not yet a validated edge. Verdict: **inconclusive-but-promising; need more
commodity history before any live or management work.**
