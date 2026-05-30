# Research: Improving Titan's Edge (ICT/SMC) — 2026-05-29

Deep-research pass: 5 angles, 24 sources fetched, 102 claims, 25 adversarially verified (19 confirmed / 6 refuted). All ICT model-definition claims rest on cross-corroborated retail trading-education sources (a valid baseline for *what the method prescribes*), **not** peer-reviewed proof of profitability.

## Evidence-based findings (high confidence)
1. **No independent evidence ICT/SMC beats generic TA.** Profitability is attributed to discipline/risk-management, not the method. Our negative backtest is consistent with the literature. *(algostorm.com; absence of academic validation.)*
2. **More confluence/complexity → better backtest, worse live** (overfitting). Fix = correctness + fewer robust rules, not more filters. *(MDPI JRFM; arXiv 2501.03938.)*
3. **Kelly is the decisive lever.** At 22% win / 3:1 RR, full Kelly `f* = p − q/b = 0.22 − 0.78/3 = −0.04` → **negative**. No sizing scheme rescues negative expectancy; win rate / RR must clear breakeven first, then use fractional (½–¼) Kelly, never over-Kelly. *(Kelly 1956; Thorp; en.wikipedia.org/wiki/Kelly_criterion.)*

## Canonical model rules (audit baseline; each 3-0 verified)
- **CRT:** HTF range (D/H4/H1) → LTF (5/15m). Bullish = liquidity raid (grab prior low, **close back inside**) → **LTF MSS** → enter **retest into FVG/OB**; stop below raid/MSS low; **target opposite range extreme**. *(innercircletrader.net, writofinance, tradingfinder, tradingwyckoff.)*
- **Unicorn:** Breaker⊕FVG overlap + structural shift; entry = **mandatory retest of the zone, never chase**. *(innercircletrader.net, luxalgo.)*
- **OTE:** fib zone **0.62–0.79** (0.705 centre); enter on retrace into zone **confirmed by LTF MSS/rejection — not the bare level** ("entering 0.705 without confirmation" = top mistake; price wicks through). *(innercircletrader.net, howtotrade, tradingfinder.)*
- **Silver Bullet:** **three** 1-hr NY-local windows (03–04, 10–11, 14–15), **DST-adjusted**; MSS → FVG → premium/discount. *(innercircletrader.net, fxopen, ultimamarkets, howtotrade.)*

**Unifying refinement:** every model enters on a **retest confirmed by a lower-timeframe MSS/rejection — never a passive limit at a level.** This single discipline explains both our symptoms: passive level-limits get **wicked** (low win rate) and **never fill** (150 expired). *(Caveat: that confirmation raises win rate is ICT folklore — no independent statistic proves it; we must verify on our own data.)*

## Refuted — do NOT hard-code
- Unicorn "10–20 pips beyond FVG wick" stop (1-2); Silver Bullet "beyond wick, 1:3" (1-2).
- Volatility-targeting / parity performance figures (single vendor; 0-3 / 1-2).
- "Retail can't infer institutional flow" (0-3) and "ICT can't be backtested" (0-3) — both overstated.

## Our code vs canonical (deviations)
| Model | Our code | Gap |
|---|---|---|
| CRT | M5 PDH/PDL sweep, single-candle rejection, enter at close (long=limit-at-close), fixed 3R | Not HTF-range model; no MSS, no retest, TP not opposite extreme — biggest deviation |
| Unicorn | FVG+breaker overlap + crude sweep; passive LIMIT at historical breaker level | No structural-shift confirmation; far limits expire |
| OTE | Single 0.705 LIMIT, FVG confluence, >2-ATR swing, no confirmation | The exact "bare-0.705, no confirmation" antipattern → wicked + 5 fills |
| Silver Bullet | Only 10–11 window, no DST, FVG+body>0.8ATR, no MSS | Misses 2 of 3 windows; no confirmation |

## Open questions (from verification)
- Is 22% win statistically adequate **per sub-strategy**? (Sample-size before disabling anything.)
- Does confirmation-retest actually raise **this bot's** win rate? (No independent proof — must measure.)
- Instrument return correlations (GBP/USD clusters, XAU, US30, BTC, Brent) for exposure caps.
- After rule correction, which sub-strategies clear positive-Kelly vs should be disabled.
