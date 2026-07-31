# Titan Trading Bot — Independent Technical Audit & Strategy Design

**Subject:** `Titan` — MT5/ICT forex trading bot (Python core + MQL5 bridge + React GUI + Telegram control)
**Repository audited:** `https://github.com/Kiyingijmc/Titanprivate-`
**Commit range:** `7dd9527` (baseline) → `cc59155` (HEAD)
**Scope:** 356 commits, 22 branches, full working tree, full git history
**Audit date:** 2026-07-30
**Method:** Four-perspective adversarial review — quantitative systems architect, adversarial security auditor, senior Python/MQL5 engineer, risk officer/discretionary trader

---

## ⛔ READ THIS FIRST

**A live Telegram bot token is publicly exposed in this repository, in two independent locations, and has been since the first commit.** The repository is public despite its name.

Go to **`01-SECURITY-INCIDENT-P0.md`** before reading anything else. The remediation takes about two hours and the first step takes ten minutes.

---

## Document set

| # | Document | Purpose | Read when |
|---|---|---|---|
| **00** | `00-README-INDEX.md` | This file — index, method, how to use the set | First |
| **01** | `01-SECURITY-INCIDENT-P0.md` | Credential exposure: scope, impact, exact remediation commands | **Immediately** |
| **02** | `02-AUDIT-REPORT.md` | The complete audit. Twelve sections across six phases | Reference — read Executive Summary, then dip in |
| **03** | `03-FINDINGS-REGISTER.xlsx` | All 101 findings, filterable, with owner/status/date columns for tracking | While remediating |
| **04** | `04-REMEDIATION-ROADMAP.md` | Four-stage plan, quick wins, go-live checklist | Planning your next month |
| **05** | `05-STRATEGY-ARSENAL.md` | Seven candidate strategies + one control experiment, designed against this bot's real constraints | After Stage A/B |
| **06** | `06-PRE-REGISTRATION-TEMPLATE.md` | Reusable template to prevent selection bias in strategy research | Before every new strategy |

### Suggested reading order

1. **`01`** — act on it today.
2. **`02` §12.1 Executive Summary** — the honest verdict in two pages.
3. **`03`** — import into your tracker; filter to Critical and High.
4. **`04` Stage A** — one week of work; do it before any run, demo included.
5. **`02`** in full — as reference while you fix things.
6. **`05`** and **`06`** — only after Stage B is complete.

---

## Headline verdict

> **Is this safe to run on live money today? No — and not for strategy reasons.**

Titan is substantially more complete and better researched than "unfinished bot" suggests. The full path — tick → feature → signal → grade → arbitration → sizing → risk gates → order → fill → journal → notify — is implemented and working. The single funnel through which every order must pass is the correct architecture and **it holds: no strategy can place an order without passing risk.** The research discipline behind the strategy exceeds that of many professional desks.

Three structural problems prevent live capital:

1. **The layer nearest the money is the least engineered.** `bridge_zmq.py` — 129 lines, the only path an order can take to your broker — has zero tests, no idempotency key, unauthenticated sockets bound to all interfaces, and silently discards truncated messages. Meanwhile ~3,900 lines of tests point at a package (`tradebot/`) that cannot affect a trade.

2. **The component producing the entire edge has never been run against a simulator.** The strategy is **−0.122R** with fixed exits and **+0.194R** with the ratchet+runner. The validated ratchet is offline reimplementation code; the live ratchet is different code. **Live expectancy is unknown, and the sign is not guaranteed.**

3. **Several safety controls are advisory rather than enforced.** The daily drawdown limit resets on every process restart with no restart cap. Position-count and per-symbol caps are blind to resting limit orders — the normal state of a limit-entry strategy. The correlation gate fails open. The flatten command reports success it has not verified. Nothing anywhere checks whether the connected account is demo or live.

**Estimated time to a defensible live run:** ~1 week of stop-the-bleeding fixes, ~3 weeks of foundations, then a 4-week demo soak with defined pass criteria.

---

## Findings summary

| Severity | Count | Dominant themes |
|---|---|---|
| **P0** | 1 | Live credential public in git history and in HEAD, on a public repository |
| **Critical** | 8 | Unenforced risk limits · unmeasured edge · unvalidated trust boundary · data-integrity corruption · missing idempotency · unusable journal schema · privilege/config-write chain |
| **High** | 36 | Unverified fire-and-forget commands · fail-open controls · observability blind spots · network exposure · zero test coverage on the order path · no CI, no dependency pinning, no backups, no runbook |
| **Medium** | 39 | Backtest realism gaps · unvalidated hyperparameters · resource/lifecycle hygiene · stale artifacts · schema durability |
| **Low** | 17 | Stale docs and entrypoints · misleading status headers · missing metrics · mechanisms built but never called |
| **Total** | **101** | |

### The pattern worth naming

The modal High finding is **not a missing feature.** It is a control that exists, is well-reasoned, is documented in a comment explaining exactly why it's correct — and is **never verified**.

`_dispatch_mgmt_command`'s docstring states the MODIFY outcome "is observable in the next HEARTBEAT's SL/TP." It *is* observable. Nothing observes it. That shape repeats across the ratchet, the partial closes, the TTL cancels, the flatten commands, the correlation matrix, and the `drops` counter.

**The systemic fix is not more controls. It is closing the loop on the ones you already have.**

---

## What the audit could not assess

| Cannot assess | Why | What would close it |
|---|---|---|
| EA runtime behaviour under load | MQL5 cannot be executed in this environment | Demo terminal with `OnTimer` latency logging |
| Whether ZMQ frames concatenate on the EA's PULL socket | Determines whether the substring-routing bug is theoretical or live | Logging build of the EA printing raw frames |
| `libzmq.dll` provenance (449 KB binary) | Unverifiable binary loaded into your trading terminal | SHA-256 against an official ZeroMQ release |
| Windows firewall posture | Decides whether ZMQ/bridge exposure is local-only or LAN-reachable | `netsh advfirewall firewall show rule name=all`; `nmap` from another host |
| Actual live spreads and slippage | Only the demo soak resolves it — and the journal cannot currently record it | Journal schema fix, then 4 weeks of soak |
| Whether the demo soak is running, and against what | Nothing in the code can answer this today | The account-mode assertion (OPS-01) |
| `.venv` contents | Gitignored; 15 unpinned `>=` constraints | `pip freeze` from the deployment host |
| The 21 non-`main` branches | Scanned for secrets; code not reviewed | `git log --oneline main..<branch>` per branch |

**One open question that changes the priority of everything:** `CLAUDE.md:61` says FBS-**Demo**; `titan-live.service` is named LIVE. **Is real money at risk right now?** If yes, the top four findings are not a roadmap — they are tonight.

---

## Conventions used throughout

- **`file.py:123`** — file and line reference into the audited commit range. Every finding carries one.
- **`NOT FOUND`** — searched for and absent. Treated as a finding, not an omission.
- **`[INFERRED]`** — reasoning beyond what was directly read.
- **R-multiple (`R`)** — profit or loss as a multiple of the initial stop distance.
- **Severity** — P0 (act today) · Critical (blocks live capital) · High (blocks live capital) · Medium (fix before scaling) · Low (hygiene).
- **Panel disagreements are preserved, not resolved into consensus.** Where the four perspectives conflict, both positions and the trade-off are stated.

---

## Corrections issued during the audit

Recorded here because an audit that never corrects itself should not be trusted.

| Correction | Original claim | Reality |
|---|---|---|
| **Threading model** | GUI writes could race the trading loop mid-decision | `server.py:169` runs uvicorn as a coroutine on the *same* event loop. No threads. The risk-decision block contains no `await` and is therefore atomic. **Withdrawn.** |
| **Cached risk scalars** | GUI falsely reports live settings as effective | `settings.py:16–26` documents this precisely and moves those keys to restart-tier. The GUI does not lie. **Downgraded Medium → Low.** |
| **Universe expansion** | Three new symbols possibly unvalidated | Re-validated on the identical pipeline with OOS, per-year slices, 2× spread stress, and a reproduction check. **Suspicion was wrong.** |
| **`test_data.csv`** | Suspected leak | 9,623 rows of OHLC. Benign. Not a finding. |
| **`boot_crash.log` root cause** | Open startup failure | Fixed. `Decimal`-based precision, dedicated branch, regression test. The *file* being committed is the residual finding. |

---

*Prepared as an independent technical review. Every finding is traceable to a file and line in the audited commit range. Where the audit could not verify something directly, it says so.*
