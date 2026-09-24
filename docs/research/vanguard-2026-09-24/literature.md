# C. External evidence review

Research accessed 2026-09-24. This is a targeted literature review, not an exhaustive systematic review or independent reproduction. Strength labels distinguish published empirical evidence, model-dependent theory, working papers and practitioner convention. Publisher abstracts/previews were used where full text was unavailable; those sources support only the stated narrow conclusions. No source establishes VANGUARD profitability.

## Trend following: supported phenomenon, unresolved transfer

**L1 — Moskowitz, Ooi and Pedersen (2012), Time Series Momentum. Strong published empirical evidence at substantially longer horizons.** The study reports own-return predictability across 58 futures/forward instruments, with persistence over roughly one to twelve months and partial reversal later. Diversification and extreme-market performance are relevant; extrapolation to M5 acquisitions in broker CFDs is not established. [Author-hosted publication](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum), [paper](https://fairmodel.econ.yale.edu/ec439/mosk.pdf).

**L2 — Hurst, Ooi and Pedersen (2017), A Century of Evidence on Trend-Following Investing. Broad historical institutional evidence, with backcast limitations.** Long histories and multiple asset classes strengthen the case for diversified trend exposure. Reconstructed instruments, historical cost estimates and long horizons limit direct applicability. Use it to motivate a slow baseline and calendar-regime stress tests, not to assert intraday crisis protection. [Publication PDF](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-JPM-Fall-2017.pdf).

**L3 — Potters and Bouchaud (2005), Trend followers lose more often than they gain. Model-dependent theory.** Their solved model produces an asymmetric per-trade distribution even with zero mean gain. This directly undermines treating positive skew, low win rate or rare large winners as evidence of alpha. Measure net mean and capital drawdown alongside skew. [Paper](https://arxiv.org/abs/physics/0508104).

**L4 — Sepp and Lucic (2026), The Science and Practice of Trend-Following Systems. Current working paper, not established independent replication.** The supplied arXiv reference is real and was submitted July 21, 2026. It relates normalized trend-system returns to serial dependence/drift, studies skewness and cost-optimal spans, and explicitly warns about short-memory predictability being uneconomic after costs. Its model and futures tests do not validate VANGUARD's phases, campaigns or lifecycle rules. [Abstract/version](https://arxiv.org/abs/2607.19497), [full text](https://arxiv.org/html/2607.19497v1).

**L5 — Lempérière et al. (2014), Two centuries of trend following. Long-run empirical working-paper evidence.** The study extends trend evidence over long histories and reports saturation for large signals. This motivates bounded exposure rather than assuming stronger measured trend always deserves more leverage. It does not prove that an old individual trend must be near exhaustion. [Paper](https://arxiv.org/abs/1404.3274).

**Implication:** persistence, decay and crisis performance depend on horizon, instrument, diversification and costs. An abrupt crash/rebound can hurt a slow trend system before it adapts. No fixed trend half-life or H1/M15/M5 hierarchy follows from these studies.

## Entry timing, microstructure and state estimation

**L6 — Gao, Han, Li and Zhou (2018), Market intraday momentum. Published empirical evidence for a specific clock-time pattern.** First-half-hour market return predicts last-half-hour return in their ETF sample, with state dependence. This is evidence that some intraday persistence exists, not evidence that arbitrary M5 pullbacks are favorable. Market timing and opening/closing flows may matter more than candle names. [Publisher](https://www.sciencedirect.com/science/article/pii/S0304405X18301351).

**L7 — Hedging demand and market intraday momentum (2021). Published broader futures evidence; publisher preview examined.** The study describes intraday momentum across more than 60 futures and relates it to hedging demand. Its specific mechanism supports testing session-conditioned predictability separately from an all-day local pattern. It does not establish transfer to Titan's broker quote stream. [Publisher](https://www.sciencedirect.com/science/article/pii/S0304405X21001598).

**L8 — Osler (2002 staff report; 2005 journal publication), Stop-Loss Orders and Price Cascades in Currency Markets. Published microstructure evidence.** Documented stop clusters are associated with rapid self-reinforcing exchange-rate moves, with effects on the scale of hours rather than days. That provides a possible breakout mechanism and a warning about adverse stop execution. OHLC patterns alone do not identify actual clustered orders. [Federal Reserve Bank of New York](https://www.newyorkfed.org/research/staff_reports/sr150.html).

**L9 — Adams and MacKay (2007), Bayesian Online Changepoint Detection. General methodological evidence.** Online run-length inference can be causal when filtering forward. It requires a likelihood and hazard specification; inferred change points are not automatically profitable trading regimes. Compare to a threshold/dwell rule before adopting it. [Author PDF](https://www.cs.princeton.edu/~rpa/pubs/adams2007changepoint.pdf).

**L10 — Wood, Roberts and Zohren (2021), Slow Momentum with Fast Reversion. Financial working-paper evidence.** A changepoint module within a deep momentum model improves their historical results around nonstationarity. The integrated learned strategy is substantially different from VANGUARD; it supports an experimental question, not a ready-made exit rule. [Paper](https://arxiv.org/abs/2105.13727).

**L11 — Levy and Lopes (2021), Trend-Following Strategies via Dynamic Momentum Learning. Working-paper evidence.** Sequentially learned combinations of momentum speeds improve performance in their futures study. This makes fixed versus adaptive speed a legitimate research comparison. It does not justify estimating many speed weights from a small intraday trade sample. [Paper](https://arxiv.org/abs/2106.08420).

**L12 — de Lataillade et al. (2012), Optimal Trading with Linear Costs. Model-dependent theory.** With a predictive process, position bounds and linear costs, a no-trading region can be optimal. This supports testing explicit cost-aware entry/exit hysteresis, rather than continuously reacting to small score changes. It does not provide Titan-specific thresholds. [Paper](https://arxiv.org/abs/1203.5957).

**Assessment of the three entry families:** breakout/ignition has the clearest general persistence rationale. Pullback acquisition exchanges price improvement for missed trends and adverse selection; compression predicts a potential change in volatility, not its direction. No reviewed primary study establishes the brainstorm's particular benign/hostile taxonomy as superior. Require separate arms, matched trend episodes, and missed-opportunity accounting.

**Primitive measurements:** normalized slope/momentum is a reasonable low-dimensional descriptive statistic, not a calibrated probability. Efficiency adds path shape but overlaps persistence. Kalman filtering adds a model of noise and drift; Titan already has a local comparator. Acceleration amplifies noise. Binary directional entropy adds no information beyond the binary sign proportion. Short-window autocorrelation estimates have large uncertainty. Online changepoints are causal in principle; offline smoothed regime labels are inadmissible decision inputs.

## Exit science and the central VANGUARD claim

**L13 — Kaminski and Lo, When do stop-loss rules stop losses? Published framework and empirical study.** Stop-loss value depends on the return-generating process; random-walk and momentum cases differ. This supports testing informational conditions rather than assuming stop tightening universally helps. It does not establish thesis deterioration measured by VANGUARD's indicators or progressively slower management after profits. [MIT repository](https://dspace.mit.edu/entities/publication/bb69ca4b-0cdc-487f-831d-63b2e84fafee).

**L14 — Leung and Zhang (2017), Optimal Trading with a Trailing Stop. Model-dependent optimal stopping.** Under specified diffusion dynamics they derive acquisition/liquidation policies, including a sell limit with a trailing stop. This is a useful counterexample to the universal claim that fixed profit targets are irrational. The optimal answer depends on the process/objective; it is not empirical support for fixed targets in VANGUARD. [Paper](https://arxiv.org/abs/1701.03960).

**L15 — Fonseca (2026), Point-in-Time Backtesting of Momentum-Trend Equity Strategies. Supplied recent reference: provisional evidence only.** The Sciety record exists and describes filtration, stop sequencing and ATR ratchets; it is an index record with zero evaluations, not an independent confirming study. The supplied MDPI URL returned HTTP 429 and the direct preprint retrieval failed during this review. Publication status and full empirical details therefore were not verified here. Exclude its performance claims from the evidence supporting VANGUARD. [Supplied publisher URL](https://www.mdpi.com/2227-7390/14/12/2182), [preprint DOI](https://doi.org/10.20944/preprints202606.0436.v1), [discovery record](https://labs.sciety.org/articles/by?article_doi=10.20944%2Fpreprints202606.0436.v1).

**Answer to the central question:** credible literature supports state-dependent continuation/exit decisions as a research problem. It does **not**, in the material reviewed, directly establish that losing intraday positions should use this proposed thesis score or that winners should graduate to slower horizons. Those remain two separate experimental hypotheses. Neither should be bundled with the other or called proven exit science.

ATR stops and monotonic trails are transparent comparators. Time exits are operationally useful but can truncate slow trends; compare fixed holding limits to continuation-based exits. MFE/MAE are descriptive path measurements, not causal forecasts. MFE must be restricted to information observed so far for decisions, and evaluated over a common future observation window for exit diagnostics.

**Partial liquidation and pyramiding:** no sufficiently transferable primary empirical evidence was found in these searches for Anchor/Satellite roles, promotion, protected-profit reservoirs or evidence-conditioned partials. Practitioner use of scaling is not validation. Mechanically, a partial reduces subsequent participation in both favorable and adverse paths; adding increases both. Compare equal-budget aggregate exposure, include costs, and judge portfolio returns/tails—not attractive per-ticket R. Absence of supporting evidence in this review is not proof these mechanisms cannot work.

## Dynamic risk and portfolio construction

**L16 — Moreira and Muir (2017), Volatility-Managed Portfolios. Strong published evidence within studied assets/factors.** Reducing exposure in high-volatility periods improved several studied portfolios. This supports volatility scaling as a serious baseline. It does not make stop-distance sizing identical to volatility targeting or justify multiplying trend confidence, maturity and drawdown factors. [Journal](https://onlinelibrary.wiley.com/doi/10.1111/jofi.12513).

**L17 — Cederburg et al. (2020), On the performance of volatility-managed portfolios. Published counterevidence.** Across a larger strategy set, results are less favorable under implementable out-of-sample combinations; structural instability matters. Therefore a native overlay must beat shared sizing under matched exposure and realistic leverage constraints, not only an in-sample regression. [Journal](https://www.sciencedirect.com/science/article/pii/S0304405X2030132X).

**L18 — Busseti, Ryu and Boyd (2016), Risk-Constrained Kelly Gambling. Model-based risk/growth framework.** Explicit drawdown constraints are more meaningful than assuming fractional Kelly is universally safe. The result requires a specified outcome distribution; VANGUARD does not possess a reliable one. Use capital-loss constraints and stress tests first; defer estimated Kelly sizing. No estimated risk-of-ruin number should be presented as a guarantee. [Author publication page](https://www.web.stanford.edu/~boyd/papers/kelly.html).

**L19 — Ledoit and Wolf (2003/2004), Honey, I Shrunk the Sample Covariance Matrix. Established estimation research.** Covariance estimation error can seriously distort optimized portfolios; shrinkage improves estimation in their setting. This argues against fine allocation from a small pairwise H1 matrix. For initial VANGUARD use conservative factor groups and stressed common-direction shocks; assess shrinkage covariance only later. [Author PDF](https://ledoit.net/honey.pdf).

**L20 — Risk parity / marginal contribution.** Equal risk contribution is an allocation objective, not alpha. For signed exposures `w`, covariance `Σ` and portfolio volatility `σp`, Euler contributions are `w_i(Σw)_i/σp`. Estimates can be negative for hedges and unstable during stress. The original Roncalli author site was discovered but full PDF retrieval failed; a reviewed peer-reviewed extension explicitly develops risk-contribution allocation using mean absolute deviation. Neither establishes suitability for small CFD campaigns. [MAD risk parity portfolios](https://link.springer.com/article/10.1007/s10479-023-05797-2).

**Dynamic leverage, drawdown and anti-martingale:** adding to winners is not a proof of safety; position size can be largest just before reversal. Drawdown-dependent compression can reduce losses but also miss recoveries and change right-tail participation. Treat it as an owner utility/risk policy, with performance costs reported. A simple NORMAL/REDUCED/HALTED schedule is a sufficient comparator to five named levels. Recent failed trades justify reduced forecasts only if they predict worse forward outcomes conditional on the existing market state; otherwise loss memory is an arbitrary exposure schedule.

## Statistical hazards

**L21 — Bailey et al., The Probability of Backtest Overfitting. Published methodological evidence.** Evaluating many alternatives and selecting a winner can produce poor out-of-sample results. PBO/CSCV quantifies aspects of selection using the tested return matrix; it is not a cure for missing trials, changing datasets or nonstationarity. Preserve all variants, not just winners. [Author PDF](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

**L22 — Bailey and López de Prado (2014), The Deflated Sharpe Ratio. Published methodology.** DSR adjusts evidence for selection and non-normal returns. It needs a defensible trial count/dependence estimate and sample moments. Serially dependent daily returns and rare trend outliers require additional care. DSR should supplement paired chronological tests, not replace them. [Author PDF](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).

**L23 — López de Prado, financial ML course materials / validation methodology.** Overlapping outcome intervals require purging; embargo addresses adjacent dependent samples when nonchronological splits are used. A fixed indicator strategy does not need ML simply to use these ideas. For VANGUARD, chronological deployment replay remains primary; campaign overlap and long holding periods determine purging, not an arbitrary percentage of rows. [Author course materials](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3459207).

Walk-forward testing is still vulnerable if the researcher repeatedly chooses windows, parameters or successful folds. Regime labels assigned after outcomes create hindsight; train-only thresholds and causal state filtering are mandatory. Feature availability, revisions, universe selection and broker specification history belong in the information set. Bootstrap campaigns/time blocks jointly across symbols; treating satellites or two OHLC paths as independent samples exaggerates evidence.

## Official execution constraints

**L24 — MQL5 OrderSend.** A successful call does not alone establish a completed fill; retcodes and trade transactions matter. One request may generate multiple transaction events. Persist request identity, pending state and actual fills independently. [Official documentation](https://www.mql5.com/en/docs/trading/ordersend).

**L25 — MT5 accounting modes.** Netting aggregates a symbol's exposure, whereas hedging permits multiple positions. Independent broker-side stop policies for virtual Anchor/Satellite tranches are therefore not automatically implementable on netting accounts. Stop/TP inheritance must be handled explicitly when adding. [Official trading principles](https://www.metatrader5.com/en/terminal/help/trading/general_concept).

**L26 — Broker symbol properties.** Stop/freeze distances, tick size, volume minimum/maximum/step and execution/fill modes are instrument properties. Recheck them for each order/modify plan and recompute legal risk after normalization. [Official symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants).

**Execution conclusion:** a broker stop is contingent protection, not guaranteed capital. A gap may skip the level; a rejected modification does not protect profit; a request timeout is an unknown outcome until reconciled. These conclusions are engineering requirements, not evidence that a stop strategy earns alpha.

## Evidence-to-design decision

| Claim | Evidence judgment | Design response |
|---|---|---|
| Trend can be profitable | Strong across some markets/horizons | Simple trend baseline first |
| Trend can be positively skewed | Theoretical and empirical support, horizon-dependent | Measure skew; do not use it as profitability proof |
| M5 acquisition improves H1 trends | Unresolved; adverse Titan evidence | Separate cost/participation gate |
| Pullbacks beat breakouts | Not established generally | Independent competing families |
| Multiple states predict more | Not established | Minimum states and component ablations |
| Thesis exits beat tighter stops | Plausible, unproven here | Paired counterfactual exit test |
| Winners should graduate | Unproven | Fixed slow versus age versus evidence graduation |
| Partial harvesting improves convexity | Not established; exposure reduction can truncate tails | Defer; equal-risk comparison |
| Native dynamic risk improves results | Mixed literature, context-dependent | Shared baseline, isolated overlay |
| Stops finance “free” satellites | No guarantee or transferable validation | Zero protected-profit credit initially |
| More validation variants cure selection bias | False | Frozen ledger, untouched chronological holdout, prospective replication |
