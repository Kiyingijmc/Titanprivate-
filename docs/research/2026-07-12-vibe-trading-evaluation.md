# Vibe-Trading (HKUDS) — Applicability Assessment for Titan

Date: 2026-07-12
Sources: GitHub (`HKUDS/Vibe-Trading`), GitHub REST API, PyPI (`vibe-trading-ai`), project wiki, one independent third-party review. All fetched read-only; no code executed or installed.

---

## 1. What is it, actually?

Vibe-Trading is a **natural-language, LLM-agent-orchestrated research and backtesting workspace**, not a signal service and not a validated strategy. Core stack: FastAPI backend + React 19 frontend, LangChain/LangGraph for agent orchestration, CLI + web UI + MCP server entry points (`vibe-trading`, `vibe-trading-mcp`). [GitHub README](https://github.com/HKUDS/Vibe-Trading/blob/main/README.md), [PyPI](https://pypi.org/project/vibe-trading-ai/).

Components (verified from repo tree `agent/`: `backtest/`, `cli/`, `skills/`, `src/`, `tests/`, `scripts/`, plus `api_server.py`, `mcp_server.py`):
- **Data layer**: 19 free market-data sources with fallback chains (Yahoo, Sina, Stooq, Tushare, AKShare, Eastmoney, Baostock, OKX, CCXT, etc.), optional paid marketplace (QVeris).
- **Strategy layer**: an "alpha zoo" of 460 pre-built quantitative factor formulas (Qlib158, Kakushadze101, GTJA191, academic/fundamental families) plus LLM-driven natural-language strategy generation.
- **Backtest engine**: `backtest/` submodule with `runner.py`, `validation.py`, `metrics.py`, `correlation.py`, `run_card.py`, `engines/`, `loaders/`, `optimizers/` — supports walk-forward validation, Monte Carlo/bootstrap resampling, PIT-safe fundamental anchoring, and market-specific cost stacks (e.g. an India-equity engine modeling STT/stamp-duty/exchange/SEBI/GST).
- **Broker/execution layer**: read-only + paper connectors for IBKR, Longbridge, Trading 212, Dhan, Shoonya; **bounded live/paper trading** for Robinhood (Agentic Trading, OAuth), Tiger, Alpaca, OKX, Binance, Futu. **No MT5 broker connector** — MetaTrader 5 support is **MQL5 code export only** (alongside TradingView Pine Script v6 and TDX export), confirmed from README: `"/pine exports strategies to TradingView (Pine Script v6), TDX (...), and MetaTrader 5 (MQL5)"` — generates code for manual deployment, not a live bridge.
- **Model dependencies**: 13+ LLM providers supported (OpenAI, Anthropic Claude, DeepSeek [default], Gemini, Groq, DashScope/Qwen, Zhipu/GLM, Moonshot/Kimi, MiniMax, Z.ai, Ollama for local/no-key use). Cost is pay-per-API-call to whichever provider the user configures; no bundled/fixed pricing published.
- **Safety model for live trading**: a user-committed "mandate" (symbol universe, order-size cap, exposure/leverage limits, daily loss cap), a filesystem-level kill switch, a fail-closed pre-trade advisory gate, and an audit ledger. Explicitly framed as "experimental / use at your own risk."

## 2. Maturity & trust

| Signal | Value | Source |
|---|---|---|
| Repo created | 2026-04-01 (~3.5 months old) | GitHub API |
| Stars / Forks | 19,889 / 3,483 | GitHub API |
| Open issues | 12 | GitHub API |
| Contributors | 70 total, but **heavily concentrated**: top contributor (`warren618`, also the PyPI maintainer of record) has 306 commits vs. 27/22/20/15 for the next four | GitHub API |
| Last push | 2026-07-10 | GitHub API |
| License | MIT (core); Apache-2.0 for the Qlib alpha subset; attribution notices for other academic alpha families | LICENSE file, PyPI |
| PyPI version | 0.1.11 (2026-07-11), Beta classifier, Python ≥3.11 | PyPI |
| Org provenance | **Verified real.** `HKUDS` (Hong Kong University Data Science lab, contact `hkuds@connect.hku.hk`) is a genuine, prolific GitHub org: it also owns `LightRAG` (EMNLP2025, 37.5k★), `VideoRAG` (KDD'2026, 3.1k★), `AI-Researcher` (NeurIPS2025), `AutoAgent`, `DeepCode`, `nanobot` (45k★), `CLI-Anything` (45k★), and a near-duplicate prior project `AI-Trader` (20.7k★, last pushed 2026-06-11, apparently superseded by Vibe-Trading) | GitHub org API |

Red flags / caveats:
- **Star velocity is extreme** (0→19.9k in ~3 months) relative to a low, well-managed issue count (12) and a commit history dominated by one person. This is consistent with HKUDS's established pattern of shipping many rapid, marketing-forward, high-virality repos across unrelated domains (RAG, video, coding agents, trading) rather than a slow-grown, battle-tested trading-specific tool. It is not evidence of fraud (the org is real and academically credentialed), but it is evidence of a "ship fast, market hard" culture, not a "battle-tested in production" culture.
- An independent third-party review ([andrew.ooo](https://andrew.ooo/posts/vibe-trading-hkuds-personal-trading-agent-review/)) is balanced rather than purely promotional and flags real immaturity: *"Cost transparency is incomplete... provider-reported only with no price estimation"*; *"Provider quirks bite. Multiple recent releases are dedicated to fixing DeepSeek hangs, Kimi User-Agent rejections..."*; *"Robinhood Agentic is the only live broker that's been verified end-to-end. The others are paper-account or read-only by current design."*
- No abandonment or API-key-harvesting patterns were found in the surface-level review (README, pyproject, LICENSE, contributor list). This is not a substitute for a full source security audit, which was out of scope (read-only, no execution).

## 3. Evidence of edge

**None published.** Across the README, PyPI page, wiki summary, and the independent review, there are **zero backtested returns, Sharpe ratios, CAGR, drawdown, or any other performance numbers** for the 460-factor alpha zoo or any example strategy — in-sample or out-of-sample, gross or net. The project ships strong backtest *infrastructure* (walk-forward validation, PIT-safe data anchoring, Monte Carlo/bootstrap resampling, per-market cost stacks, reproducibility artifacts via `run_card.json/.md`), but this is tooling for a user to evaluate their *own* strategies — the vendor makes no edge claim of its own. Applying Titan's house standard ("gross-positive-in-sample claims are worthless"): there is nothing here to even apply the standard to. It is a research toolkit, not a strategy with a claimed edge.

## 4. Fit analysis vs. Titan

**(a) Research-side tool (idea generation / factor screening), isolated from the live path.**
Technically usable in principle (data aggregation, factor library, backtest scaffolding), but the cost is disproportionate: it pulls in LangChain/LangGraph, FastAPI, a React frontend, DuckDB, and a dozen optional broker/messaging SDKs — a large dependency footprint for a single-operator, no-cloud-budget project, to get a tool whose core interaction model (natural-language LLM agent) does not match Titan's deterministic, pre-registered-gate research culture. It would also require configuring and paying for an LLM API (DeepSeek is the free-ish default but still a network/API dependency) just to drive factor generation Titan's own strategy modules could express directly and deterministically. Marginal value, real cost — **not worth it as an installed tool.**

**(b) FeatureBus resource / strategy plugin candidate.**
**Disqualified outright.** Vibe-Trading's strategy-generation path is LLM-agent orchestrated (LangGraph multi-agent "swarms" for investment committees/quant desks), which directly conflicts with Titan's hard rule of "NO black-box/LLM-discretionary execution" and the determinism/replayability requirement for the live path. Even its pre-built alpha-zoo factors are unvalidated formulas, not strategies that have cleared a net-of-cost, pre-registered gate — they don't meet Titan's strategy-culture bar regardless of the LLM issue.

**(c) Infrastructure ideas worth borrowing (design only, no code/dependency adoption).**
A few patterns are worth noting for Titan's own Trading OS refactor, as ideas only:
- `run_card.json/.md` — a standardized, versioned artifact capturing a backtest run's inputs/config/results for reproducibility. Titan's golden-tape journal already covers this territory; worth a quick comparison for gaps.
- Per-market cost-stack modeling (India STT/stamp-duty/exchange/SEBI/GST as a first-class engine parameter) — directly analogous to Titan's own hard-won lesson that FBS spread cost kills most intraday edges; reinforces (doesn't add) the existing practice of net-of-cost gating.
- The mandate + filesystem kill-switch + fail-closed pre-trade gate + audit-ledger pattern for bounded autonomous execution is a reasonable reference design if/when Titan's intent arbiter needs an analogous "hard limits" layer — but Titan already has state reconciliation and Telegram remote-control (`/panic`, `/pause`) covering similar ground.

**Explicit conflicts with Titan's hard rules:**
- LLM-in-the-live-loop for signal/strategy generation — directly violates the no-black-box/no-LLM-discretionary-execution rule.
- Non-determinism inherent to LLM agent swarms — violates the determinism/replayability requirement.
- No MT5 live-execution bridge at all (MQL5 is export-only, generated code for manual deployment) — it cannot touch Titan's actual live venue (FBS via the ZMQ bridge) in any capacity.
- Meaningful new dependency surface (LangChain/LangGraph/FastAPI/React/DuckDB + optional broker/messaging SDKs) for a single-operator, no-cloud-budget project — fails the "new dependencies require justification" bar on cost/benefit alone, independent of the LLM issue.

## 5. Verdict

**REJECT for adoption** (as a tool, dependency, or strategy-plugin candidate). At most **BORROW-IDEAS** (design-level only, no code pulled in) for the two infrastructure patterns noted above (reproducibility run-cards, mandate/kill-switch pattern) if useful when Titan's own arbiter/risk-engine layer is designed.

Top reasons:
1. **Zero MT5 live-execution capability** — MetaTrader 5 support is code-export only, so it cannot participate in Titan's actual live path (FBS via ZMQ bridge) under any configuration.
2. **Core value proposition (LLM-agent strategy generation) directly violates Titan's hard rules** — no black-box/LLM-discretionary execution, and determinism/replayability are non-negotiable for the live path; the alpha-zoo factors, even setting the LLM issue aside, have no net-of-cost, pre-registered-gate evidence behind them.
3. **No published evidence of edge whatsoever** — not gross, not net, not in-sample, not out-of-sample — so there is no track record to weigh against the real cost of a large new dependency footprint (LangChain/LangGraph/FastAPI/React/DuckDB) for a single-operator, no-cloud-budget project.
