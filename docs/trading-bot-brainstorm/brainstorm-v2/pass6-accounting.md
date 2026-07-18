# PASS 6 — ACCOUNTING, COMPLIANCE & MONEY TRUTH

**Chair:** A-Tier Auditor & Accountant. **Contributors:** all ten seats; every claim below survived the Chair's red-team or is labeled with its evidence class.
**Inputs (read in full):** `00-overview.md`–`05-…`, `pass1-audit.md` (F-001…F-039), `pass2-research.md`, `pass3-systems.md` §1–§4 (normative; this pass **extends** the §1.1 envelope, the §1.3 hash chain, and the §3.3 reconciliation algorithm — it contradicts none of them).
**Routing note:** Pass 1's disposition column predates the summit re-scope; this pass owns **every finding whose subject is money** regardless of the pass number cited there: F-002 (accounting side), F-003 (cost capture, adopted), F-012 (spread/adverse-selection attribution), F-020 (swap), F-022 (slippage-vs-decision accounting), F-023 (conversion), F-029 (cost-capture side; calibration stays Pass 7), F-032 (attribution of money to owners), plus the money-relevant residues of F-004 (audit-chain verification job), F-031 (command-channel inheritance for money-mutating commands), F-033 (clock discipline for conversion timestamps). §9 records each.
**Chair's prior, restated as the design bar:** P&L bugs are silent, compounding, and discovered at tax time. Therefore: no money number may exist in exactly one place; every money number must be re-derivable from two independent paths whose difference is computed, classified, and alarmed. A ledger that cannot fail loudly is a diary, not a ledger.

**Unit convention (binding for this pass):** all monetary amounts are stored as **integer micro-units of their currency** (`i64`, 1 unit = 10⁻⁶ of the currency; $14.00 = `14_000_000`). Floats never touch stored money. Conversion multiplies once in extended precision, rounds **half-even** once, and the rounding residual per posting is bounded by 1 micro-unit and posted explicitly (§1.3). Tick quantities remain `int` ticks per F-003; risk fractions remain floats per Pass 3 §1.2 (they are ratios, not money).

---

## §1 The P&L engine — double-entry ledger design

### 1.1 Design principles

1. **Double-entry, machine-generated.** Every money-affecting event produces a balanced posting (Σ debits = Σ credits, exact in micro-units). Postings are generated mechanically from typed events by one function per event schema — there is no hand-written journal entry anywhere in the system. (Backend Architect's "overkill" objection and its resolution: §8-1.)
2. **Two truths, one ledger.** The ledger carries **broker-book amounts** (what the broker posted: `DEAL_PROFIT`, `DEAL_SWAP`, `DEAL_COMMISSION`, already in account currency) as the cash-truth, and **decision-book amounts** (independently recomputed from prices, specs, and our own conversion rates) as dimensions on the same lines. The difference between the two is not error to be hidden — it is *the product*: it decomposes into slippage, spread, conversion drift, and swap mismatch, each with its own account and tolerance. Cost blindness is impossible because the cost **is a ledger balance** you can trend.
3. **Ledger lines are events.** A posting is a `ledger.posting` event on the Pass-3 chain: it has `seq`, `prev_hash`, `parent_ids`, an actor, and canonical JSON. The P&L engine has no storage of its own; balances are a projection (fold) over posting events, rebuilt after any reconcile exactly like the risk ledger (Pass 3 §3.3 sign-off condition, extended to money).
4. **The sole writer writes money too.** All postings are appended by the core's single writer (Pass 3 §1.4). The writer **refuses to append** an unbalanced posting or a posting with no parent — invariants I2/I3 (§6.2) are enforced at write time, not discovered at audit time.

### 1.2 Chart of accounts

| Code | Account | Class | Normal | Contents |
|---|---|---|---|---|
| 1000 | Cash at broker | Asset | DR | Account-currency balance; moves only on broker-posted facts (deal profit/swap/commission, balance ops) |
| 1100 | Open-position mark | Asset | DR | Unrealized value of open tranches at last mark (§1.5); zero when flat |
| 1150 | Swap accrued (open) | Asset/Liab | signed | Predicted swap accrued nightly on open positions (§2.2); reversed at close against broker-posted swap |
| 1900 | Suspense / unattributed | Asset | DR | Quarantine-book money (F-032) + unexplained cash residuals awaiting classification; **target 0, alarmed** (§4.1) |
| 3000 | Opening capital | Equity | CR | Balance at ledger genesis |
| 3100 | Deposits / withdrawals | Equity | CR | `DEAL_TYPE_BALANCE` ops; never P&L |
| 4000 | Realized price P&L | P&L | CR | Broker-book price component of closed tranches |
| 4100 | Swap realized | P&L | CR | Broker-posted swap at close (and broker nightly postings where the broker cash-posts swap) |
| 4110 | Swap true-up | P&L | CR | Broker-posted swap − our accrual prediction (§2.2 verification residual) |
| 4200 | Commission & fees | P&L | DR | Per-deal commission + `DEAL_FEE`; verified vs configured model (§2.1) |
| 4400 | Conversion gain/loss | P&L | CR | Our-rate vs broker-implied-rate drift + any revaluation (§3.4) |
| 4600 | Unrealized MTM change | P&L | CR | Counter-account of 1100 marks; reverses into 4000 at close |
| 4900 | Unexplained residual | P&L | CR | Daily cash-equation residual below auto-accept tolerance (§5.3); **trended and alarmed** |
| 9000/9100/9200 | Margin / notional / gap-stressed | Memo | — | References into the Pass-3 §2.6 risk ledger; memo class, excluded from trial balance (no double counting of the risk ledger) |

**Trial-balance identities (checked continuously, §6):**
`1000 + 1100 + 1150 + 1900 = 3000 + 3100 + Σ(4xxx)` (internal consistency, exact) and
`1000 + 1150 ≈ broker balance`, `1000 + 1100 + 1150 ≈ broker equity` (external truth, within the MTM tolerance of §5.3 — marks race quotes, so this one is toleranced, the internal one is not).

### 1.3 Posting rules (event → posting)

Every rule cites its parent event(s); `parent_ids` on the posting point at them (audit chain, §6). DR/CR shown for the *typical sign*; all rules are sign-symmetric.

| Trigger event (Pass-3 schema) | Posting | Notes |
|---|---|---|
| `exec.fill` (entry, open or add) | Create tranche record (§4.2 schema; memo). If the entry deal carries commission: DR 4200 / CR 1000 | No P&L at open. Cost basis = fill price; decision-book fields (decision price, spread at fill, slippage ticks) stored on the tranche from `exec.telemetry_sample` |
| `ledger.accrual` (nightly rollover timer, §2.2) | DR **4100** (expense) / CR **1150** for negative swap (signs reversed for positive swap), at the **predicted** amount | Predicted from discovered specs; broker truth arrives later and settles via the 4110 true-up at close |
| `exec.fill` (close / reduce) → `ledger.tranche_alloc` (§4.2) | (a) DR 1000 / CR 4000 for broker `DEAL_PROFIT` (allocated per tranche); (b) reverse the tranche's accumulated mark: DR 4600 / CR 1100; (c) settle swap: DR 1150 / CR 1000 for accrued amount, and DR/CR **4110** for (broker `DEAL_SWAP` − accrued); (d) DR 4200 / CR 1000 for `DEAL_COMMISSION`+`DEAL_FEE`; (e) DR/CR **4400** for (our independently converted price P&L − broker `DEAL_PROFIT`) — see §3.4 | One balanced posting with up to 5 line-pairs; the `ledger.waterfall` event (§2.3) accompanies it and must sum to the same net |
| `ledger.mark` batch (§1.5) | DR/CR 1100 vs 4600 per position, delta since last mark | Batch = one posting; per-position lines carry rate metadata |
| `recon.money_run` residual ≤ auto-accept | DR/CR 4900 / 1000 | Residual is *posted*, never absorbed silently; 4900's balance is a monitored health metric |
| Broker balance op (`DEAL_TYPE_BALANCE`) | DR 1000 / CR 3100 | Deposits/withdrawals/credits; a balance op we didn't initiate is a `BALANCE_OP_UNSEEN` diff (§5.4), posted to 1900 pending human classification |
| Quarantine adoption (`position.adopted`, unmatched) | Money effects post to **1900**, not 4000 | Attribution to a child moves it out of 1900 with a re-posting (both postings chained; nothing is edited) |

**Rounding law:** within a posting, each line rounds half-even to 1 micro-unit; the posting-level residual (≤ n_lines micro-units) is added to the largest line so the posting balances *exactly*. Property test P11 (§6.3) fuzzes this.

### 1.4 Realized vs unrealized; lot-relief policy (F-002 — both designs, decision matrix, no silent default)

**Realization rule:** P&L is realized per closing **fill**, allocated to tranches (specific lots) by the allocation policy below. A partial close realizes the allocated fraction and leaves the remainder's basis untouched. Unrealized (1100/4600) is recomputed at each mark for open lots only.

**The mechanical fact the policy must respect (Bot Dev, §8-3):** MT5 **hedging** accounts realize per-ticket — each position is its own lot, so *specific identification is exact and free*. MT5 **netting** accounts hold one position per symbol at a **volume-weighted average open price**, and the broker computes each reducing deal's `DEAL_PROFIT` against that average — i.e., the broker's book is **average-cost**, not FIFO. Any internal policy that differs from the broker's will show per-deal price differences that are *not errors* — they net to zero at flat but poison per-deal reconciliation if unmodeled.

**Design: three coexisting views, each serving exactly one consumer.**

1. **Broker book (Book B)** — mirrors the broker's method: per-ticket on hedging, average-cost on netting. This is what posts to 4000, because 4000 must reconcile to broker cash **per deal, exactly** (tolerance = rounding only). Non-negotiable.
2. **Attribution tranche ledger (Book A)** — specific-lot tranches keyed `(signal_id, child_id)` (schema §4.2). Consumes closing deals via the allocation policy; its per-tranche price P&L uses the tranche's own entry price. Book A total = Book B total **by construction** (the allocation is a partition of each deal, §4.2), but per-deal splits differ; the per-deal difference is carried as a tranche-level dimension (`basis_translation_micro`), summing to zero per deal. This is what attribution (§4) and the learning loop consume.
3. **Tax-lot view (Book T)** — computed on export (§7) from Book A's tranche history under a **configurable** relief policy `accounting.tax_lot_policy ∈ {FIFO, specific_lot}`. **No default is shipped**: `defaults.yaml` leaves it unset; config validation permits trading but **refuses to run tax exports** until the operator sets it (with a GUI prompt explaining the choice belongs to their accountant). This is the "no silent default" demanded by F-002's OPEN status, applied to the accounting dimension.

**Decision matrix (internal realization method for Book B on netting accounts):**

| Criterion | (a) Mirror-broker avg-cost **(recommended)** | (b) FIFO internal | (c) Specific-lot internal |
|---|---|---|---|
| Per-deal reconciliation vs `DEAL_PROFIT` | exact (rounding-only tolerance) | differs per deal; needs translation layer; recon noise | differs per deal; same problem |
| Attribution fidelity | avg mixes lots — but under F-002 degraded mode B (one child per instrument, Pass 3 §8.7) lots within a position belong to **one child**, so child-level attribution is unharmed | good | best |
| Tax-convention alignment | neutral (Book T handles tax) | FIFO is a common convention — but that's Book T's job | specific-lot common option — Book T's job |
| Failure mode | none new | every deal generates a pseudo-diff to suppress — a standing hole in the diff taxonomy (Auditor veto: a tolerance you must always apply is a check you no longer have) | as (b) |

**Recommended default: (a)** for Book B, with Book A providing lot-level attribution and Book T providing tax-policy flexibility. Under the future option-C synthetic tranche design (Pass 4, if ever built), Book A is already the tranche ledger it needs — this pass's schema is forward-compatible by construction.

### 1.5 Mark-to-market: cadence and price side

- **Price side (binding):** a long position is marked at **bid**, a short at **ask** — the price at which the position could actually be closed now. Mid is display-only (Day Trader objection and resolution, §8-4). The mark price source is the same quote snapshot the periodic reconcile heartbeat consumed, so equity checks compare like with like.
- **Cadence:** a `ledger.mark` batch is posted (i) with every **periodic reconcile** (60 s heartbeat-fresh, Pass 3 §3.3), (ii) on every exec event touching the position, (iii) at snapshot events (§1.3 of Pass 3), and (iv) at day boundary for the daily P&L cut. Between marks, GUI unrealized figures are projections off the last mark plus live ticks — labeled "indicative" in the UI; only marks enter the ledger.
- **Conversion at mark:** unrealized amounts in profit currency convert at the **mark-time** rate under the §3.1 hierarchy; the rate and source ride on each mark line. Realized never uses mark-time rates (§3.2).

---

## §2 Every cost captured

### 2.1 Commission

**Models supported (config per broker overlay, 04§B1):**

| Model | Formula (account ccy) | Typical use |
|---|---|---|
| `per_lot` | `rate_ccy_per_lot × lots` (side or round-turn flag) | RAW-tier FX ($3.5/side/lot ≈ the Pass-2 $7 RT) |
| `per_deal` | flat per deal | some CFD brokers |
| `percent_notional` | `bps × notional × conv(t_fill)` | stock/crypto CFDs |
| `none` | 0 | STD-tier markup pricing |

**Discovery reality (Bot Dev):** MT5 does not reliably expose commission schedules via `symbol_info`; the *configured* model is therefore a **prediction**, and the per-deal `DEAL_COMMISSION` + `DEAL_FEE` fields are the **truth**. Posting uses truth (§1.3); the predicted amount rides as a dimension; `|posted − predicted| > T_comm` (§5.3) raises `COMMISSION_MISMATCH` — which catches both config errors and silent broker schedule changes (the F-007 class, money edition). The viability gate's `commission_ticks` (F-003) is fed from **measured** per-deal postings once ≥ 30 deals exist per instrument (hypothesis threshold), replacing the configured prior — priors as floors per F-029 (never model commission *below* prior − margin).

### 2.2 Swap accrual, triple-swap day, verification (F-020 owned here; Pass 2 §2.3e math adopted)

**Discovery inputs (03§B1, extended):** per symbol — `swap_long`, `swap_short`, `SYMBOL_SWAP_MODE` (points / base-ccy / margin-ccy / deposit-ccy / interest-based / disabled), and `SYMBOL_SWAP_ROLLOVER3DAYS` (**the triple-swap weekday is a discoverable per-symbol field — discover it, never assume Wednesday**). The bridge's `/specs_full` endpoint (Pass 3 §6.2) must carry all four fields.

**Accrual formula (POINTS mode, the common case; per night, profit currency then converted):**

```
swap_profit_ccy = lots × contract_size × (swap_rate_points × point_size)     # point_size = 10^-digits, price units
swap_acct_micro = round_half_even(swap_profit_ccy × conv(profit_ccy→acct_ccy, t_rollover))
nights          = 1, or 3 if weekday(t_rollover, broker_tz) == swap_rollover3days
```

Mode variants: `CURRENCY_*` modes skip the point conversion (rate already in the named currency — convert that currency to account ccy); `INTEREST_*` modes: `notional × rate% / 360` per night (hypothesis day-count; verified per broker below). **Fail-safe rule (Auditor):** a symbol whose swap mode is unrecognized or whose fields are missing is **blocked from overnight holds** (session children unaffected; T1/TC-2/T3 refuse the instrument) until the mode is modeled — mirroring the sizing fail-safe philosophy (return 0, never guess).

**Rollover timing:** accrual fires on a core timer at the discovered broker day boundary (server midnight, offset measured continuously per Pass 3 §8.3 / F-033); weekend nights accrue on the triple day, not on Sat/Sun.

**Verification against broker truth (the F-020 "verified against actual statements" requirement):**
1. Where the broker cash-posts or position-posts swap nightly, the nightly posted value is compared to the accrual next morning in the daily money reconcile (§5.2), line class `SWAP_MISMATCH`, tolerance `T_swap`.
2. Where swap only materializes at close (`DEAL_SWAP`), the close-time settlement posting (§1.3) computes `true_up = DEAL_SWAP − Σ accruals`; `|true_up| > T_swap × nights_held` → `SWAP_MISMATCH`.
3. **Triple-day empirical check:** for each symbol, the first observed week of overnight holds must show the 3× accrual landing on the discovered weekday; a mismatch reclassifies the symbol's rollover day, emits `broker.spec_changed`-style WARN, and recomputes affected accruals. Three symbols mismatching → the broker offset itself is suspect (F-033 path).
4. **Rate-drift check (Swing Trader, §8-5):** swap rates change silently and often. Weekly job re-pulls specs and diffs swap fields; any change triggers T3/TC-2/TC-1 viability recompute (their edge math is swap-inclusive per Pass 2 — a swap change is an **edge event**, not bookkeeping trivia).

### 2.3 Spread & slippage: decision-price accounting (F-012, F-022 — the anti-cost-blindness core)

Three reference prices are frozen per entry/exit, all already available from Pass-3 events (no new capture path):

| Reference | Source | Meaning |
|---|---|---|
| `P_decision` | signal snapshot (02§B1) / `manage_position` action event: **mid** at decision time (or the intent `level` for BREAKOUT/LIMIT) | what the strategy believed it acted at |
| `P_ref` | `exec.telemetry_sample.requested_price`: quote at send (market), level (stop/limit) | what execution aimed at |
| `P_fill`, `mid_fill` | `exec.fill` + the ±5 s tick ring buffer (Pass 3 §1.2 `market.tick` journaling) | what actually happened, and the book at that instant |

**Per-fill decomposition (ticks, side-signed so costs are positive):**

```
spread_cost_ticks   = side × (P_fill − mid_fill) / tick_size        # what crossing the book cost
slippage_ticks      = side × (P_fill − P_ref)   / tick_size        # mechanism quality (F-022's number)
decision_lag_ticks  = side × (mid_fill − P_decision) / tick_size    # market moved while we decided/queued
                                                                    # (a latency diagnostic, NOT a broker cost)
```

For passive limits, `spread_cost_ticks ≤ 0` (spread avoided — **never "earned"**, F-012 wording adopted); the adverse-selection cost F-012 identified is *not* a fill-time number — it is measured as fill-vs-next-N-bar drift by the learning loop (03§A4) and lives in the cost model (Pass 7), not the ledger. The ledger records facts; the cost model records expectations. (Quant objection on this boundary and resolution: §8-2.)

**The waterfall identity (per closed tranche, `ledger.waterfall` event, identity-checked as invariant I9):**

```
net_cash_micro  =  gross_decision_micro                     # (P_decision_exit − P_decision_entry) × side × lots
                 − entry_exec_cost_micro                    # (spread + slippage)_entry × tick_value_conv
                 − exit_exec_cost_micro
                 − commission_micro − swap_micro
                 ± conversion_effect_micro                  # §3.4
                 ± basis_translation_micro                  # Book A↔B per-deal split, nets to 0 per deal (§1.4)
assert net_cash_micro == Σ(broker-book postings for this tranche)   # exact, micro-units
```

Every closed trade in the journal page renders this waterfall (Frontend seat, §8-7); the per-child aggregation of these terms **is** the Pass-2 cost-waterfall artifact (gross → spread → slippage → double-fill → swap → net) computed from live data — the same shape G1 reports use, so live-vs-backtest cost drift is a column-by-column diff, not a research project. F-022's realized-risk recompute already lives in Pass 3 §2.3 row 1; this section is its money mirror: the ledger stores **realized** cost, and approved-vs-realized deltas are queryable by construction.

### 2.4 Partial-fill cost allocation

Per fill, pro-rata by lots: each fill spawns/extends a tranche with its **own** `P_fill`, `spread_cost`, `slippage` (no averaging of execution quality across fills — averages are where costs hide). Deal-carried commission attaches to its deal's lots exactly as posted. OCO double-fill flatten costs (F-021) post as ordinary exit costs on the unwanted leg's tranche, tagged `cause=oco_double_fill` — so the measured `f_df · c_df` kill-term consumes ledger lines, not estimates.

---

## §3 Currency conversion correctness (F-023 owned here)

### 3.1 The currency triangle and the rate-source hierarchy

Per instrument, discovery yields three currencies: **base**, **profit** (quote — P&L accrues here), **margin**. The account has one **account currency**. Money truth needs one conversion: `profit_ccy → acct_ccy` (margin ccy affects the memo accounts only).

**Rate-source hierarchy (evaluated at each conversion, best available wins; every ledger line records which was used):**

| Rank | Source | Mechanics | Staleness bound |
|---|---|---|---|
| 1 | `FEED_CROSS` | live bid/ask of the conversion pair from our own subscribed feed; cross-computed via USD legs if no direct pair (e.g. EURJPY = EURUSD × USDJPY), using the **conservative side** (the side that reduces reported profit / increases reported loss) | quote age ≤ 5 s (hypothesis) |
| 2 | `TICKVALUE_IMPLIED` | `conv = tick_value_acct / (tick_size × contract_size)` from a **signal-time-fresh** `symbol_info` call — the F-023 fix (refresh at use, discovery copy is fallback only) | fetched ≤ 60 s before use |
| 3 | `STALE_LAST` | last known rate of either source | line flagged `conv_stale=true`; age > 1 h ⇒ WARN on the posting; **new entries blocked** for instruments whose conversion is stale > 1 h (sizing would be equally stale — this extends the Pass-3 §2.2 row-1 spec-freshness guard to conversion) |

Special case the hierarchy makes free: when the instrument's profit currency pairs with the account currency via the instrument itself (USD account + USDJPY: the conversion rate *is* the fill price), rank 1 is exact by definition.

### 3.2 Timestamp law (binding)

| Amount | Conversion timestamp |
|---|---|
| Realized price P&L | **fill time** of the closing fill (per fill, not per position) |
| Commission | fill time of the carrying deal |
| Swap accrual | rollover time of the accrual night |
| Unrealized mark | **mark time** |
| Sizing (`risk_amount` → lots) | signal time (already specced, F-023) |

Clock basis: `ts_event` from the core monotonic-anchored clock (Pass 3 §1.1); the F-033 health thresholds (§8.3) protect these timestamps — a > 750 ms NTP excursion blocks new session-scoped entries and therefore also blocks new conversion-bearing postings' *creation*, never their recording.

### 3.3 Worked examples (all rates illustrative)

**USD account:**

| Trade | Price math (profit ccy) | Conversion | Realized (acct) |
|---|---|---|---|
| EURUSD long 0.10 lot, 1.08420→1.08560 | 0.10×100,000×0.00140 = **$14.00** | profit ccy = acct ccy, rate 1.0 | $14.00 |
| USDJPY long 0.10 lot, 155.200→155.700 | 0.10×100,000×0.500 = **¥5,000** | JPY→USD at exit-fill USDJPY 155.700 (rank 1: the instrument is the pair): 5,000 ÷ 155.700 | $32.11 |
| XAUUSD long 0.10 lot (100 oz), 2400.00→2412.50 | 0.10×100×12.50 = **$125.00** | profit ccy USD | $125.00 |
| NAS100 long 1.0 lot (contract 1, $1/pt), 19850.0→19910.0 | 60.0 pts × $1 = **$60.00** | profit ccy USD | $60.00 |

**EUR account (same trades; EURUSD 1.08560 / EURJPY 168.93 = 1.0850×155.700 at the respective exit fills):**

| Trade | Profit-ccy amount | Conversion at exit-fill time | Realized (acct) |
|---|---|---|---|
| EURUSD | $14.00 | ÷ EURUSD **1.08560** — the exit fill itself is the rate (rank 1, exact) | €12.90 |
| USDJPY | ¥5,000 | ÷ EURJPY 168.93 (rank 1 cross via EURUSD×USDJPY; direct EURJPY feed preferred if subscribed) | €29.60 |
| XAUUSD | $125.00 | ÷ EURUSD 1.08500 (rate at *that* trade's exit fill time — note it differs from the EURUSD trade's 1.08560; per-fill timestamps, not per-day) | €115.21 |
| NAS100 | $60.00 | ÷ EURUSD 1.08500 | €55.30 |

**Drift example (§3.4 in action):** broker posts `DEAL_PROFIT` = €29.55 for the USDJPY trade (its internal desk rate, its internal timestamp) vs our €29.60 → **−€0.05 to account 4400**, 0.17% of the converted amount → below `T_conv` auto-accept, posted and trended, no alarm. Ten trades all drifting the same sign at 0.3% → the trend alarm fires even though each line passed (§5.3 note).

### 3.4 Conversion drift as a first-class reconciliation line

Because Book B posts broker truth to cash and 4000, and the decision book recomputes the same amount independently (own rate, own timestamp), **every converted realization produces a measurable drift** = ours − broker's. It posts to 4400 (per §1.3 rule (e)) and is classified in the daily run as `CONVERSION_MISMATCH` when above tolerance. This is the line that catches: broker conversion-spread markups (a real, quiet cost — literature-informed: retail brokers convert at 0.05–0.5% off mid), our stale rates (rank-3 lines correlate with big drifts → the flag works), and wrong-pair bugs (drift ≈ the rate ratio, unmistakable). 4400's monthly balance appears in the cost waterfall as its own column — conversion is a cost like spread, and it gets the same visibility.

---

## §4 Attribution — sums exactly, or alarms

### 4.1 The partition invariant and the unattributed bucket

Attribution dimensions on every ledger line (denormalized from the tranche at posting time): `child_id@version`, `family`, `instrument`, `regime_at_entry` (published label from the signal snapshot), `session`, `mechanism`, `closed_by`. Aggregation is a GROUP BY over posting lines — **no separate attribution store exists**, so attribution cannot drift from the ledger (nothing to reconcile because there is only one thing).

**Partition invariant (I7):** for any period, `Σ_child(realized+costs) + Σ_quarantine(1900-tagged) + 4900 + 4400_unattributed_share = account P&L` — **exactly**, in micro-units. The residual buckets are *members of the partition*, not leakage: money that cannot be attributed is money attributed to the bucket whose job is to be embarrassing.

**Alarm thresholds (hypothesis, Pass 7 calibrates):** |1900 balance| or |4900 monthly flow| > **0.1% of equity** → WARN + review queue; > **0.5%** → CRITICAL, halt-new-risk (breaker-style: entries blocked, exits and kill paths untouched per 02§A4). The Chair's rationale printed: an unattributed bucket below alarm is bookkeeping friction; above it, either the broker is doing something we don't understand or we are — both are trade-stopping facts.

### 4.2 Tranche bookkeeping (netting attribution, ties F-002)

**Tranche schema (Book A row; referenced by posting lines):**

```
tranche {tranche_id: uuid, position_id, signal_id, child_id@version, instrument,
         direction, lots_open, lots_remaining, entry_fill_event_id,
         entry_price, decision_price, cost_basis_micro, swap_accrued_micro,
         entry_costs: {spread_ticks, slippage_ticks, commission_micro},
         opened_ts, params_hash}
```

**Allocation of a reducing/closing deal to tranches (netting accounts; on hedging each ticket IS one tranche and this is the identity function):**

```
allocate_close(deal):
  T ← open tranches for (instrument), ordered:
        1. intent-matched (the deal's client_key → signal_id → its own tranche)   # a child closing ITS trade
        2. FIFO by opened_ts among the rest                                        # forced netting interactions
  rem ← deal.lots
  for t in T while rem > 0:
      take ← min(t.lots_remaining, rem);  rem −= take
      realized_B ← deal.profit_micro × take/deal.lots                # broker-book pro-rata (avg-cost basis)
      realized_A ← (deal.price − t.entry_price) × side × take × conv # attribution-book, tranche basis
      emit ledger.tranche_alloc{deal_id, tranche_id, take, realized_B,
                                basis_translation = realized_A − realized_B}
  assert rem == 0                       # else: UNKNOWN_DEAL path (§5.4) — never force-fit
  assert Σ realized_B == deal.profit_micro    # partition exact; rounding residual (≤1 μ-unit
                                              # per tranche) assigned to the youngest tranche
```

Under Pass-3's recommended degraded netting mode B, list T always has one child's tranches → attribution is exact trivially. If option C (multi-child netting) is ever built in Pass 4, this allocator plus the `basis_translation` dimension **is** its attribution reconciliation — designed now, forward-compatible, per Pass-1's instruction that C ships only with a reconciliation-complete design.

### 4.3 Human-intervention attribution

`closed_by ∈ {bot, human:gui:<user>, human:tg:<chat_id>, broker_stopout, quarantine_policy}` propagates from `position.closed` (Pass 3 §1.2) onto every closing ledger line; the actor arrives via the HMAC'd command channel (F-031 inherited — a money-mutating human action always carries an authenticated actor, so the human-decision analytics can never be polluted by unattributed closes). The learning loop's human-vs-bot comparison (05§D5) reads ledger lines filtered by `closed_by` and pairs each human close with a **counterfactual bot exit** simulated by replaying the child's `manage_position` policy forward on recorded bars. Board rule (Strategist, §8-10): counterfactual numbers are **analytics-grade** — rendered in the GUI with an `analytics (simulated)` badge, never posted to any 4xxx account, never summed with ledger-grade money. The ledger records what happened; only what happened.

---

## §5 Reconciliation against broker statements

### 5.1 Sources and ingestion path

| Source | Transport | Role |
|---|---|---|
| Deals/orders history (`HistoryDealsGet` etc.) | bridge `/deals_since` (Pass 3 §6.2, extended with `/deals_range`, `/balance_ops`) | **primary structured truth** — daily + monthly runs consume this |
| Account snapshot (balance/equity/margin) | existing heartbeat | continuous equity identity (§1.2) |
| Broker statement file (monthly; MT5 report export) | operator-triggered or scheduled bridge endpoint `/statement?from&to` returning the terminal's report file; raw file stored as a chained sidecar (SHA-256 in the `statement.ingested` event, exactly the Pass-3 §1.3 sidecar discipline) | **independent second rendering** of the same facts — catches bridge/API bugs, not just ledger bugs |

Infra seat ruling (§8-8): no investor-portal scraping — fragile, credentialed, and outside the WG perimeter. The statement parser is tolerant (per-broker template quirks); **parse failure is WARN, never blocking** — the structured deals path is the primary; the statement is the cross-check. A statement that parses but disagrees with the deals API is CRITICAL (the broker's two mouths disagree — stop and look).

### 5.2 Daily reconciliation algorithm

Runs at broker day close + 15 min (broker-offset-aware, F-006/F-033 clocks); also on demand. Extends Pass-3 §3.3 (which reconciles **state**: positions/orders); this run reconciles **money** and consumes §3.3's output rather than re-deriving it.

```
money_reconcile_daily(day):
  # 0. preconditions
  require latest recon.run verdict ∈ {CLEAN, REPAIRED}          # state recon first; money recon
                                                                 # on unreconciled state is noise
  B ← bridge.deals_range(day.start_broker, day.end_broker)       # deals + balance ops, broker truth
  L ← ledger.postings(effective_day = day)                       # our lines, mapped to broker day
  diffs ← []

  # 1. per-deal matching (deal_id is the join key; we stored it at posting time)
  for deal in B.trade_deals:
      p ← L.by_deal_id(deal.ticket)
      if p is None:
          diffs += MISSING_DEAL(deal)                            # broker has it, ledger doesn't
          continue
      if |p.price_pnl − deal.profit|        > T_price(deal):  diffs += PRICE_MISMATCH(deal, Δ)
      if |p.swap_settled − deal.swap|       > T_swap(deal):   diffs += SWAP_MISMATCH(deal, Δ)
      if |p.commission − deal.commission_fee| > T_comm:       diffs += COMMISSION_MISMATCH(deal, Δ)
      if |p.our_converted − deal.profit|    > T_conv(deal):   diffs += CONVERSION_MISMATCH(deal, Δ)
  for p in L.deal_postings not matched:                          # ledger has it, broker doesn't
      diffs += (TIMING(p) if broker_ts(p) within ±10 min of day boundary
                else UNKNOWN_LEDGER_LINE(p))                     # CRITICAL class — we invented money
  for op in B.balance_ops:
      if not L.by_deal_id(op.ticket): diffs += BALANCE_OP_UNSEEN(op)

  # 2. cash equation (independent of per-deal matching — catches what matching can't)
  residual ← B.balance_end − (L.cash_1000_start + Σ L.day_cash_deltas)
  if |residual| ≤ T_cash_accept:   post residual → 4900 (auto-accept, logged)
  elif |residual| ≤ T_cash_warn:   diffs += CASH_EQUATION(residual, WARN)
  else:                            diffs += CASH_EQUATION(residual, CRITICAL)

  # 3. equity identity (toleranced — marks race quotes)
  if |(1000+1100+1150) − B.equity_at(day.end)| > T_mtm:  diffs += MTM_DIVERGENCE(Δ, WARN)

  # 4. resolve, escalate, emit
  for d in diffs: classify → action per §5.4 table
  rebuild money projection from post-resolution postings          # never patch incrementally
                                                                  # (same law as Pass 3 §3.3)
  emit recon.money_run{day, counts per class, residual, verdict}
```

Timing diffs self-heal: a `TIMING` line is parked and auto-matched by the next day's run (deal landed across the boundary); parked > 2 days → escalates to its underlying class.

### 5.3 Tolerance defaults (all **hypothesis** — calibrated in Pass 7 from the first 60 days of demo reconciles; units stated per line)

| Symbol | Applies to | Default | Unit / rationale |
|---|---|---|---|
| `T_price` | per-deal price P&L | `1 tick × tick_value × lots` | one tick of rounding between price bases; anything more is not rounding |
| `T_swap` | per position-night (or ×nights at close true-up) | `max(0.10 acct-ccy, 10% of predicted)` | swap rates are coarse and change silently; relative band + absolute floor |
| `T_comm` | per deal | `0.01 acct-ccy` | commission is contractual — near-exact or it's a schedule change |
| `T_conv` | per converted realization | auto-accept ≤ **0.20%** of converted amount; WARN ≤ 0.5%; CRITICAL > 1.0% | broker conversion spread 0.05–0.5% (literature-informed) sits inside auto-accept |
| `T_cash_accept` / `T_cash_warn` | daily cash equation | ≤ `max(0.01 acct-ccy, 0.02% equity)` / ≤ 0.2% equity | above warn ⇒ CRITICAL **halt-new-risk** |
| `T_mtm` | equity identity | `0.05% equity + Σ(open spread × lots × tick_value)` | quote-race allowance, spread-aware |
| Trend guard | every toleranced class | 10-day same-sign drift of a class's *summed* residual > 3× its per-line tolerance → WARN regardless of per-line passes | the Chair's rule: tolerances hide small thefts; trends un-hide them |

### 5.4 Diff classification taxonomy and escalation

| Class | Meaning | Default action |
|---|---|---|
| `ROUNDING` | within per-line tolerance | auto-accept; post to residual account; counted |
| `TIMING` | boundary-straddling deal | park; auto-match next run; escalate after 2 days |
| `PRICE_MISMATCH` | price P&L differs beyond `T_price` | WARN + review queue; 3+ same instrument/day → CRITICAL (basis or spec error — F-007 money edition) |
| `SWAP_MISMATCH` | posted vs predicted swap | WARN; systematic (≥3 nights, one symbol) → refresh specs, recompute accruals, re-run; still failing → CRITICAL |
| `COMMISSION_MISMATCH` | schedule disagreement | WARN + freeze commission-fed viability inputs to priors until resolved (F-029 floor rule) |
| `CONVERSION_MISMATCH` | drift beyond `T_conv` | per §5.3 ladder; rank-3 (`STALE_LAST`) lines involved → also fix the rate feed, that's ours |
| `MISSING_DEAL` | broker deal absent from ledger | **CRITICAL**: post to 1900 immediately (cash truth first), then attribute via §3.3's orphan machinery; unattributable → stays in 1900, alarmed by §4.1 |
| `UNKNOWN_LEDGER_LINE` | ledger money with no broker fact | **CRITICAL + halt-new-risk**: the ledger invented money; REFUSE-class per Pass-3 §3.3 (projection can't be trusted) |
| `BALANCE_OP_UNSEEN` | deposit/withdrawal/credit we didn't log | CRITICAL if unexpected (theft/fee-grab detection); operator can pre-register expected movements which then auto-accept |
| `CASH_EQUATION` / `MTM_DIVERGENCE` | §5.2 steps 2–3 | per §5.3 ladders |

Escalation semantics are breaker-grade (02§A4): WARN → alert + queue; CRITICAL → **halt new risk** (entries blocked; exits, stop management, and both red buttons fully available), Telegram+GUI CRITICAL piercing quiet hours (F-039 mapping), human ack to resume. Auto-accept is never silent: every auto-accepted diff is a posted, counted, trended event.

### 5.5 Monthly statement reconciliation

At month close: (1) re-derive the month's P&L **from the archived event log** (Pass 3 §1.3 parquet archive + chain) — not from the running projection — proving the archive replays to the same money (this doubles as the monthly archive-integrity drill); (2) ingest the broker statement file (§5.1), parse period totals: closed P&L, swap, commission, deposits/withdrawals, end balance/equity; (3) three-way compare — ledger vs deals-API vs statement — any pairwise disagreement beyond the §5.3 tolerances is CRITICAL (two broker renderings disagreeing is a broker bug we must not paper over); (4) emit `recon.money_run{scope: MONTHLY}` + a signed-off monthly close artifact (totals + chain head hash + statement SHA-256) that §7's exports cite. A month is **closed** only when its run verdict is CLEAN/auto-accepted; tax exports refuse to include unclosed months (they'll export, but stamped `PROVISIONAL`).

---

## §6 The immutable audit chain

### 6.1 Linkage (extends Pass 3 §1 — no new mechanism, new members only)

The chain already exists: envelope `seq`/`prev_hash` (F-004), `correlation_id = signal_id`, `parent_ids`. This pass adds the money events as chain members: `ledger.posting`, `ledger.tranche_alloc`, `ledger.accrual`, `ledger.mark`, `ledger.waterfall`, `recon.money_run`, `statement.ingested`, `audit.verify_run`. The full causal line for one trade:

```
signal.generated ─ risk.evaluated ─ signal.state_changed* ─ exec.intent_persisted ─
exec.order_submitted ─ exec.order_ack ─ exec.fill ─ position.opened ─
[ledger.accrual*] ─ [ledger.mark*] ─ exec.fill(close) ─ position.closed ─
ledger.tranche_alloc ─ ledger.posting ─ ledger.waterfall
```

every arrow being a `parent_ids` reference, all under one `correlation_id`, all hash-chained. An auditor with the SQLite file and 30 lines of Python can verify the whole set below — that is the design goal stated as a deliverable.

### 6.2 The invariant set (mechanically verifiable; one line each)

| ID | Invariant |
|---|---|
| I1 | Every `exec.fill` has exactly one `exec.order_submitted` ancestor via `client_key`, **or** is quarantine-adopted with a `recon.run`/`recon.money_run` parent — no parentless fills |
| I2 | Every `ledger.posting` has ≥ 1 parent that is a fill, accrual timer, mark batch, recon run, or balance op — **no orphan money movements** (enforced at write, §1.1-4) |
| I3 | Every posting balances: Σ DR = Σ CR, exact in micro-units (enforced at write) |
| I4 | Trial balance internal identity (§1.2) holds exactly at every snapshot event |
| I5 | External equity identity holds within `T_mtm` at every mark batch |
| I6 | Every `position.closed`'s `pnl_ccy + swap_ccy + commission_ccy` equals the sum of its ledger postings, exactly |
| I7 | Attribution partition (§4.1) sums exactly to account P&L, residual buckets included |
| I8 | Tranche conservation: Σ `lots_remaining` over a position's tranches = position lots, always; every allocation partitions its deal exactly (§4.2 asserts) |
| I9 | Every `ledger.waterfall` sums to its tranche's net cash postings, exactly (§2.3) |
| I10 | Hash chain unbroken and `seq` gapless across all of the above (Pass 3 §1.3, inherited) |

### 6.3 The audit-verification job

| Cadence | Checks | On failure |
|---|---|---|
| **At write** (sole writer) | I2, I3 | append refused; the *attempt* is logged (`audit.append_refused`, CRITICAL) — a code path tried to move unbalanced/orphan money |
| **Every mark/periodic recon** (60 s) | I5 on fresh data; I4 incremental | WARN → CRITICAL per §5.3 ladders |
| **Daily 00:20 UTC** (after the Pass-3 backup job, against the **restored backup copy** — verifying the backup and the books in one pass, per the Chair's "an unverified backup is no backup") | full-day walk of I1–I10 + chain segment | `audit.verify_run` CRITICAL → halt-new-risk + human ack |
| **Monthly** | full-history I1–I10 from archive parquet + live DB, plus §5.5 three-way | month refuses to close |
| **CI** (extends Pass 3 §7.2 P-series) | **P11** posting-balance fuzz (random events → postings always balance, rounding law holds); **P12** allocation partition (random deal/tranche sets → exact partition, residual ≤ 1 μ-unit, youngest-tranche rule); **P13** conversion round-trip (rate hierarchy under stale/missing feeds → correct source recorded, conservative side chosen); **P14** waterfall identity on the §7.3 scenario library's fills (incl. OCO double-fill and VETO_CLOSING trades) | merge-blocking |

Negative controls (Pass-1 T7, applied to this pass's own machinery): CI plants a corrupted posting (unbalanced), a parentless posting, a mis-allocated deal, and a wrong-rate conversion into a fixture log — the daily job **must** flag all four or the audit job itself fails the build. An audit that cannot catch a planted error certifies nothing.

---

## §7 Tax-ready reporting

### 7.1 Export catalog (CSV; UTF-8; ISO-8601 UTC timestamps + broker-time columns; amounts in account currency to 2 dp **plus** micro-unit integer columns for lossless re-derivation)

**`closed_trades_<period>.csv`** — one row per closed tranche (Book T policy applied, stamped in header):
`tranche_id, position_id, deal_ids, child_id, family, instrument, direction, lots, open_ts_utc, open_ts_broker, close_ts_utc, close_ts_broker, entry_price, exit_price, gross_pnl_profit_ccy, profit_ccy, conv_rate, conv_rate_ts, conv_source, gross_pnl_acct, commission_acct, swap_acct, net_pnl_acct, net_pnl_micro, spread_cost_ticks, slippage_ticks, closed_by, regime_at_entry, lot_policy`

**`realized_by_period.csv`** — per configurable period bucket: `period_start, period_end, trades, gross_acct, commission_acct, swap_acct, conversion_gl_acct, net_acct, deposits, withdrawals, end_balance_broker, recon_verdict`
**`swap_summary.csv`** — per instrument × month: nights, triple-nights, predicted, posted, true-up.
**`commission_summary.csv`** — per instrument × month: deals, posted, model-predicted, mismatch count.
**`cash_movements.csv`** — every balance op with broker ticket, classification, and pre-registration status.

### 7.2 Configurability and determinism

- **Jurisdiction-agnostic period boundaries:** `reporting.period ∈ {calendar_year, uk_apr6, custom(start_mmdd)}` and `reporting.boundary_tz` (IANA) — the *operator's accountant's* year, cut in the *operator's* timezone, regardless of broker server days (the daily recon's broker-day mapping handles the translation; boundary-straddling deals land per the timestamp law §3.2).
- **Lot policy stamped, never defaulted** (§1.4 Book T): every export header carries `lot_policy`, `conv-source statistics`, the period's `recon.money_run` verdicts, and the chain head hash at export time. Same period + same policy + same chain head ⇒ **byte-identical file** (asserted in CI, same discipline as the Pass-3 run-card determinism check).
- Exports are generated from **closed months only** (§5.5) unless the operator explicitly requests `--provisional`, which watermarks every page/row.

### 7.3 What the system deliberately does NOT do (printed in the GUI export screen, verbatim)

The system exports **records**, not returns. It does not: compute tax owed; classify instruments under any jurisdiction's regimes (e.g. US §988 vs §1256, UK CGT vs income, wash-sale or bed-and-breakfast adjustments); choose a lot-relief policy for you; or provide tax advice of any kind. The lot-policy setting exists because your accountant must choose it; the export tells them exactly which policy produced the numbers. Legal/compliance framing reviewed by the board: this is a bookkeeping instrument — treat its output as source data for a professional, and keep the raw event log; it is the audit trail that makes the CSVs defensible.

---

## §8 Board debate log (objections that changed content)

1. **Backend Architect vs full double-entry** — "a signed cash-flow log reconciles fine; double-entry is ceremony." Chair's rebuttal: single-entry logs can *record* a leak but cannot *notice* one — balance is the noticing mechanism, and I3-at-write makes an unbalanced code path a build-time bug instead of a tax-time archaeology. Resolution: double-entry retained, but postings are **machine-generated per event schema** (never hand-written), collapsing the ceremony cost. Changed §1.1.
2. **Quant vs slippage/adverse-selection in the ledger** — "expectation terms don't belong in books of fact." Sustained in part: fill-time spread/slippage are facts and stay (§2.3); adverse-selection is an expectation and was **moved out** of the ledger into the Pass-7 cost model, with the ledger's fill-vs-drift telemetry as its measurement feed. The ledger/cost-model boundary is now a stated law.
3. **Bot Dev on netting realization** — surfaced that MT5 netting realizes at *average cost*, which killed the draft's FIFO-internal Book B (it would have produced a permanent per-deal pseudo-diff). Forced the mirror-broker recommendation and the three-book separation (§1.4). The Chair notes this is the pass's most valuable single catch: a wrong Book-B basis would have made per-deal reconciliation permanently noisy, and permanently-noisy reconciliation gets muted (the F-013 lesson, money edition).
4. **Day Trader vs bid/ask marking** — "marking longs at bid makes every fresh position show an instant loss; operators will distrust the dashboard." Frontend Architect sided with the ledger: the instant loss **is the spread you already paid** — hiding it is cost blindness at the UI layer. Resolution: ledger marks at closable price; GUI shows both ("value if closed now" primary, mid secondary, labeled). Changed §1.5 + a UI requirement exported to the interfaces backlog.
5. **Swing Trader on swap verification cadence** — draft verified swap only at close; for TC-2 (months-held) a wrong swap model compounds for weeks unseen. Forced nightly accrual-vs-posted checking where the broker exposes it, the weekly spec re-pull, and the reclassification path for the triple-day (§2.2). Also insisted the triple-day be **discovered** per symbol, not assumed Wednesday — index/energy CFDs commonly roll 3× on Friday (literature-informed).
6. **Strategist vs CRITICAL-halt on conversion mismatch** — "a 0.6% conversion drift on one trade must not stop a healthy book." Resolution: the §5.3 ladder (accept/WARN/CRITICAL at 0.2/0.5/1.0%) plus the trend guard, so single-line noise never halts but systematic drift always surfaces. The Chair accepted on condition of the trend rule — which then generalized to every toleranced class.
7. **Frontend Architect** — required the per-trade waterfall (§2.3) rendered in the journal page with the same column names as the G1 cost-waterfall artifact, so a human can eyeball live-vs-backtest cost drift per column. Accepted; naming unified.
8. **Networking/Infra vs statement scraping** — vetoed investor-portal scraping (credentials outside the WG perimeter, brittle HTML). Resolution: terminal-generated report via a bridge endpoint, raw file chained as a sidecar; parse failures WARN-only (§5.1). Also pinned the money-recon scheduling to the *measured* broker day boundary, not server-midnight folklore (F-033 inheritance).
9. **Chair's red-team of "sums EXACTLY"** — floating point makes "exactly" a lie in doubles. Forced the integer micro-unit representation, the single-round half-even law, the posting-level residual rule, and property tests P11–P14. "Exact" in this document now means *integer-exact*, and the word is earned.
10. **Master Strategist on counterfactual analytics** — insisted simulated "what the bot would have done" numbers be quarantined from ledger-grade money (§4.3), after the Chair showed a mockup where a summed dashboard implied the account had earned the counterfactual. Analytics-grade badge rule adopted board-wide (applies to Pass-7 expectation surfaces too).

---

## §9 Findings-resolution table

| Finding | What this pass does | Section | Status |
|---|---|---|---|
| F-002 (accounting dimension) | Three-book design; mirror-broker Book B decision matrix (recommended (a)); tranche allocator + `basis_translation` = the attribution reconciliation any future option-C design must use; tax-lot policy has **no silent default** | §1.4, §4.2, §7.2 | **RESOLVED for accounting**; account-mode default remains OPEN-FOR-HUMAN (Pass 3 §8.7), Pass-8 decision sheet |
| F-003 | Corrected tick arithmetic consumed throughout; ledger feeds the gate **measured** commission/spread/slippage from postings (priors as floors) | §2.1, §2.3 | ADOPTED (formula was RESOLVED in Pass 1; threshold calibration stays Pass 7) |
| F-004 (money residue) | Money events join the chain; daily verification runs against the **restored backup**; monthly re-derivation from archive; planted-error negative controls for the audit job itself | §6.1–6.3, §5.5 | RESOLVED (extends Pass 3 §1.3; contradicts nothing) |
| F-012 (accounting side) | "Avoid, never earn" encoded in `spread_cost_ticks` sign convention; fact/expectation boundary: fill-time costs in ledger, adverse-selection in cost model fed by ledger telemetry | §2.3 | RESOLVED here; fill-simulation spec remains Pass 7 |
| F-020 | Swap accrual formulas per discovered mode; triple-day **discovered** (`SYMBOL_SWAP_ROLLOVER3DAYS`) + empirically verified; nightly/close true-up; weekly rate-drift check wired to T3/TC-2 viability | §2.2 | **RESOLVED** (Pass 2 resolved the strategy math; this pass supplies the books + verification) |
| F-022 (money mirror) | Realized costs per fill in the ledger; approved-vs-realized queryable; waterfall identity I9 | §2.3, §6.2 | RESOLVED (state-machine side was Pass 3 §2.3) |
| F-023 | Rate-source hierarchy with freshness bounds; timestamp law (fill-time realized, mark-time unrealized, signal-time sizing); stale-conversion blocks new entries; every line carries source+ts | §3.1–3.2 | **RESOLVED** |
| F-029 (capture side) | Measured commission/spread/slippage flow from postings with priors-as-floors; conversion drift and swap true-up added to the cost waterfall as first-class columns | §2.1, §3.4 | PARTIAL — thresholds/hysteresis calibration owned by Pass 7 as assigned |
| F-032 (money residue) | Quarantine money lives in 1900 inside the partition invariant; attribution moves are chained re-postings; unattributed alarmed at 0.1/0.5% (hyp.) | §4.1, §1.3 | RESOLVED (attribution mechanics were Pass 3 §3.1/§3.3) |
| F-031 (inherited) | Money-mutating human commands (manual close, expected-balance-op pre-registration, month-close ack, provisional export) ride the §8.5 HMAC channel; `closed_by` actor integrity guaranteed for §4.3 | §4.3, §5.4 | INHERITED-AND-APPLIED |
| F-033 (inherited residue) | Conversion/accrual timestamps bound to the Pass-3 clock discipline; money-recon scheduled off the *measured* broker offset; >750 ms NTP excursion blocks new conversion-bearing entries | §3.2, §5.2 | INHERITED-AND-APPLIED (monitoring surfacing to the ops/interfaces backlog) |
| F-026, F-009 (Pass-1 "PASS-6" routing, non-money subjects) | Confirmed **not owned here** post-re-scope: F-026 (config provenance UI) and F-009 transport details belong to the interfaces/ops content (Pass 3 resolved semantics; surfacing → Pass 7/8 backlog per Pass-3 §10) | — | RE-ROUTED, explicitly |

**Constraints exported to Passes 7–8:**
- **Pass 7 (validation/learning):** calibrate all §5.3 tolerances from ≥ 60 demo days of `recon.money_run` data; calibrate §4.1 unattributed thresholds; the viability gate must consume **ledger-measured** costs once sample thresholds hit (F-029 floors); the backtester's SimAccount must produce the same posting stream (P11–P14 run against sim logs too — a backtest whose books don't balance is inadmissible as G1 evidence); adverse-selection estimator consumes §2.3 telemetry; negative/positive controls for the audit job are part of the T7 gate-control suite.
- **Pass 8 (synthesis):** human decision sheet gains two accounting entries — `accounting.tax_lot_policy` (mandatory before first tax export; accountant's choice) and pre-registration policy for expected balance ops; the F-002 account-mode decision carries this pass's note that degraded mode B also makes the **books** trivially exact, which is an argument for B the Pass-3 matrix didn't include.

— End of Pass 6. Every tolerance, threshold, and cadence above is labeled hypothesis until Pass 7 calibrates it; every formula's units are stated; the books balance in integers or they refuse to be books.
