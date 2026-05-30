# ▶ RESUME — Titan project state (handoff for the next session)

**If you are a fresh Claude session: read this file first, then continue from "NEXT ACTION".**
Working branch: `harden/normalize-price-crash` (NOT merged to main). Run everything from repo root with `.venv/bin/python`. Tests: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.

## The story so far (why we are where we are)
We inherited an MT5/ICT trading bot. We (1) fixed a boot crash + broker-spec-only sizing + secrets hygiene; (2) connected MT5 (FBS demo) ↔ WSL over a ZMQ bridge; (3) built a **cost-aware backtester** (R-multiples + $ + spread/commission + train/test split + Wilson significance + Monte-Carlo) and **multi-timeframe history export** (M5/H1/H4/D1 via the EA's `GET_HISTORY`).
**Findings (all rigorously cost- + OOS-validated):**
- All four ICT strategies (Unicorn, CRT, OTE, SilverBullet) are **net-negative after costs**. Deep research found ICT/SMC has **no independent evidence** of edge.
- SilverBullet looked positive frictionless (+0.33R in a broker ~04–08 window) but **died on spread** — its stop is `0.2×ATR` (sub-pip); spread > edge. **Lesson: precise entries are fine, but stops MUST be structural/wide or spread eats the edge.**
- A short trend system (Donchian-20, D1, 8 instruments, ~5y) is also **net-negative** — but that's a too-fast, weak variant; cost-robust structure (wide stops) was confirmed (−0.1 to −0.25R, NOT cost-driven).

## Current direction (user's chosen path)
Design **our own** multi-timeframe, trend-aligned, pullback-entry system (NOT session/time-bound):
**4H bias → 1H confirmation → 15m trend → 5m OTE/Fib-retracement setup → 1-2m precise entry; only trade WITH the 4H bias + trend; structural (15m/1H/ATR) stops.**
Sequence the user wants AFTER the strategy: **order management → risk management → account management → compounding → bookkeeping → accounting/auditing → ML (LAST).**

## Research status
The formal deep-research workflow on this design **FAILED** (intermittent model outages broke the synthesis after 105 agents). An **interim evidence synthesis** was written instead: `docs/research/2026-05-30-mtf-synthesis-interim.md` (confidence-labeled) — and it proved sufficient; the formal workflow was **not** re-run. Optional: re-run the formal cited workflow (`deep-research` skill, brief in `docs/research/RESEARCH_QUESTION_mtf.md`) if desired.

## ✅ DONE this session: the MTF-PB PoC is built + validated
- **Spec:** `docs/superpowers/specs/2026-05-30-mtf-trend-pullback-poc-design.md`; **Plan:** `docs/superpowers/plans/2026-05-30-mtf-trend-pullback-poc.md`; **Code:** `scripts/poc_mtf_pb.py` + `tests/unit/test_mtf_pb.py` (**69 tests green**). Run: `.venv/bin/python scripts/poc_mtf_pb.py`.
- **Design as built:** 4H+1H 50-EMA bias (must agree) → 5m fib(0.5–0.705) pullback + confirmation-**close** entry (never a passive limit) → **1.0×ATR(1H) structural stop** → two exit models (fixed-2.5R + partial-1R/BE/2.0×ATR-trail). Validated net-of-cost, OOS (70/30), Wilson CI, pooled by asset class. (2-TF gate not 3, to curb overfitting + keep n; 1–2m entry deferred — no M1 data.)
- **Result (`docs/research/2026-05-30-mtf-pb-poc-results.md`): NOT a GO, but the first cost- + OOS-surviving signal all project.** Basket loses (~−0.22R both models); FX strongly negative (as predicted); index/crypto negative. **Only metals (XAUUSD) clears the gate** (positive net-of-cost in BOTH train+test under BOTH exit models, n_test ~35). Energy (XBRUSD) positive under the trailing exit only. Metals = one instrument on ~3 months → multiple-comparisons + thin-sample caution → **inconclusive-but-promising, not validated.** Known caveats documented in the results doc.

## NEXT ACTION (do this first)
1. **Do NOT build the management layers yet.** Gather more **commodity** history (multi-year XAUUSD + more commodities: XAGUSD, WTI/XTIUSD, copper, natgas if FBS offers them — EA D1/H4 export is cheap; recreate the warm-up+retry export pass, see Operational notes) to get a real sample.
2. Re-run `scripts/poc_mtf_pb.py` (**same a-priori params, no sweeping**) on the larger commodity set; check whether metals' positive net-of-cost OOS edge holds at **n≥100+** under **both** exit models.
3. If it holds → THEN work the management layers in the user's order (order → risk → account → compounding → bookkeeping → accounting/auditing); **ML last**. If it dissolves at scale → small-sample luck (the VALIDATED_REPORT.md lesson) → shelve or iterate the few a-priori rules.

## Hard rules (do not repeat past mistakes)
- **Structural stops only** (≥ ~confirmation-TF swing / a few ATR). Never sub-pip/tight stops — they die on spread.
- **Always validate net-of-cost in R** (`net_r = r − 2·spread/stop − commission_R`) AND **out-of-sample** (train/test) AND significance (Wilson, flag n<30). A frictionless R result means nothing.
- **No parameter sweeping** to manufacture a win (overfitting is the #1 research-flagged risk). Use a-priori, documented parameters.
- ICT claims = folklore unless independently supported; the one defensible ICT idea is "pullback/retracement entry in the direction of the higher-TF trend."

## Operational notes
- **Bridge:** EA `Titan_Gateway` on FBS MT5 (terminal data folder `776D2ACDFA4F66FAF3C8985F75FA9FF6`). Python BINDS, EA CONNECTS. EA **`InpIP` must = the current WSL eth0 IP** (`ip -4 addr show eth0`; was `172.31.128.205`) — it resets to `127.0.0.1` on recompile and then jams the ports. `libzmq.dll`+`libsodium.dll` are in `MQL5/Libraries`. EA now supports `M5/H1/H4/D1`.
- **History export gotchas:** the EA builds history with O(n²) string concat → M5 capped ~20k bars; D1 is cheap (~1300 bars=5y). Cold symbols (gold/BTC) return NODATA on first request — needs a warm-up + retry pass (see `/tmp/export_d1_noping.py` pattern, now lost on revoke — re-create: send GET_HISTORY for all syms, wait ~12s, then per-symbol retry). History export needs the bot NOT running (shared ZMQ ports) and **no overlapping bridge processes** (they jam ports; if "Address already in use", `pkill -f '.venv/bin/python'` then wait ~70s for TIME_WAIT).
- **4 demo trades** (2 market + 2 pending) may still be open on FBS-Demo from an earlier test — flatten or ignore.
- **Secrets:** live Telegram token in `.env` (git-ignored, untracked, NOT rotated by user's choice).
- Data under `data/history/` is git-ignored (CSVs, specs.json, result .txt reports).

## Key docs
- `data/history/VALIDATED_REPORT.md` — the 20k-bar validated ICT results.
- `docs/research/2026-05-29-ict-edge-research.md` — the first deep-research report (ICT has no edge; Kelly; canonical rules).
- `docs/superpowers/specs/` + `plans/` — specs/plans for the harness, SilverBullet timing, H4 trend PoC.
- Memory: `.../memory/MEMORY.md` (auto-loaded) — has the SilverBullet/bridge/token findings.
