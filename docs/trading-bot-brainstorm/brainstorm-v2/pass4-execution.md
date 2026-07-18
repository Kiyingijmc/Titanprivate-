# PASS 4 — EXECUTION & MICROSTRUCTURE REALITY

**Co-chairs:** Profitable Retail Day Trader/Scalper + Profitable Swing Trader + Principal Algo-Bot Developer. **Contributors:** all ten seats; the Auditor red-teams per board rule (b).
**Inputs (read in full):** `00`–`05`, `pass1-audit.md` (39 findings), `pass2-research.md`, `pass3-systems.md` §1–§4 (final; built upon, never contradicted). Pass 3 §5.2's `FillModel` protocol existed at read time and is treated as **informative only** — §4 below implements behind that seam but depends on nothing beyond Pass 3 §4.
**Ownership rule applied:** this pass owns and resolves every finding whose subject matter is execution / microstructure / broker behavior / fill modeling, regardless of the pass number its Pass-1 disposition cites. Owned here: **F-002 (execution-layer design, default still OPEN), F-006, F-007, F-010, F-011 (execution/gap-fill realities), F-012 (fill-simulation spec), F-021 (blackout mechanics + OCO grace window), F-023, F-025, F-029 (execution min-sample rules)**, plus the execution arms of F-001 and F-022. §7 is the resolution table.
**Labeling:** every number is **(measured)** — nothing qualifies yet — **(literature-informed)**, or **(hypothesis)**, per the Pass-2 honesty rules.

**Canonical vocabulary used throughout** (consumed by §2–§5 and by the simulator): `session_id ∈ {asia, london, overlap, ny_late, rollover}` for fx/metals/crypto-CFD; `{pre_open, open_5, cash, close_15, closed}` for exchange-hours instruments. `vol_state ∈ {low, normal, high, extreme}` = EWMA-vol percentile buckets {<25, 25–75, 75–95, >95} against the rolling 90-day distribution (hypothesis buckets; Pass 3 §4.3 EWMA node is the source). `news_state ∈ {clear, pre_red, post_red}` from the calendar service (§1.0).

---

## §1 Scenario stress book

Each scenario: **(R)** what actually happens at a retail MT5 broker → **(D)** what the current design (docs 02/03 + Pass 3 §2–§3) does → **(B)** where it breaks → **(F)** the fix, with thresholds and state-machine deltas.

### §1.0 Foundation: the calendar & time service (resolves F-006, F-025)

Every scenario below is time-anchored, so the service Pass 1 demanded is specified first. Module `calendar_svc/` (Pass 3 §6.1 stub), sole owner of time semantics:

| Component | Spec |
|---|---|
| **Session tables** | Generated weekly from tzdb, per instrument: fx sessions anchored `Asia/Tokyo` (asia), `Europe/London` (london/overlap), `America/New_York` (ny_late, **rollover = 17:00 America/New_York**, not a UTC constant — it floats with US DST); exchange instruments anchored to their exchange zone (`America/New_York` US indices, `Europe/Berlin` DAX). Output: lookup table `(instrument, ts_utc) → session_id` + `session.boundary` events consumed by the feature engine (Pass 3 §4.3 session-range node). |
| **DST mismatch windows** | The two ~2–3-week windows/year where US and EU DST are offset are precomputed and published as `calendar.dst_mismatch(active:bool, markets:[...])`. Per Pass 2 §3.1: session children are **blocked** during mismatch windows until the service passes its parity tests (named test cases: 2026-03-08→03-29, 2026-10-25→11-01 patterns, regenerated yearly). |
| **Broker clock offset** | Measured continuously: `offset = median(tick.ts_broker − ts_recv)` over a rolling 500-tick window per connection (hypothesis window). Discovery stores the broker's *claimed* server zone; the measured offset is the authority. Drift of the measured offset by > 60 s from its session baseline (hypothesis) → WARN + session-scoped entries blocked (extends Pass 3 §2.5 `UP_UNVERIFIED` check into steady state). |
| **News calendar** | Red-calendar events ingested weekly + refreshed 4×/day from a configured source; each event carries `(ts, currencies, impact)`. Failure mode: **stale news calendar (> 26 h old) ⇒ treat every session as `pre_red` for entry gating** (fail-closed, hypothesis staleness bound) + WARN. |
| **Expected-bar grid / staleness (F-025)** | The service publishes `expected_next_bar(instrument, tf, ts)` honoring sessions, weekends, holidays. Feed staleness (Pass 3 `market.feed_staleness_changed`) is judged against this grid: quote-age thresholds per state — trading session: STALE at `quote_age > max(10 s, 2× median inter-tick gap for this session)` (hypothesis), DEAD at 60 s; outside session: no alarm (expected_by_calendar=false). The DAX-evening false-trip and the dead-D1-feed missed-trip from F-025 are both unit tests. |
| **Trading-day boundary** | The bot owns D1/weekly boundaries (per F-006): trading day = 17:00→17:00 America/New_York for fx/metals; exchange calendar for indices. Daily-loss breaker (02§A4) resets on the bot's boundary, never the broker's candle. |

**Hard sequencing dependency (restating Pass 2 §7-10):** no session-scoped child (M1, M2, M4, T4) and no rollover/news gating below can go live before `calendar_svc` passes the DST test cases.

### §1.1 News spread blowouts (red-calendar seconds) — F-021 blackout mechanics

**(R)** In the 1–5 s around a red release, retail MT5 feeds show: spread 5–20× for 30–120 s (literature-informed), decaying roughly exponentially; quote gaps of tens of ticks between consecutive ticks; stop orders filled with 5–50 tick adverse slippage (literature-informed); market orders answered with requotes/`OFF_QUOTES`; some brokers widen `stops_level` minutes *before* the release (see §1.5). Limit orders fill instantly and adversely — the blowout trades *through* passive levels.

**(D)** Doc 03§A2's spread gate (`gate_ratio > 3.0 → HOLD`) blocks IMMEDIATE entries; M1 and (post-F-021) T4 carry ±60 min strategy-level blackouts. Nothing else: resting orders from *other* children keep working through the release, trailing modifies keep firing, and a child with no blackout (T1, T2, M3) can route an IMMEDIATE straight into the blowout — the spread gate holds it, retries, and may release it into the still-elevated tail.

**(B)** Three holes: (1) resting stops/limits are live through the event — a T1 breakout stop placed Tuesday fills into an NFP spike with tail slippage; (2) the spread gate's retry loop can fire the *first* second `gate_ratio ≤ 3.0`, which is still 2–3× normal cost; (3) trailing modifies during the blowout hit `FREEZE`/`STOPS_LEVEL` rejects in bursts, burning the modify budget (§3.4) and spamming WARN.

**(F)** Two-layer blackout, adopted (execution layer is child-agnostic — it protects children that never heard of news):

| Layer | Scope | Window (hypothesis) | Behavior |
|---|---|---|---|
| **Strategy blackout** (exists, Pass 2) | M1/T4 per dossier; per-child config | ±60 min | no signal generation for affected currencies |
| **Execution hard gate** (new) | ALL new entry orders (market, stop, limit placement) on instruments whose base/quote/underlying matches the event currencies | **T−120 s → T+180 s** | entry placements queued (not dropped): released when both (a) window over and (b) `gate_ratio ≤ 1.5` for 3 consecutive samples at 2 s cadence (hypothesis); if `valid_until` passes while queued → EXPIRED normally |
| **Resting-order policy** (new) | working entry orders (stops/limits) inside T−120 s | per child `news_resting_policy ∈ {keep, suspend}` | default: **meanrev children `suspend`** (cancel at T−120 s, re-place after gate clears if signal still valid per `invalidation()`), **trend children `keep`** (a breakout through news is within the thesis; the cost is priced in the simulator §4.6). Suspend/re-place rides the normal OMS cancel/place paths — the F-010 already-filled arm covers the race. |
| **Exits & stops** | always | never blocked | position stop modifies *toward safety* (tighten/BE) allowed at any time, requote-tolerant with 5 attempts; loosening modifies and reprices deferred until T+180 s. Kill paths bypass everything, as ever. |

State-machine delta: none — the hard gate is a guard on Pass 3 §2.2 row 2 (`send` requires `news_gate_clear ∨ leg ∈ {STOP-tighten, CLOSE, CANCEL}`); the queue is the OMS holding `INTENT_PERSISTED` orders. Release threshold `gate_ratio ≤ 1.5` deliberately tighter than the generic 3.0: post-news tails are where "gate passed" still means 2× cost (Day Trader's forced change, §6-3).

### §1.2 The rollover minute (17:00 America/New_York ± minutes)

**(R)** Around rollover, retail MT5 brokers: widen spreads 3–8× for 2–10 min (literature-informed); charge swap on every open position; many reject modifies and even closes with `OFF_QUOTES`/`TRADE_DISABLED` for 1–3 min; some briefly stop quoting entirely; `stops_level` often widens temporarily. The minute is *scheduled chaos* — it happens every trading day.

**(D)** Nothing in docs 02/03 or Pass 3 mentions rollover. The spread gate would block IMMEDIATE entries incidentally; resting orders, reprices, trailing modifies, and the M-family's session logic run blind through it. H1 children evaluating on the 17:00 NY bar close (which is 00:00 broker time — a *daily* bar boundary on most MT5 servers) can emit signals straight into the worst 5 minutes of the day.

**(B)** (1) Reprice/trail modifies sent 16:59–17:03 NY are rejected in bursts → `ATTACH_RETRYING` noise and wasted modify budget; (2) IMMEDIATE signals generated at the daily bar close pay 3–8× spread or sit in retry loops; (3) swap accrual is invisible to the bot's P&L until position close (see §1.8); (4) broker daily-candle boundary ≠ bot trading-day boundary — already fixed by §1.0, but rollover is where the mismatch bites.

**(F)** A scheduled `session_id=rollover` micro-session, **16:55–17:10 America/New_York** (hypothesis width):
- **No new entry placements** (queued exactly as §1.1's gate; guard shared).
- **No reprices / trail modifies**; deferred modifies coalesce — when the window ends, only the *latest* intended value per order is sent (never a burst of stale intermediate levels).
- **Exits allowed** but flagged: a market close during rollover is charged rollover-session costs in telemetry (§5) so the learning loop sees what discretionary "get me out at 5pm" costs; time-stops that mature inside the window fire at window-end + spread-normalization (same 3-sample rule as §1.1), max deferral 15 min (hypothesis), and the deferral is event-logged (`cause=ROLLOVER_DEFER`).
- **Session children:** M-family `pre_filter()` receives `session_id=rollover` and declines (they already require their named sessions; making rollover a first-class session makes the exclusion structural rather than accidental).
- Swap accounting: §1.8.

### §1.3 Sunday open & gap opens (F-011 at the execution layer)

**(R)** Quotes resume Sunday ~17:05 NY (fx) with: first ticks frequently off-market (stale Friday book, crossed/1-tick-book quotes); spreads 3–10× for the first 2–10 min (literature-informed); gaps through Friday's close — usually ticks, occasionally ATRs (index CFDs have opened 3–5×ATR through stops on macro shocks — literature-informed, per F-011). Friday's resting orders behave mechanically: a **stop** whose level is inside the gap fills at the *first available price* (the open, not the level); a **limit** inside the gap fills at the open too — but for limits that is price *improvement* (the only systematically favorable fill in retail execution); position SLs inside the gap fill at the open, realizing loss = gap size, not stop distance.

**(D)** 02§A5's weekend rule reduces/flattens CFDs (default now ON for exchange-gapped assets per F-011); Pass 3 §2.6 prices held-over-close risk at k×. But nothing governs *pending entry orders held over the weekend*, and nothing stops the bot trading the first unrepresentative minutes.

**(B)** (1) A T1 buy-stop resting from Friday gaps to a fill 2×ATR above its level — realized risk-at-stop is a multiple of approved (F-022's worst case), and the fill price was never a price the thesis contemplated; (2) M-family limits from Friday would fill at gap opens exactly when the range they were fading no longer exists; (3) first-tick garbage can trip the spread gate *open* (a momentarily tight crossed quote passes `gate_ratio`), fire invalidation watches on phantom prices, or feed the feature engine an aberrant first bar.

**(F)**
- **Weekend pending-order policy (new, per intent type):** at Friday close-minus-15-min (calendar-svc event): meanrev LIMIT entries → **cancel** (their session thesis cannot survive a weekend; re-generated Monday if still valid); trend BREAKOUT stops → per-child `weekend_pending ∈ {cancel, keep_with_gap_guard}`, default **cancel** (board vote 8–2, Strategist dissent §6-7: "the Monday gap through the level *is* the breakout" — resolution: the child may re-emit at Monday open under normal gates; what it may not do is hold a stop order into a gap where fill price is unbounded).
- **Open quarantine:** for 5 min after any session open following a close (Sunday fx, daily exchange opens) (hypothesis; per-instrument, tuned by measured spread-decay curves — same measurement M4 is gated on, Pass 2 §3.4): no entry placements; ticks feed features but are marked `open_window=true`; the spread gate uses the *previous session's* norm (an open-window norm would learn the blowout as normal).
- **Gap-fill accounting:** any fill where `|fill − level| > 5 × spread_norm_ticks` (hypothesis) is tagged `gap_fill=true` in telemetry (§5); position opens route through Pass 3 §2.3 row 1 (realized-risk recompute) and row 5 (RISK_TRIM at >1.25× approved) — the mechanism exists; this pass supplies the tag so the simulator's gap model (§4.7) can be calibrated against reality.
- **Stops through gaps:** nothing to fix at the broker (that is physics); the fix is honesty — the simulator fills gapped SLs at the open (§4.7), which is what makes the k× budgeting of F-011 *measured* instead of assumed, closing the loop Pass 3 left to us.

### §1.4 Requote storms / OFF_QUOTES bursts

**(R)** Under fast markets or thin books, brokers answer market/stop sends with `REQUOTE` (price moved beyond your deviation) or `OFF_QUOTES` (no price at all). These cluster: a storm is 30–120 s of near-total rejection (hypothesis duration; measured by the storm detector below). Instant-execution accounts requote; market-execution accounts instead slip (no requote, worse fill) — **which regime the account is in is discovered** (`SYMBOL_TRADE_EXEMODE`), and the two need different handling.

**(D)** Pass 3 §2.2 rows 4–5: requote → resend same client_key up to 3 attempts with refreshed price, else REJECTED. Correct per-order; blind per-storm — during a storm, every queued order burns its 3 attempts pointlessly, and urgent exits interleave with doomed entries.

**(B)** (1) Attempt exhaustion converts transient illiquidity into terminal `FAILED` signals; (2) no backpressure: five children can each burn 3 attempts in the same 30 s; (3) exits compete with entries for the same trade channel during exactly the seconds exits matter.

**(F)** **Storm detector + degraded mode** (execution-intelligence state, per instrument):
- Enter `STORM` when ≥ 5 requote/OFF_QUOTES rejects across ≤ 3 distinct orders within 60 s (hypothesis).
- In `STORM`: all *entry* sends held (queued, as §1.1); exit/close sends get widened deviation (2× normal cap, §2) and up to 5 attempts; stop-attach retries continue (safety) with backoff per Pass 3 §2.3 row 3.
- Exit `STORM` after 60 s with zero rejects (hypothesis).
- Every storm emits `exec.storm{instrument, start, end, rejects:int}` (§5) — storms/week per instrument is a broker-quality metric feeding the §2 matrix (a broker whose storms cluster at your entry times is telling you your mechanism is wrong) and G2/G3 review (F-030's execution-telemetry sanity check).
State-machine delta: none new — `STORM` is a guard on OMS row 2, same hold mechanism as the news gate.

### §1.5 Dynamic `stops_level` / spec changes mid-position (resolves F-007)

**(R)** `SYMBOL_TRADE_STOPS_LEVEL` and `SYMBOL_TRADE_FREEZE_LEVEL` are dynamic on many retail brokers: widened before news (10 → 50–100 ticks is real behavior), sometimes around rollover, occasionally permanently and silently. `tick_value`/`contract_size`/`volume_step` restatements also occur (contract respecifications, leverage-tier changes). A widened stops_level makes existing *modify* and *attach* calls fail; it does not touch already-accepted broker-side stops.

**(D)** 03§B1 raises `SPEC_CHANGED`; Pass 3 §1.2 `broker.spec_changed` pre-classifies severity `{INFO, REVALIDATE_ORDERS, RECOMPUTE_LEDGER, BREAKER}` and §2.2 row 19 re-enters validation for working orders — the skeleton exists; Pass 1 assigned the analyzer's behavior spec to this pass.

**(B)** Without per-field behavior: a stops_level jump before news leaves an M1 resting limit whose on-fill stop-attach will be rejected → stopless position at the worst moment (F-007's scenario); a tick_value restatement leaves the ledger wrong until "someone" recomputes.

**(F)** **Spec-diff impact analyzer** — per-field classification and mandated actions:

| Field changed | Severity | Mandated action (deadline) |
|---|---|---|
| `stops_level` ↑ | REVALIDATE_ORDERS | within 5 s: for every working entry order, recompute whether its risk-block stop is legally attachable at current price. If not: per child `stops_level_policy ∈ {widen_and_trim, cancel}` — default **cancel the entry order** (meanrev: a stop that must sit further than the thesis allows is a different trade), trend default **widen_and_trim**: plan the on-fill stop at min legal distance + partial-size so risk-at-legal-stop ≤ approved (the Pass 3 §2.3 row 3 rule, applied *pre-fill*). Open positions: existing broker stops are untouched by the broker; verify each via reconcile snapshot; any `MISSING` stop re-attach uses the new legal distance + trim. **CRITICAL alert if any open position affected** (Pass-1 requirement). |
| `stops_level` ↓ | INFO | log; pending `widen_and_trim` plans may be relaxed at next natural modify (never a burst). |
| `freeze_level` ↑ | REVALIDATE_ORDERS | refresh §3.4 freeze guard parameters; no order action needed. |
| `tick_value`, `tick_size`, `contract_size` | RECOMPUTE_LEDGER | immediately: rebuild the exposure ledger from the projection with new specs (Pass 3 §3.3's "rebuild, never patch" rule reused); re-run limit stack; any limit now breached → `ALERT_ONLY` (positions are facts) + new-entry block on that instrument until back inside. |
| `volume_min/step/max` | REVALIDATE_ORDERS | pending partial-close/trim plans re-quantized; a planned trim below new `volume_min` escalates to full close of the excess or WARN hold (per child). |
| `trade_allowed → false`, `TRADE_DISABLED` mode | BREAKER | treat as instrument-scoped data-integrity breaker: no new entries; exits attempted anyway (they may be the only thing allowed — brokers commonly permit close-only). |
| `swap_long/short`, `swap_rollover3days` | INFO→RECOMPUTE | refresh carry math (TC-1/T3 filters, §1.8); a sign flip on a held carry-filtered position → WARN to owning child (`invalidation()` gets a chance to act). |
| filling modes, expiration modes | REVALIDATE_ORDERS | §3.1 expiry strategy re-selected; queued orders re-planned. |

Trigger paths: scheduled 24 h discovery; on any `STOPS_LEVEL`/`FREEZE`/`INVALID_VOLUME` reject (OMS row 6 already triggers re-discovery — confirmed); **and a 60 s lightweight poll of `stops_level`/`freeze_level`/spread for instruments with working orders or open positions** (hypothesis cadence; it is one `symbol_info` call — cheap insurance exactly where F-007 hurts).

### §1.6 Slippage asymmetry: stops vs limits vs market (quantified model; F-012 claim → mechanism)

**(R)** The asymmetry, stated as mechanics: **stop orders** trigger when the market trades at the level and fill at the *next available* price — slippage is one-sided against you, small in quiet sessions, heavy-tailed in fast ones. **Limit orders** fill at the level or not at all (MT5 retail: no partial price improvement on fx limits worth modeling) — they never slip, but they fill *conditionally on the market trading through you*, so the fill population is adversely selected: the post-fill drift of filled limits is negative relative to all touches. **Market orders** pay the spread plus a small execution drift; on market-execution accounts add slip, on instant-execution accounts add requote risk instead.

**(D)** After Pass 1 (F-012 RESOLVED-HERE for the claim), the docs say the right words; no numbers or model existed. This pass supplies the model (used by §2 thresholds and §4 simulator):

| Mechanism | Cost decomposition (ticks) | Pre-live defaults (all **hypothesis** unless noted) |
|---|---|---|
| MARKET | `spread(session)/1 + slip_mkt` | `slip_mkt ~ 0.9·N(+0.5, 1.0²) + 0.1·Exp(mean 4)` truncated ≥ −1 (small favorable slip possible, rare); ×3 tail weight in `vol_state=extreme` or `news_state≠clear` |
| STOP (entry or SL) | `slip_stop` one-sided | `slip_stop ~ 0.85·N(+1.5, 1.5²)⁺ + 0.15·Exp(mean 6)`; in news/rollover windows: tail component weight → 0.5, mean → 15 (literature-informed order of magnitude for retail news stops); gap opens: deterministic fill at open (§4.7) |
| LIMIT | `0` slippage; `+AS` adverse selection | fill requires trade-through ≥ 1 tick (F-012, binding); `AS = 0.5 × spread_avoidance_credit` pre-live (F-012 default), replaced by measured post-fill drift (§5's `exec.post_fill_drift`) at G2 — M1's G2 exit criterion (Pass 2 §3.1g) consumes exactly this record |

**(B)** Without this: the §2 matrix has no numbers to compare mechanisms with, and the simulator inherits touch-fill optimism. Both closed below.

**(F)** Adopted as the canonical execution-cost decomposition. One addition with teeth: **slippage is recorded signed, per fill, in ticks, against the *requested* reference** (stop level for stops, decision-time quote for market) — never against "the price we got last heartbeat". Telemetry schema §5 enforces the reference-price field so the asymmetry is measurable per cell, not anecdotal.

### §1.7 Netting vs hedging at execution time (F-002 — behavior designed for BOTH; default remains OPEN)

**(R)** **Hedging account:** each fill creates an independent position ticket with its own SL/TP; opposing positions coexist; partial close keeps the ticket. **Netting account:** one aggregate position per symbol with ONE SL/TP slot; any opposing order *is* a partial/total close of the aggregate; same-direction orders merge (weighted-average entry); "your" position identity does not exist at the broker — only deals do.

**(D)** Pass 1 F-002: v1 gates on account type; netting runs degraded (one child position per instrument); full synthetic-tranche ledger deferred **to this pass as a design item**. Pass 3 §2.6 limit #2 already assumes the degraded rule.

**(F) Execution-layer behavior, both account types (this is the design; the *default posture* stays OPEN-FOR-HUMAN):**

**Hedging mode (full model):**
- Position identity = broker ticket; `client_key ↔ ticket` map (Pass 3 §3.1) is the attribution spine. Per-child tranches are real broker positions with real per-position stops — 02§A5 holds natively.
- Edge cases owned: some brokers' partial closes emit a close-deal against the ticket with volume reduced (ticket stable) — reconciler treats volume-only drift on a matched ticket as `FIELD_DRIFT(volume)` and re-derives remaining risk; `CLOSE_BY` (offsetting two tickets) is **never used** by the bot (it destroys per-child attribution for a spread rebate we don't need).

**Netting mode (degraded, honest):**
- **Constraint enforced upstream:** at most ONE bot position per instrument, from one child (risk manager blocks both opposing *and* same-direction stacking — same-direction merge would destroy attribution; both emit `POSITION_CONFLICT` per F-019's Pass-3 resolution).
- Position identity = symbol; the projection keeps the virtual book (child, signal, entry, stop) and the broker's aggregate is verified against it every reconcile.
- The single SL/TP slot carries the owning child's stop — legal because there is only one owner by construction.
- **The reduce-only guard (new, the netting-specific hazard):** on netting, a close order for a position that no longer exists (stopped out milliseconds ago) **opens a reverse position**. Rule: every CLOSE/partial-close send on netting requires a position read ≤ 1 s old confirming direction and `volume ≥ close_volume`; on any mismatch → abort send, force reconcile, re-plan. OMS delta: new guard on §2.2 row 2 for `leg=C` under netting. The Algo-Bot Dev calls this the single most common real-money netting bug in retail bots; it is now unrepresentable.
- External manual trades on the same symbol (operator using the terminal) merge into the aggregate and desynchronize the virtual book → reconcile detects net-volume drift → position `QUARANTINED` (Pass 3 §2.3), exits-only, human attribution. Documented operator rule: don't hand-trade bot symbols on a netting account.

**Synthetic-tranche ledger (Option C) — designed enough to reject for v1:** tranches as projection rows over one broker aggregate; broker SL slot set to the *worst-case* tranche stop; all better stops synthetic (bot-watched). Rejected for v1 on the Networking seat's Pass-1 argument, now quantified: synthetic stops die with the bot/link, and the window of death is precisely the window of storms (§1.4) and disconnects (§1.11) — the failure modes correlate. Revisit only with a hosted watchdog (out of scope).

**Decision matrix (F-002 stays OPEN-FOR-HUMAN):**

| Criterion | A: require hedging account | B: netting degraded mode | C: synthetic tranches |
|---|---|---|---|
| 02§A5 stop integrity | native | native (single owner) | violated on link loss |
| Child attribution | full | full (by restriction) | full until crash |
| Concurrent children per instrument | yes | **no** (the cost) | yes |
| Complexity / new failure modes | none | reduce-only guard | high, correlated failures |
| Operator reach (some jurisdictions/brokers are netting-only) | excludes them | includes them | includes them |
| **Board recommendation** | **preferred posture where the operator has the choice** | **the netting behavior, and safe** | rejected v1 (10–0) |

Recommended default for the human decision: A-with-B-fallback (discovery detects; B engages automatically on netting with a one-time GUI acknowledgment of the one-child-per-instrument restriction). The board does **not** decide this; it ships both behaviors.

### §1.8 Triple-swap day accounting at the execution level

**(R)** Swap is charged per open position at rollover (17:00 NY); fx/metals charge 3× on **Wednesday** (T+2 settlement over the weekend); many index/commodity CFDs charge 3× on **Friday**; crypto CFDs often charge daily including weekends. The 3× day is per-symbol broker data: `SYMBOL_SWAP_ROLLOVER3DAYS` — **discovered, never assumed**. Swap appears on the broker's position record (accumulating field) and in deal history at close.

**(D)** 03§B6 checkbox ("swap-aware"); Pass 3 `position.closed` carries `swap_ccy` at close. Nobody records accrual during the hold, so a 3-week TC-2 position's P&L projection, the F-024 anomaly breaker's mark-to-market input, and TC-1/T3's carry filters all run on price-only P&L until close — and F-023's staleness applies to swap rates too.

**(F)** Ownership assigned: **the reconciler records swap; the position projection carries it.**
- New event `position.swap_accrued {position_id, ts, nights:int, triple:bool, swap_ccy:float, source:{broker_position_field}}` — emitted by the first PERIODIC reconcile after each rollover for every open position, from the delta of the broker position's swap field (broker truth, not our own rate math — rates are for *forecasts*, accruals are *facts*). Extends Pass 3 §1.2 position.\* family; contradicts nothing.
- Mark-to-market P&L everywhere (breakers, GUI, cone monitoring) = price P&L + accrued swap. `position.closed.swap_ccy` must equal the accrual sum ± broker rounding; mismatch > 2× rounding → `recon.diff(FIELD_DRIFT)` WARN (the Auditor's reconciliation-path demand, satisfied).
- Forecast side (sizing/filters): `E[swap_ticks_per_night]` from discovered rates, refreshed at signal time per F-023 (extended to swap fields — Pass 2 §5.2 already required this for TC-1); triple-day awareness in `nights_held` projections (a Wednesday-held fx position ≥ Wed counts +2 extra nights).
- Weekend-hold decisioning (T1/TC-2 Friday evaluations) uses the *discovered* 3× day — an index CFD with Friday-3× charges the weekend premium the night you decide to hold it; the cost shows up in the §4 simulator's swap module identically (Pass 3 §5.4 `CostModel.swap schedule incl. triple-swap day` — this pass supplies its semantics).

### §1.9 `freeze_level` vs trailing-stop modifies

**(R)** When price is within `freeze_level` of an order's trigger (pending entry) or a position's SL/TP, the broker rejects modification/cancellation of that order/level (`FREEZE`/`MODIFY_DENIED`). Freeze is exactly where trailing logic wants to act: a trail tightens the stop toward a price that is approaching it.

**(D)** Pass 3 §2.2 row 17 gates modifies on "rate limiter clear" and row 18 handles rejects; no freeze-awareness — the bot would send modifies destined to fail whenever the market runs at the stop.

**(B)** Burst of `FREEZE` rejects during fast approaches (again: the worst moment), wasted modify budget, `MODIFY_PENDING` churn; and a cancel of a pending entry racing its own trigger inside the freeze band is *rejected*, then fills — an F-010 special case with a known precursor we can see coming.

**(F)** **Pre-send freeze guard** (execution intelligence): a modify/cancel is sent only if `distance(current_price, affected_level) > freeze_level + max(2, spread_now_ticks)` (buffer hypothesis). Inside the band:
- Trailing modifies: **defer, don't drop** — the intended stop is recorded on the position (`intended_stop` projection field); the modify fires when the guard clears or the old stop executes (which is fine: the old stop is *further* than the trail wanted, so the realized loss ≤ thesis loss + trail lag; the lag cost is telemetered as `trail_defer_ticks`, §5).
- Cancels of pending entries inside the freeze band: attempt anyway once (broker may allow), but the OMS pre-arms the F-010 arm — the cancel is *expected* to lose the race; invalidation logic treats "cancel sent inside freeze band" as `probably_filling` and pre-stages the adoption path (no state change, just no surprise).
- `stops_level` interaction: the legal-distance check (§1.5) and the freeze guard are evaluated together in one pre-send validation (`can_modify(order, new_values) → {OK, DEFER_FREEZE, ILLEGAL_STOPS_LEVEL, RATE_LIMITED}`), which is the single choke point all modify paths (trail, BE move, reprice, spec-revalidation) must pass. State-machine delta: `DEFER_FREEZE` is a self-loop on `ACKED_WORKING`/`OPEN` with a timer, not a new state.

### §1.10 Partial fills: remainder policy per urgency class

**(R)** MT5 partial fills occur on `IOC`/`RETURN` filling modes when top-of-book volume is thin — rare on fx majors at retail size (hypothesis: < 0.5% of orders ≤ 1 lot), material on index CFDs, exotics, and crypto CFDs at size, and during storms. The remainder either rests (RETURN) or cancels (IOC) — *broker-decided by filling mode*, which discovery records per symbol.

**(D)** 03§A3.5: passive → leave working; urgent → convert to market if spread gate passes else cancel. Pass 3 §2.1 rows 15/17/21 handle partial-during-confirmation (F-001). Gaps: `normal` urgency undefined; interaction with `volume_min` undefined; filling-mode selection undefined.

**(F)** Complete policy table (OMS consumes; filling mode chosen at send):

| Urgency | Filling mode preference (from discovered allowed set) | Remainder policy |
|---|---|---|
| passive (M1/MC-1 limits) | RETURN > IOC | leave working under the same signal contract (expiry/invalidation unchanged); if remainder < broker `volume_min` → cancel remainder, keep filled part (a sub-min remainder can never fill) |
| normal (default; T1/T2/M2/M3 entries) | RETURN > IOC | leave working for `min(2 × median_fill_latency, 30 s)` (hypothesis), then cancel remainder — a normal-urgency entry that didn't complete in seconds is telling you about liquidity; trade the size you got (position already opened + stop attached per F-001 first-fill rule) |
| urgent (exits, veto-closes, T4 twin-flatten) | IOC > FOK; market conversion | remainder immediately re-sent as market with widened deviation (2× cap); repeat ≤ 3; if still unfilled → CRITICAL (an unfillable *exit* is an incident, not a policy branch) |
| FOK-only symbols | FOK | no partials possible; a FOK reject at size → halve size once and retry (hypothesis; respects `volume_step`), else FAILED — never loop-halve to dust |

Risk accounting: every partial routes through position row 1 (realized-risk recompute on *filled* lots); ledger reserves release pro-rata on remainder cancellation. This completes F-001's execution arm: budget reserved at placement (Pass 3 row 5), debited at each partial, released on remainder death.

### §1.11 Disconnect mid-order-send (ties to Pass 3 §3.2)

**(R)** The TCP link (or the Windows bridge hop, if F-016 resolves to topology (b)) can die after the request left and before the response arrived. The broker may have: never received it; received and rejected; received and executed. All three are indistinguishable from the client at timeout. Additionally MT5 can be *connected but trade-server-degraded* (quotes flow, trades time out).

**(D)** Pass 3 owns this correctly: OMS rows 8/11 (`SENT_UNKNOWN` → probe → `LOST_LINK_PENDING_RECON`), §3.2 probe/dedup, §3.3 POST_RECONNECT reconcile, "no retry with a new key, ever". This pass **adopts it unchanged** and adds the execution-layer consequences the systems pass left open:

**(F)**
1. **Stops ride the entry request.** The single largest residual risk in the Pass-3 design is a market/pending entry that *fills during the disconnect* and sits stopless until reconnect + reconcile + attach. Fix (rule change vs the implicit attach-on-fill flow): **every entry order carries `sl` (and `tp` where the plan has one) in the initial request** — MT5 supports SL/TP on market and pending orders natively. Attach-on-fill (Pass 3 §2.3 rows 2–4) becomes the *fallback* for the cases where send-time attachment is illegal (stops_level at send, §1.5) — not the default path. Consequence: a fill during a dead link is born stopped, server-side. 02§A5 is now enforced by the broker even when we are gone. The board rates this the pass's most consequential single change (§6-1).
2. **Probe matcher tolerance** (Pass 3 §3.2 `|price − intent.price| ≤ tolerance`): tolerance = `max(10, 3 × spread_norm_ticks) + slip_p99(mechanism, session)` from the execution profile (hypothesis composition) — a news-window fill can be far from intent price and must still match rather than fall to quarantine.
3. **Trade-channel-degraded detection:** the quote stream being LIVE must not mask a dead trade channel; the connection machine (Pass 3 §2.5) tracks them separately — confirmed — and this pass adds the probe: any order send timing out while quotes are fresh increments `trade_channel_suspect`; 2 consecutive → treat trade channel DOWN (storms §1.4 excepted: rejects are answers, not timeouts).
4. **Entry queue flush on reconnect:** orders held in the §1.1/§1.2/§1.4 queues re-validate (`invalidation()`, spread gate, valid_until) before release — a queue must never replay stale intents into a market that moved during the outage.

---

## §2 Intent → mechanism decision matrix v2

Replaces 03§A1. All thresholds are **(hypothesis)** until the named telemetry accumulates its minimum sample; the learning loop may adjust *only* the rows marked adaptive, per the locked "execution/costs/throttles only" constraint.

| Intent × condition | Mechanism | Concrete rule & default thresholds | Telemetry that tunes it (§5 fields) | Min sample before any adaptive flip (F-029) |
|---|---|---|---|---|
| BREAKOUT_AT, level ≥ `stops_level` from market | broker-side STOP, **SL in request** (§1.11-1) | default | `slippage_ticks` vs reference=level, per cell | — (default) |
| BREAKOUT_AT, measured stop slippage bad | synthetic stop (bot watches, fires MARKET) | flip when cell median `slip_stop` > max(4 ticks, 0.25 × child edge_ticks) **and** synthetic simulated cost (latency-adjusted, from §4 latency model) beats it by ≥ 20% (hysteresis; flip back requires the reverse by the same margin) | `slip_stop` distribution per (broker, instrument, session); `latency_ms`; synthetic shadow-cost computed per fill | **n ≥ 100 stop fills in the cell** (hypothesis); evaluated on fixed weekly blocks, flip = event `exec.mechanism_switched` with `cost_model_version` pinned |
| BREAKOUT_AT, level inside `stops_level` | hold-and-place | poll at 2 s; place the moment distance legal; if urgency=urgent → synthetic immediately | `stops_level_at_send`, hold durations | — (rule, not adaptive) |
| LIMIT_AT (passive) | broker-side LIMIT at level | default; fills only on trade-through (that is the broker's physics, and §4's model) | `exec.post_fill_drift` (adverse selection), fill-rate per touch | — |
| LIMIT_AT, near-miss pattern | LIMIT at level ± offset | offset +1…2 ticks toward market when cell touch-no-fill rate > 60% over trailing window **and** measured AS cost < spread saved (else the offset is buying adversely-selected fills) | `touches_without_fill` (from §5 order record + tick ring), `post_fill_drift` | **n ≥ 50 touched-level episodes** per cell (hypothesis) |
| IMMEDIATE (normal urgency) | MARKET, deviation cap = `clamp(2 × spread_now_ticks, 3, 20)` ticks (hypothesis) | spread gate first (03§A2, tick-corrected per F-003): `gate_ratio > 3.0 → HOLD` retry at 5 s cadence until valid_until; `spread_now_ticks > 0.25 × child edge_ticks → REJECT_COST` | `spread_at_send_ticks`, `requotes`, realized `slip_mkt` | deviation cap adaptive after **n ≥ 200 market fills** per cell: set to `P90(|slip_mkt|) + 2` (hypothesis) |
| IMMEDIATE (urgent: exits, flattens) | MARKET, deviation 2× normal cap, attempts 5 | never gated by spread/news/rollover/storm holds (§1.1/§1.2/§1.4 exits-always rule) | same + `attempts` | not adaptive (safety path) |
| Any entry, `news_state ≠ clear` ∨ `session_id = rollover` ∨ STORM | queued | §1.1/§1.2/§1.4 release rules | `queue_wait_ms`, expiry-in-queue count | — |
| Stop-loss placement/move | broker-side always; synthetic **never** for position SLs | 02§A5 is not negotiable; synthetic exists only for *entry* stops (above) and the §1.5 `OPEN_STOP_UNVERIFIED` bridge with `close_on_touch` | `position.stop_state` events | — |

**Learning-loop constraints (binding, restated):** adaptive flips touch mechanism choice, offsets, deviation caps, and queue thresholds only; per-cell evaluation on fixed weekly blocks (no per-fill peeking — F-013 discipline applied to execution); every flip is an event carrying the evidence window; priors act as floors (a cell may not be modeled cheaper than `0.7 × prior` regardless of sample — hypothesis floor, F-029); a mechanism flip **resets the cell's sample counter** (the flip changes the distribution being sampled — F-029's circularity point, closed by construction).

---

## §3 Pending-order lifecycle v2 + OCO double-fill machine

### §3.1 Expiry: broker-honored vs bot-side

Discovery records the symbol's supported expiration modes (GTC/DAY/SPECIFIED/SPECIFIED_DAY). Policy:
- **Bot-side expiry is the authority**: the STA's expiry sweeper (Pass 3 §2.1 rows 3/13/27) cancels at `valid_until` — event-time-evaluated, race-safe.
- **Broker-side GTD is the belt-and-braces**, set to `valid_until + 120 s` (hypothesis margin) where SPECIFIED is supported — it exists to kill the order when *we* are dead (crash/disconnect over expiry). The margin ensures the bot's cancel normally wins, so the log shows intent, not broker timeout; a broker-expired order discovered by reconcile resolves as `GHOST_CLOSED`-analog for orders (deal history explains it), INFO.
- Where SPECIFIED is unsupported: GTC + bot sweeper + the §1.3 weekend-cancel policy (a GTC order must never outlive Friday for weekend-cancel children).

### §3.2 Invalidation watch cadence

- **Bar-driven (primary):** owning child's `invalidation()` runs on every `feature.changed` batch of its timeframe — unchanged from 03§A3.2.
- **Timer-driven (new):** a 10 s sweep (hypothesis) evaluates only the *cheap* invalidation triggers that must not wait for a bar close: session end approaching (M-family), news gate arming (§1.1 suspend policy), regime `published` transitions (event-driven, effectively immediate), and expiry-adjacent checks. Rationale: an M15 child's bar cadence is too coarse to catch "London opens in 90 s and my Asian limit is still resting".
- Cancel-on-invalidation always rides the F-010-armed path (Pass 3 §2.1 row 20 / §2.2 row 16) — cancels are requests; `ALREADY_FILLED` adopts.

### §3.3 Min-reprice-distance formula

A resting reversion limit trails its band (03§A3.3). Reprice fires only when:

```
|new_level − current_level| ≥ max( 3 ticks,
                                   2 × spread_now_ticks,
                                   0.10 × ATR(child_tf)_ticks )      # all hypothesis
AND freeze guard clear (§1.9)  AND rate budget available (§3.4)
AND new_level respects stops_level vs current price (§1.5)
```

The three terms encode: broker-noise floor, spread-noise floor, thesis-scale floor. Telemetry `reprice_skipped{reason}` counts suppressed reprices; if a child's fills systematically occur at stale levels (fill price vs *intended* band > 1 × ATR-term), the 0.10 coefficient is a tunable (weekly block, n ≥ 50 fills — F-029 rules apply).

### §3.4 Modify rate-limit budget per broker profile

Token buckets, defaults (hypothesis, tuned down on observed `TOO_MANY_REQUESTS`-class rejects, tuned up never above discovery-tier defaults):

| Bucket | Default | Notes |
|---|---|---|
| Account-wide modifies | 30/min, burst 10 | covers modify+cancel+reprice |
| Per-order modifies | 6/min | a single trailing order may not starve the account |
| Priority classes | `safety` (stop attach/tighten, twin-cancel) > `management` (BE, trail) > `reprice` | reprices are shed first under contention; safety class may *borrow* from the full account bucket and is never shed |

A broker observed rejecting at < 50% of the default budget for 2 consecutive days → budget auto-halved + WARN (broker profile updated, event-logged).

### §3.5 OCO straddle: full state machine with the double-fill hazard (resolves the F-021 grace-window mechanics; consumes Pass 3 F-010 arms)

Bot-side OCO (brokers lack native OCO). Legs A/B are two BREAKOUT stops sharing `signal_id` (client_keys `…-E-n`, `…-EB-n`). New machine, owned by the execution-intelligence OCO manager, driving the OMS for each leg:

**States.** `PLACING (A sent, B pending), ARMED (both ACKED_WORKING), ARM_FAILED, LEG_FILLED_CANCELLING_TWIN, ACTIVE_SINGLE, DOUBLE_FILL_FLATTENING, RESOLVED_DOUBLE, CANCELLED, EXPIRED`.

| # | From | Event | Guard | To | Actions |
|---|---|---|---|---|---|
| 1 | — | arm(straddle) | news gate clear (§1.1: T4 blackout ±60 min per Pass 2 + execution hard gate) | PLACING | place A then B sequentially, each with SL in request (§1.11-1) |
| 2 | PLACING | both acked ≤ 10 s | — | ARMED | invalidation watch + expiry (3 h after London open, per T4 spec) armed on both |
| 3 | PLACING | either leg rejected ∣ 10 s deadline | — | ARM_FAILED | cancel the placed leg; signal FAILED. **A straddle is atomic — half a straddle is a directional bet nobody approved** (board unanimous) |
| 4 | ARMED | fill(A or B, PARTIAL∣FULL) | — | LEG_FILLED_CANCELLING_TWIN | position opens (born stopped); **twin cancel sent within the same event-loop turn, `safety` priority (§3.4)**; start `t_gap` clock |
| 5 | LEG_FILLED_CANCELLING_TWIN | twin cancel_result(CANCELLED) | — | ACTIVE_SINGLE | normal position management; emit `exec.oco_resolved{single, t_cancel_ms}` |
| 6 | LEG_FILLED_CANCELLING_TWIN | twin fill (before cancel confirm) | — | DOUBLE_FILL_FLATTENING | **flatten the twin's position immediately at market, urgent class** (no human confirm — pre-authorized by the straddle contract); severity: `t_gap ≤ T_grace` → WARN `double_fill_whipsaw`; `t_gap > T_grace` → CRITICAL `cancel_pipeline_slow` |
| 7 | LEG_FILLED_CANCELLING_TWIN | twin cancel_result(ALREADY_FILLED) | — | DOUBLE_FILL_FLATTENING | same as row 6 (this is the F-010 arm surfacing inside OCO — one code path) |
| 8 | DOUBLE_FILL_FLATTENING | flatten fill | — | RESOLVED_DOUBLE | emit `exec.oco_double_fill{t_gap_ms, flatten_cost_ticks (=c_df sample), news_state}`; leg-1 position continues under management |
| 9 | ARMED | invalidation ∣ expiry ∣ weekend policy | — | CANCELLED/EXPIRED | cancel both (each cancel F-010-armed: a fill racing the cancel re-enters at row 4) |
| 10 | any | disconnect | — | (frozen) | legs follow OMS `SENT_UNKNOWN`/`LOST_LINK` rules; POST_RECONNECT reconcile replays fills into rows 4–8 by deal timestamps — **ordering by broker time, not arrival time** (a double fill discovered at reconnect is still rows 6/8) |

**The grace window `T_grace` — measured parameter (F-021, Pass-2 mandate honored):**
- **Role:** classification boundary between "whipsaw double-fill" (market event; expected hazard, priced in Stage-R via `f_df·c_df ≤ 0.30·edge` kill term) and "our cancel pipeline is too slow" (engineering defect). It does **not** gate the flatten — the flatten is unconditional and immediate in both cases.
- **Starting hypothesis:** `T_grace = 5 s`.
- **Measurement plan:** (a) *backtest*: from M1-path simulation of every T4 straddle-day in the research lake, the distribution of `t_gap = |t_touch(B) − t_fill(A)|` for days both levels were touched within 10 min — Stage-R artifact `oco_gap_distribution.parquet` (feeds `f_df` and the §4.8 calibration); (b) *live/demo*: `t_cancel_ms` (fill→cancel-confirm round trip) from every row-5 resolution. **Recalibration rule:** after n ≥ 50 live OCO resolutions (hypothesis), `T_grace := clamp(P99(t_cancel_ms) + 1 s, 2 s, 15 s)`; recomputed monthly; changes event-logged. If `P99(t_cancel_ms)` itself exceeds 5 s, the finding is not a wider grace window — it is a broker/link quality CRITICAL (the Auditor's forced reframing, §6-5).

---

## §4 The execution simulator spec (resolves F-012; the fill model behind Pass 3 §5.2's `FillModel` seam)

### §4.0 Scope and stance

`RealisticFillModel` implements the (informative) Pass 3 §5.2 protocol: `on_order(order, market_state)` and `on_bar(working_orders, bar)`, emitting ack/reject/requote/fill/partial `SimEvent`s. It supersedes `ConservativeFillModel` for G1 evidence runs; the conservative model remains as the floor sanity run (both are run for gate reports; a child whose pass depends on the *difference* is flagged — Auditor rule §6-6). Every parameter lives in the versioned `CostModel`/`FillModel` objects pinned in the run manifest (Pass 3 §5.4/§5.5). **All defaults below are (hypothesis) or (literature-informed) as marked; the calibration procedure (§4.8) replaces them with (measured) per-cell values, priors-as-floors.**

Market state consumed per decision: current M1 bar (or tick where tick data exists), `session_id`, `vol_state`, `news_state`, `rollover/open_window/gap flags` (all from the same calendar_svc + feature nodes as live — zero-drift requirement holds for the *inputs* too).

### §4.1 Spread model

```
spread_ticks(t) = S_base(instrument, session_id) × M_regime(t)
S_base  ~ LogNormal(μ, σ) fitted per (instrument, session) — pre-live seeded from
          published typical spreads (literature-informed): EURUSD {london 10, asia 15,
          ny_late 13, overlap 10} STD-tier ticks; index CFDs per-broker published minimums ×1.5
M_regime: clear=1; news: peak 8× at T0 decaying exp(−t/45 s) toward 1 over ~180 s
          (peak ~U[5,20] drawn per event — literature-informed range from F-021);
          rollover: 4× over 16:55–17:10 NY (hypothesis); open_window: 6× decaying
          over 5 min (hypothesis; replaced by measured per-minute decay curves — the
          M4-gating measurement, Pass 2 §3.4);  vol_state high/extreme: ×1.3/×2 (hypothesis)
```

Sampled per simulated decision point (not per bar) so gate logic (HOLD/retry loops) experiences realistic spread paths.

### §4.2 Latency model

`latency_ms ~ LogNormal(median 150 ms, P95 800 ms)` (hypothesis for the retail-VPS-plus-bridge path; re-fit from `latency_ms` telemetry). During `news_state≠clear` or STORM: median ×3 (hypothesis). Price movement across the latency gap is simulated by advancing along the intra-bar path (§4.7); market orders are priced at the *post-latency* quote — this is where "the price ran while your order flew" lives, and it is deliberately distinct from the slippage draw (which models venue behavior at execution instant).

### §4.3 Market orders

| Aspect | Model |
|---|---|
| Fill probability | 1 − P_reject(t) (§4.5); fills at post-latency quote side ± slip |
| Slippage | `slip_mkt` mixture per §1.6 table; deviation cap honored: if post-latency price beyond cap → requote event (instant-exec) or fill-at-cap-boundary… **no — never**: model matches discovered `SYMBOL_TRADE_EXEMODE`: instant → requote; market-exec → fill at the moved price (cap ignored by broker; recorded as slippage). Both behaviors exist in retail reality; the account's regime is discovered, and the simulator honors it |
| Urgent-class retries | replayed through the same model (widened deviation honored on instant-exec) |

### §4.4 Stop orders (entries and SLs)

- Trigger: bar/tick path touches trigger side (buy-stop: ask ≥ level — spread-adjusted using §4.1's concurrent spread sample; H/L of M1 bars are bid-side on MT5, so ask-side triggers add the sampled spread — a real and routinely-ignored bias, now modeled).
- Fill price = trigger level + one-sided `slip_stop` draw (§1.6), tail-weighted by `news_state`/`vol_state` at trigger time.
- Gap-open: if the session-open (or next-bar) price is beyond the level, fill at the open price exactly (§4.7) — no draw; gaps are deterministic cruelty.
- SL fills additionally emit `gap_fill` tags when `fill − level > 5 × spread_norm` (mirrors §1.3 live tagging → calibration comparability).

### §4.5 Requote / reject / storm model

- Baseline `P(requote∣send)` per (session, vol_state): clear/normal 1%; high vol 4%; extreme 12%; `news_state≠clear` 25% (all hypothesis; literature-informed only in ordering).
- **Storm process:** 2-state Markov chain per instrument (NORMAL ↔ STORM); `P(→STORM)` per decision ≈ calibrated so unconditional storm time ≈ 0.2% of session time, mean storm duration 45 s (hypothesis); in STORM, `P(reject) = 0.8`. The live storm detector (§1.4) produces the calibration series (`exec.storm` events: frequency, duration, clustering vs news).
- Rejects during simulated storms exercise the §1.4 degraded-mode logic — the *policy* runs in backtest, not just the price math (kernel parity, Pass 3 §5.1).
- `stops_level`/`freeze` rejects: the simulator carries the discovered spec profile and — crucially — a **news-coupled stops_level widening process** (widen ×5 during T−30 min…T+15 min with probability 0.5 per event — hypothesis) so the §1.5 analyzer paths and widen-and-trim policies execute under test.

### §4.6 Limit orders (the F-012 core)

- **Fill rule: trade-through ≥ 1 tick beyond the level on the relevant side** (bid through a sell-limit's level, ask through a buy-limit's). Touch-without-through = no fill, counted as `touch_no_fill` (calibrates the §2 near-miss row). Unrepresentable: touch-fills, "earning" spread.
- **Adverse selection:** implicit in the trade-through condition (the filled population is the through population), **plus** the explicit `AS` cost term in the CostModel for viability math (pre-live: 0.5 × spread-avoidance credit — F-012 default; replaced at G2 by measured `post_fill_drift`). The simulator does not double-charge: fills happen at the limit price; `AS` lives in the evaluation layer (cost waterfall), documented in `cost_waterfall.json` per Pass 3 §5.5.
- Partial fills: `P(partial∣fill) = f(lots / liquidity_proxy)` — 0 below 1.0 lots fx majors (hypothesis), ramping to 0.3 at 10× median retail clip on index CFDs (hypothesis); remainder behavior per §1.10 policies (policies execute in sim).
- Gap-open limits: fill at the open when it is through the level — price improvement, the one favorable case, modeled as such.

### §4.7 Intra-bar path & gap-open handling

- Resolution: M1 bars minimum for all Stage-R runs (Pass 2 lake); tick data where the lake has it.
- Within an M1 bar, order interactions use a fixed path heuristic: O → (nearer of H/L) → (farther) → C; when both a stop and a limit/TP are touchable within one bar, resolve **pessimistically (stop first)** — Pass 3 §5.2's choice, confirmed and inherited; the per-trade artifact records `path_ambiguous=true` so gate reports can quantify how much P&L rests on the pessimism (if > 10% of gross, the child needs tick-data validation — hypothesis threshold, Auditor rule).
- Session opens: the first simulated minutes apply `open_window` spread multipliers + the §1.3 quarantine policy (which the live side enforces — parity); Friday→Sunday gaps come from the data itself; all resting orders and SLs resolve against the open per §4.4/§4.6 before any intra-session logic runs.

### §4.8 Calibration procedure (live telemetry → parameters)

1. **Cells:** `(broker_id, instrument, mechanism, session_id, vol_state)` with hierarchical fallback (drop vol_state → drop session → mechanism-only) via shrinkage: `θ_cell = w·θ̂_cell + (1−w)·θ_parent`, `w = n/(n+n₀)`, `n₀ = 100` (hypothesis).
2. **Fitting:** weekly batch job over `exec.telemetry_sample` + `exec.post_fill_drift` + `exec.storm` + `exec.oco_double_fill`: robust quantile matching (median → location, P90 → scale) for slippage/latency; empirical frequencies for requote/storm/partial; spread distributions directly from the session-baseline Welford/ring nodes (same nodes live and sim — Pass 3 §4.3).
3. **Floors (F-029, binding):** no cell's modeled cost may fall below `0.7 × prior` (hypothesis floor) regardless of sample; below `n = 100` fills the prior is used outright. Mechanism switches (§2) reset the cell counter.
4. **Versioning:** every refresh bumps `cost_model_version`/`fill_model_version`; gate runs pin versions (Pass 3 §5.5); a child whose G1 pass inverts under the *previous* version is flagged (model-sensitivity check, Auditor).
5. **Validation of the simulator itself (the honest test):** monthly, replay the last month's live/demo orders through the simulator with same-time market states; compare simulated vs realized per-order cost. Acceptance: median absolute error ≤ 2 ticks and realized-cost P90 within [0.8, 1.3]× simulated P90 (hypothesis bands). Persistent optimistic bias (realized > simulated at P50 for 2 consecutive months) → CRITICAL on the research pipeline: **G1/G2 evidence produced under the optimistic model is suspect and gates re-run** (this is F-030's execution leg, made mechanical).

### §4.9 Known blind spots (stated, not waved at)

1. **No queue/book model:** fill priority within the broker's book, last-look, and internalization are invisible; limit fill timing inside the through-tick is approximated.
2. **B-book behavioral shifts:** a broker that profiles clients can change execution quality *in response to our profitability*; no model — only the monthly §4.8-5 drift check can see it, after the fact.
3. **Tail beyond data:** slippage tails are fit to observed fills; the next flash event is worse than the sample by construction. The k× gap-stress budgets (Pass 3 §2.6), not the simulator, are the defense; the simulator must not be mistaken for a tail model.
4. **Correlated microstructure at news T0:** latency, spread, storm probability, and slippage all spike *together* in ways the independent-draws structure underestimates; the news multipliers are calibrated marginally, not jointly (a joint model is v2 at the earliest, and only with measured data).
5. **M1 path ambiguity:** sub-minute sequencing is a heuristic; the pessimistic rule + `path_ambiguous` accounting bound but do not remove the error.
6. **Demo≠live:** demo telemetry (G2) measures our *logic* against a frictionless-ish venue; only G3 probation telemetry calibrates real cells (F-030 posture preserved: demo evidence never overwrites live-cell priors).

---

## §5 Execution telemetry schema

Extends Pass 3 §1.2 `exec.*` — no existing field is changed; `exec.telemetry_sample` is superseded by the richer `exec.order_record` (the old schema remains valid; new writers emit the new one — upcaster registered per Pass 3 §1.1 versioning).

**`exec.order_record` (one per order attempt reaching SENDING; the per-order execution fact):**

| Field | Type | Semantics |
|---|---|---|
| `client_key, signal_id, child_id, instrument, mechanism` | — | join keys; mechanism ∈ {MARKET, STOP, STOP_SYNTH, LIMIT, LIMIT_OFFSET, MODIFY, CANCEL, CLOSE} |
| `account_mode` | {hedging, netting} | F-002 analytics split |
| `session_id, vol_state, news_state, rollover_flag, open_window_flag, storm_flag, dst_mismatch_flag` | enums/bool | the §1 regime context, from calendar_svc + features at send time |
| `reference_price, requested_price, deviation_cap_ticks` | float/int | reference per §1.6 (level for stops/limits, decision-quote for market) |
| `spread_at_send_ticks, stops_level_at_send, freeze_level_at_send` | int | spec state at send (F-007 forensics) |
| `queue_wait_ms` | i64 | time held by §1.1/§1.2/§1.4 gates before send (0 if none) |
| `latency_ms, attempts, requotes, reject_codes:[RejectCode]` | — | transport outcome |
| `filled_price, filled_lots, remaining_lots, partial_count` | — | fill outcome (null if none) |
| `slippage_ticks` | int signed | `side_sign × (filled − reference)` in ticks — positive = against us, always |
| `gap_fill, path_note` | bool, str? | §1.3 tag; sim-side carries `path_ambiguous` here |
| `swap_projection_ticks_per_night, triple_day` | float, bool | carry context at entry (T3/TC-1/TC-2 audit) |
| `trail_defer_ticks` | int? | §1.9 freeze-deferral lag realized (modify records only) |

**Companion events (new):** `exec.post_fill_drift {client_key, drift_ticks_at: {1, 5, 20} bars}` — emitted by a bar-driven follower for every entry fill; the adverse-selection measurement (F-012, M1's G2 exit criterion). `exec.storm {instrument, start, end, rejects}` (§1.4). `exec.oco_resolved / exec.oco_double_fill` (§3.5). `exec.mechanism_switched {cell, from, to, evidence_window, cost_model_version}` (§2). `position.swap_accrued` (§1.8).

**Aggregation keys → execution profiles:** primary cell `(broker_id, instrument, mechanism, session_id, vol_state)`; secondary cuts `news_state`, `account_mode`, `child_id` (child-level execution quality feeds F-013's corroborating-signal requirement: a cone breach *plus* a cost-regime shift is the demotion pair). Profiles store per cell: n, slippage quantiles {P50, P90, P99}, requote rate, storm exposure, fill-rate per touch (limits), post-fill drift means, `t_cancel_ms` quantiles. Retention: order records forever (they are small and they are the learning loop); tick ring-buffer flushes around sends per Pass 3 §1.2 `market.tick` policy (unchanged).

---

## §6 Board debate log (objections that changed content)

1. **Algo-Bot Dev vs attach-on-fill (§1.11-1).** Objection: Pass 3's stop-attach flow (position rows 2–4) leaves a stopless window measured in seconds normally and *minutes* across disconnects; production scar tissue says that window eats an account eventually. Forced change: SL/TP ride the entry request; attach-on-fill demoted to fallback. The Architect verified no Pass-3 contradiction (rows 2–4 remain as the fallback path and `stop_verified` semantics are unchanged — the ack of an order carrying SL sets it). **Adopted unanimously; flagged as the pass's most consequential change.**
2. **Auditor vs a blanket rollover no-modify rule (§1.2).** Objection: "no modifies at rollover" as first drafted included stop-tightening — a safety regression masquerading as prudence. Forced change: safety-class modifies (tighten/BE) always allowed everywhere (news, rollover, storms); only loosening/reprices defer. The exits-always principle now has a *modify-class* refinement, adopted into §1.1/§1.2/§3.4.
3. **Day Trader vs the generic 3.0 spread-gate release (§1.1).** Objection: releasing queued news-window entries at `gate_ratio ≤ 3.0` pays 2–3× cost by construction; the gate exists to prevent exactly this. Forced change: post-news release requires `≤ 1.5` × 3 consecutive samples. The Strategist's counter (missed re-entries after news) was noted and priced: expiry-in-queue is telemetered, and if > 30% of queued signals expire unfilled the threshold is re-examined on evidence (hypothesis review trigger).
4. **Swing Trader vs weekend-keep for breakout stops (§1.3).** Objection to keep-by-default: a Friday stop into a Monday gap has unbounded fill distance — the one order type where "the market decides your entry price" composes with the week's largest gap. Strategist dissent (gap *is* the breakout) recorded; resolved 8–2 for default-cancel with per-child opt-in `keep_with_gap_guard`, and the child may re-emit Monday. The learning loop will measure what the cancelled cohort would have done (shadow accounting via signal journal) — evidence before relitigating.
5. **Auditor vs elastic grace windows (§3.5).** Objection: recalibrating `T_grace` upward from live `t_cancel_ms` P99 lets a degrading broker silently stretch the definition of "expected hazard". Forced change: cap at 15 s AND a P99 > 5 s finding escalates as broker-quality CRITICAL rather than reparameterization. The window measures the market; it must not absorb the broker.
6. **Quant vs single-model gate evidence (§4.0).** Objection: a child passing G1 under `RealisticFillModel` but failing under `ConservativeFillModel` is an execution-assumption bet, not an edge. Forced change: both models run for every gate report; divergent verdicts flag the child and the deciding parameters. (This also gives the §4.8-5 drift check a second anchor.)
7. **Strategist vs the execution hard gate scope (§1.1).** Objection: a T-120 s all-entries block on *every* currency leg over-blocks (e.g., EUR events blocking AUDJPY via no shared leg — mis-scoped matching). Resolution: currency-matched scoping as specced (base/quote/underlying match only), and the Strategist's real worry — cross-asset sympathy moves — is explicitly *not* gated (it would be a strategy-level concern; execution gates only same-currency events). No change beyond scoping clarity; recorded because the scope question will recur.
8. **Networking seat vs synthetic anything (§2, §1.5).** Standing objection renewed from F-002: every synthetic mechanism (synthetic entry stops, `close_on_touch` bridges) dies with the link. Resolution: synthetic entry stops remain (an entry that fails to fire loses opportunity, not money — asymmetry accepted 9–1); synthetic position SLs remain forbidden; `OPEN_STOP_UNVERIFIED` bridge policy defaults reaffirmed (meanrev `close_now`).
9. **Backend Architect on telemetry volume (§5).** Objection: per-order records forever + post-fill drift followers could bloat the hot log. Resolved by arithmetic: even 200 orders/day × ~1 KB is ~73 MB/yr — noise next to sampled ticks; adopted without sampling. Tick ring-buffer policy untouched.
10. **Auditor's sign-off condition for the pass.** Every §1 scenario must appear in the CI scenario suite (Pass 3 §7.3's F-001/F-008 suite extended): news blowout with resting orders, rollover modify burst, Sunday gap over pending stops (both policies), storm during exit, stops_level widen with resting limit, freeze-band trail approach, netting reduce-only race, OCO double-fill (both orderings, plus discovered-at-reconnect), disconnect mid-send with SL-in-request verification. Accepted; the suite list is normative for Pass 7's CI design.

---

## §7 Findings-resolution table

| Finding | Resolution in this pass | Section |
|---|---|---|
| **F-001** (execution arm) | Budget reserved at placement → debited per partial → released on remainder death; partial policies per urgency; SL-in-request makes confirm-window partials born-stopped | §1.10, §1.11-1 |
| **F-002** | Execution-layer behavior designed for BOTH account types (hedging full model; netting degraded mode + reduce-only guard; synthetic tranches designed-and-rejected); decision matrix supplied; **default remains OPEN-FOR-HUMAN** | §1.7 |
| **F-006** | Calendar & time service specified: IANA session tables, rollover anchored 17:00 America/New_York, DST mismatch windows precomputed + child-blocking, broker clock offset continuously measured, bot-owned day boundaries | §1.0 |
| **F-007** | Spec-diff impact analyzer: per-field severity + mandated actions/deadlines; 60 s hot-poll for at-risk instruments; CRITICAL when open positions affected; widen-and-trim vs cancel policies | §1.5 |
| **F-010** | Pass 3 arms adopted; extended to freeze-band cancels (`probably_filling` pre-arm), OCO twin fills (rows 6–7 = the F-010 arm inside OCO), news-suspend re-place races, reconnect-discovered fills | §1.9, §3.5, §1.1 |
| **F-011** (execution/gap realities) | Weekend pending-order policies; open quarantine; gap-fill tagging; simulator fills gapped stops/SLs at the open — k× budgets become calibratable against measured gap fills | §1.3, §4.7 |
| **F-012** | **The execution simulator spec:** trade-through limit fills, adverse-selection term (pre-live 0.5× credit → measured `post_fill_drift`), one-sided stop slippage, session/news/rollover/open spread regimes, latency, requote/storm, partials, gap opens, calibration with floors, honest blind spots | §1.6, §4, §5 |
| **F-019** (interplay) | Pass-3 resolution adopted; netting mode extends the block to same-direction stacking | §1.7 |
| **F-021** | Blackout mechanics: two-layer (strategy ±60 min + execution hard gate T−120 s/T+180 s, currency-scoped, queue-and-release); OCO double-fill full state machine; `T_grace` = measured parameter with starting hypothesis 5 s + backtest/live measurement plan + recalibration rule + escalation cap | §1.1, §3.5 |
| **F-022** (execution arm) | Signed slippage vs declared reference price in every order record; gap-fill tags; realized-risk recompute path (Pass 3) fed with authoritative fill data | §1.6, §5 |
| **F-023** | Spec freshness at signal time confirmed (Pass 3 OMS row 1 guard); extended to swap fields; 60 s hot-poll for instruments with working orders/positions | §1.5, §1.8 |
| **F-025** | Calendar-aware staleness: expected-bar grid + per-session quote-age thresholds; both Pass-1 failure examples are unit tests | §1.0 |
| **F-029** (execution scope) | Per-cell min samples (100 fills; 50 touch-episodes; 200 market fills; 50 OCO resolutions), weekly-block evaluation, hysteresis + 20% improvement margin on mechanism flips, priors-as-floors (0.7× floor), counter reset on flip, versioned models pinned per run | §2, §3.5, §4.8 |
| **F-030** (execution leg) | Monthly simulator-vs-realized drift check with acceptance bands; persistent optimism → gate evidence invalidated + re-run; demo telemetry never overwrites live cell priors | §4.8-5, §4.9-6 |
| New (this pass) | Rollover micro-session; storm detector/degraded mode; freeze guard + deferred-modify coalescing; SL-in-request rule; modify rate budgets; min-reprice formula; broker-side GTD as belt-and-braces | §1.2, §1.4, §1.9, §1.11, §3 |

**Constraints exported to Passes 5–8:** (Pass 5) calendar_svc is a first-class owned service with the §1.0 test cases; the entry-queue and deferred-modify structures are core-process state that must survive crash (they are projection fields, event-sourced); telemetry upcaster for `exec.telemetry_sample → exec.order_record`. (Pass 6) queue/defer states, storm mode, DST-mismatch blocks, and netting-mode restriction must be *visible* in GUI/Telegram (an operator who can't see "entries queued: news gate" will think the bot is broken); OCO double-fill CRITICAL wording specified. (Pass 7) the CI scenario suite of §6-10 is normative; G1 reports run both fill models; viability-threshold calibration consumes §4 cost waterfalls; M1's G2 exit criterion binds on `exec.post_fill_drift`; simulator acceptance bands (§4.8-5) are a standing pipeline gate. (Pass 8) F-002 and F-016 decision matrices ready for the human; the SL-in-request rule and exits-always-with-safety-modify-class are non-negotiable synthesis inputs.

— End of Pass 4. Every threshold above is (hypothesis) or (literature-informed) until the named telemetry cell reaches its minimum sample; the simulator is honest about what it cannot see.
