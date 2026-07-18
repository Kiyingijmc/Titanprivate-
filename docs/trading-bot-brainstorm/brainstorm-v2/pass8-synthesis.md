# PASS 8 — SYNTHESIS & ROADMAP (FINAL)

**Chair:** Chief Systems Architect (synthesis authority), with the A-Tier Auditor & Accountant as co-signatory on every reconciliation ruling. **Contributors:** all ten seats.
**Inputs (read in full):** `00-overview.md`–`05-…`, `pass1-audit.md` (F-001…F-039 + F-040/041/042 born in Pass 7), `pass2-research.md`, `pass3-systems.md`, `pass4-execution.md`, `pass5-interfaces.md`, `pass6-accounting.md`, `pass7-innovation.md`.
**Mandate:** reconcile everything; invent nothing except where reconciliation forces a decision. Every forced decision below is marked **[FORCED]** and attributed.
**Status:** this document is the summit's single source of truth. Where it conflicts with an earlier pass, **this document wins**; the earlier text stands as history. Where it is silent, the pass of record wins.
**Locked-requirements verification (performed, §1.14):** two families → child models ✓ · three modes per child ✓ (shadow is a *stage*, not a mode — Pass 7 §2.1) · validated config ✓ · compute-once feature engine identical live+backtest ✓ (Pass 3 §5.1 structural parity) · automatic broker discovery + capability tagging ✓ · market-vs-pending intelligence + pending lifecycle ✓ (Pass 4 §2–§3) · risk enforced every mode, exits always automated, kill paths always available ✓ (incl. Pass 5 §2.7 throttle exemption + Pass 7 Sentinel) · no online self-modification of entry logic ✓ (Threshold Lab refuses strategy-param grids; swap-dodge scheduler graveyarded for exactly this) · every number labeled ✓ (measured / literature-informed / hypothesis convention applied in every pass).

---

## §1 Contradiction sweep

Method: the seven pass files were walked pairwise against each other and against the Pass-1 register dispositions. Passes 4/5/6 wrote concurrently against Pass 3 as their shared base, so most collisions are between those three and Pass 3, plus Pass 7's two deliberate amendments. Fourteen items follow. Each: the conflict, the ruling, the ruling seat, the rationale. Rulings are FINAL unless marked otherwise.

### 1.1 `confirm.hold_applied` amendment (Pass 5 §1.7) vs Pass 3 §2.1 signal machine — **ADOPTED**

**Conflict.** Pass 5 defined Snooze/Hold as *a claim of the decision*: it disarms the hybrid timeout (signal thereafter resolves only by human action or `valid_until` expiry) via a new event `confirm.hold_applied {signal_id, actor, timeout_cancelled:true}` and a `held:bool` flag, with Pass 3 §2.1 row 10's guard gaining `∧ ¬held`. Pass 3's machine as written has no such flag; Pass 7 explicitly left the amendment pending Pass-8 adoption.
**Ruling (Backend Architect + Chief Systems Architect): ADOPT.** The amendment is additive — no new state, no new transition row, one guard conjunct, one flag alongside the existing `resting`/`delivery_acked` flags (Pass 3's own flags-not-states convention). It rides the STA queue, so the F-008 serialization analysis is untouched. The Strategist's Pass-5 dissent (distracted humans killing execute-on-timeout signals) was already resolved 9–1 with the T-2-min re-ping + decision-value pricing; nothing new has emerged. Pass 3 §2.1 is amended by errata: **row 10 guard = `hybrid ∧ action=execute ∧ delivery_acked ∧ ¬held`**; row-12 (`action=skip`) is unaffected (a held skip-signal still skips at expiry, which is identical behavior); `confirm.hold_applied` joins the §1.2 `confirm.*` schema family.

### 1.2 G2 redefinition (Pass 7 §2.1) vs Pass 2 §1.4 / M1 G2 exit criteria vs doc 05 §B4 — **ADOPTED, with one forced quantification**

**Conflict.** Doc 05 §B4 defines G2 as "≥ 8 weeks or ≥ 30 trades on demo; results within Monte-Carlo cone of backtest; execution telemetry sane." Pass 1 (F-030) reframed G2 as logic-parity + infrastructure soak because demo fills are optimistic and the MC-cone-on-demo test mostly re-tests signal logic. Pass 2 then hung a measurement-typed exit criterion on G2 (M1's measured adverse selection replaces the 50%-credit hypothesis before G3). Pass 7 §2.1 redefines G2 as: (a) shadow soak ≥ 4 weeks / ≥ 2 blocks with zero kernel-parity diffs, (b) infrastructure soak on demo for broker-integration paths, (c) any dossier-named measured-data exit criteria — with guardrail G4 ensuring (c) can never be satisfied by shadow.
**Ruling (Quant Researcher + Auditor): ADOPT the Pass-7 redefinition; doc 05 §B4's G2 row is SUPERSEDED.** The three-part structure is strictly stronger evidence than the old demo cone: it keeps everything F-030 said was actually informative (logic parity, infrastructure behavior, real-feed measurements) and drops the part F-030 proved was theater (demo P&L inside a cone of frictionless fills). Pass 2's Stage-R/Stage-L template is untouched (Stage-L is live, not G2); Pass 2's M1 criterion survives verbatim as a (c)-item under G4. Chain of custody re-checked: F-030 → RESOLVED via Pass 4 §4.8-5 (execution leg) + Pass 7 §2.1 (evidential leg), adoption completed here.
**[FORCED] Quantification the redefinition left open:** part (b), demo infrastructure soak, had no duration or acceptance. Ruled: **≥ 2 continuous weeks on demo covering ≥ 1 weekend boundary and ≥ 10 rollover cycles, with reconcile verdict CLEAN/REPAIRED on every run, zero CRITICALs, zero duplicate executions, and ≥ 20 order round-trips exercising discovery, spec-diff, and cancel paths (hypothesis; joins the calibration register as CAL-23, sign-off DEV + NET, reviewable via CAL-22's promotion-cycle review).** Rationale: (b) exists to prove broker-integration plumbing, which is exercised per-event, not per-calendar-month; two weeks with the named boundary events covers every §1-of-Pass-4 scenario class at least once.

### 1.3 Netting: Pass 3 §8.7 vs Pass 4 §1.7 vs Pass 6 §1.4 — **HARMONIZED; default posture stays OPEN-FOR-HUMAN**

Three collisions found inside the F-002 complex:
1. **Shipped default in the Pass-3 code sketch vs its own matrix.** Pass 3 §8.7's pseudocode has `config.netting_policy` defaulting to `REFUSE (default-safe)` while the same section's decision matrix recommends **B (degraded mode)** as default. Pass 4 §1.7 recommends "A-with-B-fallback" (prefer hedging where the operator has the choice; B engages automatically on netting with a one-time GUI acknowledgment). Pass 6 adds that B also makes the *books* trivially exact (one child per instrument ⇒ average-cost mixing is harmless).
   **Ruling (Algo-Bot Dev + Auditor):** the shipped default is **`netting_policy: DEGRADED`** (B) with the one-time GUI acknowledgment from Pass 4; `REFUSE` remains a config option for conservative operators. The Pass-3 pseudocode comment is corrected. Rationale: three passes independently converged on B (stop integrity native, attribution exact by restriction, books exact); shipping REFUSE-by-default would make the most common non-hedging operator experience "the bot refuses to run" — a failure of the capital-access criterion all three matrices scored. The *posture* question (should the operator seek a hedging account at all) remains the human's — decision sheet H1 (§5).
2. **Event naming for same-direction stacking.** Pass 3 §8.7: same-direction blocked as `NETTING_OCCUPANCY`, opposing as `POSITION_CONFLICT`. Pass 4 §1.7: "both emit `POSITION_CONFLICT`."
   **Ruling (Backend Architect):** Pass 3's two-name scheme wins — the two blocks have different causes and different operator remedies (occupancy = wait or close; conflict = thesis disagreement worth seeing), and telemetry that merges them can't be un-merged. Pass 4 errata noted.
3. **Additions carried forward, no conflict:** Pass 4's reduce-only guard (position-read ≤ 1 s before any netting close) and the don't-hand-trade-bot-symbols operator rule are adopted as part of the F-002 design of record; Pass 6 §4.2's allocator + `basis_translation` dimension is the attribution mechanism of record and the mandatory foundation for any future option-C build.

### 1.4 Pass 6 pro-B bookkeeping argument joins the F-002 matrix — **RECORDED**

Per Pass 6 §9's export: the consolidated F-002 matrix on the decision sheet (§5, H1) now carries a fourth criterion row — *books reconcile per-deal exactly* — scoring: A native-exact, B trivially-exact, C requires the full Book-A translation machinery under multi-child mixing. This strengthens the board's B recommendation; it does not change any pass's text.

### 1.5 F-013 chain end-to-end (Pass 1 → Pass 2 §1.4 → Pass 5 §5.1 → Pass 7 CAL-08) — **CONSISTENT, one terminology fix**

Walked: Pass 1 (block evaluation, 95% ⇒ WARN only, 99% sustained 2 blocks ⇒ risk-halve, demote needs +ack or corroborating execution shift) → Pass 2 §1.4 (identical template, blocks of 20 trades / 4 weeks) → Pass 5 §5.1 (block ribbon + CUSUM track, two labeled boundaries, per-trade cone banned, mid-block cells verdict-free) → Pass 7 CAL-08 (one-sided decay CUSUM, κ=0.5, WARN h=2.5, ACTION h=4.0 sustained 2 blocks, ARL₀ ≥ 40/200 blocks, ARL₁ ≤ 8, per-child simulation calibration before Stage-L arms; C-CUS controls). **Every substantive element is consistent**: block-only evaluation, WARN-vs-ACTION asymmetry, 2-block sustain, demotion corroboration requirement, display-of-the-actual-statistic.
**One inconsistency (terminology):** Pass 5's boundary labels read "WARN (95%)" / "ACTION (99%…)" — percent-quantile language from before CAL-08 replaced quantiles with ARL-calibrated h-values. A boundary labeled "95%" that is actually "h=2.5 tuned to ARL₀ ≥ 40" would be the display lying about its own mechanism, which Pass 5 itself forbids.
**Ruling (Quant + Frontend Architect): [FORCED]** display labels become **"WARN (h = 2.5)"** and **"ACTION (h = 4.0, sustain 2 blocks → risk halved)"** with the per-child calibrated values substituted at render; the caption gains one sentence: "boundaries calibrated per child to a false-alarm budget (ARL), not fixed percentiles." Pass 5's display contract (two labeled lines) is preserved exactly as its export demanded.

### 1.6 SL-in-entry-request (Pass 4 §1.11-1) vs Pass 3 §2.3 attach-on-fill rows — **RATIFIED**

**Conflict (apparent).** Pass 3 §2.3 rows 2–4 specify stop-attach-on-fill with retry/backoff and the `OPEN_STOP_UNVERIFIED` escalation; Pass 4 §1.11-1 mandates SL (and TP where planned) in the initial entry request, demoting attach-on-fill to the fallback for stops_level-illegal-at-send cases. Pass 4 §6-1 records the Architect's verification of compatibility.
**Ruling (Architect + Algo-Bot Dev): RATIFIED as the design of record.** Pass 3 §2.3 rows 2–4 are re-titled *"fallback path — SL not accepted at send"*; row 2's normal case is satisfied by the entry ack itself (`stop_verified=true` on ack of an order carrying SL). Pass 3 §2.1 rows 15–16 (partial/full fill during confirmation "attach stop immediately") are likewise normally pre-satisfied — the resting order already carried the stop. The chaos suite's "disconnect mid-send with SL-in-request verification" row (Pass 4 §6-10) is the pinned proof. This is a non-negotiable synthesis input per Pass 4's export, and the board re-affirms it: it is the single change that most shrinks the stopless-position window, and it costs nothing.

### 1.7 Broker-clock-offset drift threshold: Pass 3 §8.3 vs Pass 4 §1.0 — **60 s + entry block wins**

**Conflict.** Pass 3 §8.3: measured broker offset drifting > **90 s** from session baseline ⇒ WARN. Pass 4 §1.0: drift > **60 s** ⇒ WARN **+ session-scoped entries blocked**. CAL-17 registered the 60 s figure.
**Ruling (Networking & Infrastructure): Pass 4 wins** — 60 s, WARN + session-entry block. It is later, stricter, register-backed, and the blocking action is the correct consequence (a session table computed against a drifted clock is exactly the F-006 failure). Pass 3 §8.3's 90 s is superseded.

### 1.8 Swap accrual double-ownership: Pass 4 §1.8 vs Pass 6 §2.2 — **LAYERED**

**Conflict.** Both passes specified swap accrual concurrently. Pass 4 §1.8: the reconciler emits `position.swap_accrued` from the *broker position field's delta* after each rollover ("rates are for forecasts, accruals are facts"); mark-to-market P&L includes it. Pass 6 §2.2: a core timer posts `ledger.accrual` at the *predicted* amount from discovered rates, settled against broker `DEAL_SWAP` at close via the 4110 true-up, with nightly posted-vs-predicted checks "where the broker exposes it." As written, a naive implementation would book swap twice, from two sources, on two events.
**Ruling (Auditor + Algo-Bot Dev): [FORCED] layer them — one posting path, one verification path.** The **books post predictions**: `ledger.accrual` (Pass 6) is the sole ledger entry for open-position swap, because it exists for every broker (including those that only materialize swap at close) and keeps the posting rules broker-independent. Pass 4's `position.swap_accrued` (broker-field delta observed by the reconciler) is **the verification feed**: it is precisely the "where the broker exposes it" data source for Pass 6 §2.2 check #1, and it updates the position projection's mark-to-market (so breakers and GUI see broker-truth swap where available, prediction otherwise, source-labeled). No amount from `position.swap_accrued` ever posts to a 4xxx account directly; discrepancy beyond `T_swap` raises `SWAP_MISMATCH` exactly as Pass 6 specifies. Both events survive; their roles are now exclusive.

### 1.9 Viability hysteresis pair: Pass 2 M1 dossier (1.2 / 1.5) vs CAL-01 (1.5 / 1.8) — **register wins**

**Conflict.** Pass 2 §3.1(f) gave M1 a Stage-L cost falsifier "viability < 1.2 for 2 weeks → auto-disable; hysteresis re-enable at ≥ 1.5." Pass 7 CAL-01 registers the system-wide pair as disable < **1.5** / re-enable ≥ **1.8**. A child at viability 1.3 trades under the dossier and is disabled under the register.
**Ruling (Quant + Auditor):** the calibration register governs — that is what the register *is for* (Pass 7 §4 governance: a threshold without a register row is a schema error; a register row without register governance is a second config nobody reconciles). The dossier's pair is superseded as a dossier-era hypothesis written before CAL-01 existed. If M1's economics genuinely justify a per-child override (its 2-week evaluation window may — M1 trades fast), that override enters through a CAL-01 Threshold-Lab artifact, not through dossier text. Pass 2 errata noted.

### 1.10 First-gate fill model: Pass 3 §5.2 (Conservative v1) vs Pass 4 §4.0 (Realistic supersedes for gate evidence) — **supersession confirmed, sequencing preserved**

Not a true contradiction — Pass 4 explicitly supersedes — but the build-order implication needed a ruling: Pass 3 ships `ConservativeFillModel` first (it is small and unblocks the kernel); **no G1 verdict may be issued on Conservative-only runs** — the both-models rule (Pass 4 §6-6) plus admissibility precondition (b) (Pass 7 §5.1) already encode this, and the build order (§4, M2/M3) sequences `RealisticFillModel` before the first admissible G1. Conservative remains the permanent floor run. Confirmed; no text change.

### 1.11 Pass-1 disposition routing vs the summit re-scope — **close-out table is the authority**

Pass 1's disposition column routed findings to pass numbers under the original topic plan; Passes 3–6 re-scoped (Pass 3 absorbed the state/architecture items routed "Pass 5"; Pass 5 took interfaces items routed "Pass 6"; Pass 6 disclaimed non-money items routed to it and took money items routed elsewhere; Pass 4 claimed all execution-subject findings). Every pass declared its ownership rule inline; Pass 6 §9 even carries an explicit re-route row. **Ruling (Chair):** the re-scope is accepted retroactively; the §3 close-out table below is the sole authority on where each finding was resolved. No finding fell into the gap between the old and new routing — verified by walking all 42 (§3).

### 1.12 DST-mismatch window blocking: Pass 2 ("until the calendar service is proven") vs Pass 4 §1.0 ("blocked … until the service passes its parity tests") — **clarified**

The two phrasings permit different readings (blocked always vs blocked only pre-proof). **Ruling (Networking + Day Trader): [FORCED]** session children are blocked during DST-mismatch windows **until `calendar_svc` has passed its named parity test cases in CI *and* has been observed through one full real mismatch window with zero session-labeling diffs** (the test cases prove the logic; one real window proves the tzdb/broker interaction). Thereafter mismatch-window trading is permitted; the windows stay flagged in telemetry (`dst_mismatch_flag`, already in `exec.order_record`) so the Threshold Lab can price whether the unblocked windows actually pay.

### 1.13 Minor harmonizations (recorded, no debate needed)

| # | Item | Ruling |
|---|---|---|
| a | `exec.telemetry_sample` → `exec.order_record` supersession (Pass 4 §5) | Confirmed; upcaster registered per Pass 3 §1.1; both valid in old logs. |
| b | Kill-path rate-limit exemption (Pass 5 §2.7) vs Pass 3 §8.5 core-side rate limits | Pass 3 §8.5's limiter must carry the exemption for `/killswitch` and `/flatten all`; pinned unit test (Pass 5's requirement) is the acceptance. |
| c | Reconcile cadence: Pass 3 §3.3 60 s periodic vs Pass 3 §9-6 heartbeat-diff mini-recon | Debate-log resolution is normative (mini-recon between full pulls); §3.3 text updated by errata. |
| d | Child-health strip placement (Pass 7 §2.3) vs Pass 5 §1.2 field order | Strip renders as block 5-bis (between AGAINST and execution details) — exactly where Pass 7 specified; Pass 5's block numbering gains one row; the 3-second test (lines 1–3) is unaffected. |
| e | Money in floats (Pass 3 §1.2 payload conventions) vs Pass 6 integer micro-units | Pass 6's own reconciliation stands: stored money = i64 micro-units; risk fractions and prices remain floats (ratios and quotes, not money). Schema upcasters cover `position.closed.pnl_ccy` etc. — money-bearing fields gain `_micro` twins; old fields retained for display compatibility. |
| f | Doc 05 §D3 demotion rules (95% cone → auto-halve) vs F-013 resolution | Doc 05 §D3 superseded by CAL-08 (already implied by Pass 1; now recorded). |
| g | Doc 00 stack line "MetaTrader5 lib" | Superseded by F-016's bridge architectures — under either topology the core does not import the `MetaTrader5` package (Windows-side bridge owns terminal access). |

### 1.14 Locked-requirements sweep result

All seven pass files were checked against the nine locked requirements (header). **No violation found.** Two near-misses worth recording as negative results: (i) the swap-dodge exit scheduler (Pass 7 §1.8) would have violated no-online-self-modification and was correctly graveyarded by the board before reaching this pass; (ii) the shadow stage skirts the three-modes-per-child lock and survives only because it is a deployment stage with modes forced-auto and no cards — the board re-affirms that any future proposal to give shadow children confirmation flows must be rejected (it would create a fourth de-facto mode).

---

## §2 Final decision register

Every major decision of the summit. **Status: FINAL** = board-decided, implementation-normative; **OPEN** = OPEN-FOR-HUMAN (appears on the §5 decision sheet). "Record" = pass §. Objections are compressed to the one that changed content.

| ID | Decision | Owner seat | Record | Key objection → resolution | Status |
|---|---|---|---|---|---|
| D-001 | Viability arithmetic: all terms in ticks; expectancy numerator; old threshold "4" void | Auditor+Quant | P1 F-003, P2 §1.3 | Gate was inert as specced → formula rebuilt, C-VIAB regression control pinned | FINAL |
| D-002 | Evidence-honesty regime: measured/literature-informed/hypothesis labels; E1–E3 grading; named-loser rule; post-publication-decay prior | Quant+Strategist | P2 §1.1–1.2 | — (charter-derived) | FINAL |
| D-003 | Two-stage falsification template (Stage-R pre-registered / Stage-L CUSUM blocks) binding on every child | Quant | P2 §1.4 | Over-damping vs false alarms → block evaluation, 99%×2 action | FINAL |
| D-004 | Roster build priority: T1, TC-2, M2, M1, T2, T4, M4(after measurement), M3, T3, TC-1, MC-1; MC-2 deferred (architecture-blocked) | Board vote | P2 §8 | Strategist vs TC-2 displacing T3 → T3 demoted not dropped (9–1) | FINAL |
| D-005 | T3 ships long-top-k+flat; shorts per-instrument only on positive swap-inclusive backtest | Quant+Auditor | P2 §2.3e | "Half a strategy" → swap math decision matrix, carried 8–2 | FINAL |
| D-006 | Regime engine: E0 confidence/dwell/hysteresis MANDATORY; E1 EWMA ADOPT; E2 narrow ADOPT; E3 DEFER (named re-entry); E4 HMM REJECT | Quant | P2 §4 | Dwell delays trend entry → dwell binds published labels only | FINAL |
| D-007 | Event envelope + hash chain + snapshots + archive + verified backup + RECOVERY_REQUIRED refuse-to-trade | Architect+Auditor | P3 §1.1–1.3 | Sidecar outside audit → chain covers sidecar hash | FINAL |
| D-008 | Core process is sole DB writer, total; interface read-only forever; all mutations via HMAC command channel | Backend Architect | P3 §1.4, §8.5 | — (collapses F-008+F-015) | FINAL |
| D-009 | Signal Transition Actor: one serialized owner; requests-not-transitions; event-time guards; race_losers truth | Backend Architect | P3 §2.1 | — | FINAL |
| D-010 | Fill-during-confirmation edges; budget reserved at placement; veto-after-fill closes filled part; timeout/expiry NEVER auto-closes a filled part | Algo-Bot Dev | P3 §2.1 r15–21 | FE vs timer-close of unconfirmed partials → adopt-and-manage, human veto only closes (§9-1) | FINAL |
| D-011 | 11-limit exposure stack with declared gross/net, exclusive classes, macro-factor caps, gap-stressed + margin + notional columns; binding-order report | Quant+Auditor | P3 §2.6 | — | FINAL |
| D-012 | At-most-once send per attempt + reconcile-to-exactly-once effects; client_key scheme; intent-persisted-before-send is the attribution authority | Algo-Bot Dev | P3 §3 | Auditor vs "exactly-once" claim → wording + DUPLICATE_EXECUTION counted event | FINAL |
| D-013 | Feature engine REBUILD: persistent incremental nodes, per-(instrument,tf) BarClock, state manifests, replay validator + rebuild + canary | Architect | P3 §4 | Canary tolerance vs float drift → 1e-9 relative + 10k-bar recompute (CAL-16) | FINAL |
| D-014 | Backtester = same composition root, three substitutions (SimClock/SimBroker/ConfirmationPolicy); run-cards; committed frozen-lake manifest; golden-replay parity zero-tolerance | Architect | P3 §5 | — | FINAL |
| D-015 | Titan prior-art verdicts (BORROW/ADAPT/REBUILD) at file level | Architect | P3 §6.2, P5 §7 | — | FINAL |
| D-016 | Platform topology: recommended (b) Linux core + Windows bridge | Networking | P3 §8.1 | Infra cost objection → recorded in matrix, not resolved away | **OPEN** (F-016, H2) |
| D-017 | Netting: discovery gate; degraded mode B designed; shipped default `DEGRADED` w/ one-time ack (Pass-8 harmonization §1.3); option C designed-and-rejected for v1 (10–0); reduce-only guard | Algo-Bot Dev+Auditor | P3 §8.7, P4 §1.7, P6 §1.4, P8 §1.3 | Synthetic stops die with the bot → C rejected | **OPEN** (F-002 posture, H1) |
| D-018 | Interface process split (:8790) from core (:8770); GUI/Telegram out of trading loop | Backend Architect | P3 §9-2, §8.2 | Titan embedded pattern vs loop protection → split | FINAL |
| D-019 | Calendar/time service: IANA sessions, floating 17:00-NY rollover, DST windows precomputed, news calendar fail-closed, expected-bar grid, bot-owned day boundaries | Networking | P4 §1.0 | — | FINAL |
| D-020 | Two-layer news blackout; execution hard gate T−120 s→T+180 s currency-scoped; queue-and-release at gate_ratio ≤ 1.5 ×3 samples | Day Trader | P4 §1.1 | Generic 3.0 release pays 2–3× cost → 1.5 rule (§6-3); CAL-11 | FINAL |
| D-021 | Rollover micro-session 16:55–17:10 NY: no entries, coalesced deferred modifies, exits allowed+flagged | Day Trader | P4 §1.2 | Blanket no-modify was a safety regression → safety-modify class always allowed (§6-2) | FINAL |
| D-022 | Weekend pending-order default-cancel (meanrev always; trend default-cancel w/ `keep_with_gap_guard` opt-in); 5-min open quarantine; gap-fill tagging | Swing Trader | P4 §1.3 | Strategist "gap IS the breakout" → 8–2, child may re-emit Monday; shadow accounting of cancelled cohort | FINAL |
| D-023 | Storm detector + degraded mode (entries queued, exits widened-deviation) | Algo-Bot Dev | P4 §1.4 | — (CAL-12) | FINAL |
| D-024 | Spec-diff impact analyzer: per-field severities + mandated actions + 60 s hot-poll for at-risk instruments | Algo-Bot Dev | P4 §1.5 | — | FINAL |
| D-025 | SL/TP in the entry request; attach-on-fill = fallback only | Algo-Bot Dev | P4 §1.11-1, P8 §1.6 | — (unanimous; "most consequential change") | FINAL |
| D-026 | Mechanism decision matrix v2 with F-029 min-samples, hysteresis, priors-as-floors, flip-resets-counter; synthetic position-SLs forbidden forever | Day Trader+Dev | P4 §2 | Networking vs synthetics → entry-only asymmetry accepted 9–1 | FINAL |
| D-027 | OCO machine: atomic arming, immediate unconditional twin-flatten, T_grace as measured classification boundary (5 s start, clamp [2,15] s) | Day Trader | P4 §3.5 | Elastic grace absorbs broker decay → cap + broker-quality CRITICAL (§6-5); CAL-10 | FINAL |
| D-028 | RealisticFillModel spec (trade-through limits, one-sided stop slip, session/news/rollover/open spread regimes, storms, gaps); both-models rule for every gate report; monthly sim-vs-realized drift check invalidates optimistic evidence | Dev+Quant | P4 §4 | Single-model gate passes are execution bets → both models (§6-6); CAL-06 | FINAL |
| D-029 | Confirmation card: risk-first field order, mandatory AGAINST line, silence line with consequence, 3-second test, "exits bot-managed" on every card | Frontend Architect | P5 §1.2–1.3 | Day Trader wanted price on line 2 → mock-session evidence, 8–2 | FINAL |
| D-030 | Snooze = claim of decision (`confirm.hold_applied`, timeout disarmed, never extends validity) | Frontend Architect | P5 §1.7, P8 §1.1 | Strategist: distracted humans kill signals → re-ping + decision-value pricing, 9–1 | FINAL |
| D-031 | Version-pinned approvals (material changes only); rejects never pinned; idempotent taps | Frontend+Backend | P5 §1.8 | Retry-loop under pressure → material-only bumps | FINAL |
| D-032 | No optimistic rendering of outcomes; RESOLVING spinner; event-truth only; race truth verbatim | Frontend Architect | P5 §3.4 | FE withdrew own optimistic draft on F-008 re-read | FINAL |
| D-033 | Quiet-hours taxonomy total mapping; confirmations delivered silent, timeout unchanged (per-child override; eyes-open setup notice) | Both traders | P5 §2.5 | Swing vs Day trader deadlock → per-child config with honest default | **OPEN** (ratify default, H5) |
| D-034 | Kill paths never rate-limited at any layer (pinned test) | Auditor | P5 §2.7 | — | FINAL |
| D-035 | Graduation panel: evidence checklist, zero prescriptive copy, asymmetric friction (restrict=1 tap, free=filled checklist) | Quant | P5 §6.4 | "Consider AUTO" nudge deleted | **OPEN** (threshold ratification, H6/CAL-09) |
| D-036 | Double-entry machine-generated ledger; integer micro-units; three books (B mirror-broker / A tranches / T tax-on-export); trial-balance identities | Auditor | P6 §1 | BE "ceremony" → machine-generated postings; Bot Dev's avg-cost catch killed FIFO Book B | FINAL |
| D-037 | Ledger/cost-model boundary law: fill-time facts in books, expectation terms (adverse selection) in cost model | Auditor+Quant | P6 §8-2 | — | FINAL |
| D-038 | Swap: predicted accrual posts, broker-field verification feed, discovered triple-day, empirical checks, weekly rate-drift → viability recompute | Auditor+Swing | P6 §2.2, P4 §1.8, P8 §1.8 | Double-ownership → layered (posting vs verification) | FINAL |
| D-039 | Conversion: rate-source hierarchy w/ conservative side, timestamp law, stale-conversion blocks entries, drift to 4400 as first-class cost | Auditor | P6 §3 | Strategist vs CRITICAL-halt on one drift → 0.2/0.5/1.0% ladder + trend guard | FINAL |
| D-040 | Money reconciliation: daily deal-level + cash equation + equity identity; monthly three-way (ledger/API/statement) w/ archive re-derivation; diff taxonomy w/ halt-new-risk CRITICALs | Auditor | P6 §5 | Infra veto of portal scraping → terminal statement via bridge, parse-fail WARN-only | FINAL (CAL-04) |
| D-041 | Attribution partition invariant (I7); 1900/4900 embarrassment buckets alarmed at 0.1%/0.5% equity | Auditor | P6 §4 | — (CAL-05) | FINAL |
| D-042 | Tax exports: records not returns; lot policy stamped, never defaulted; closed-months-only; byte-deterministic | Auditor | P6 §7 | — | **OPEN** (policy value, H4) |
| D-043 | Shadow stage adopted with guardrails G1–G4 (cap 4, budget-tagged, never counts toward live minimums, drift-check-chained admissibility, measurement-typed criteria excluded) | Architect | P7 §2.1 | Day Trader: model-flattered scalps → G4; Auditor: evidence creep → badges + exclusions | FINAL |
| D-044 | G2 redefined: shadow logic-parity + demo infra soak (CAL-23, §1.2) + dossier-named measurements; doc 05 §B4 G2 superseded | Quant+Auditor | P7 §2.1, P8 §1.2 | — | FINAL |
| D-045 | Threshold Lab: pre-registered frozen grids, CI'd counterfactuals, analytics badges, 1 change/item/quarter citing artifacts | Quant | P7 §2.2 | Auditor forking-paths No vote → rails + Pass-8 cadence ratification request | **OPEN** (cadence ratification, H10) |
| D-046 | Child-health strip on cards (block-frame, frozen, insufficient-sample rendering, own effect measured w/ rollback trigger) | Strategist | P7 §2.3 | QNT anchoring → measurement covariate, 10–0 | FINAL |
| D-047 | Randomized execution A/B: entry legs only, deterministic assignment, OBF spending, 2R/0.5R budgets tighter-of-modeled/realized, probation children excluded, ≤2 concurrent | Algo-Bot Dev | P7 §2.4 | STR/AUD tuition caps; QNT peeking → block-boundary analysis | FINAL (CAL-20) |
| D-048 | Stop Sentinel: independent close-only watchdog, own channels, alert-only v1, drills mandatory before first real-money week | Networking | P7 §2.5 | BE second-actor objection → writes nothing we own, close-only CI static check | FINAL (arming: **OPEN**, H3) |
| D-049 | Broker scorecard + migration dossier: cost drag in R/yr, switching-cost line, 12-month amortization, demo-grade haircut ×1.3 | Auditor | P7 §2.6 | STR churn objection → switching-cost + 2-month sustain, 10–0 | FINAL (CAL-21) |
| D-050 | Gate-control suite: NC/PC specimens, planted-lie controls for every judge, admissibility preconditions, constitution rule (control edits need board sign-off); **controls precede the first G1 verdict ever** | Auditor+Quant | P7 §5 | PC-2 soft assertion → mechanical disjunction (§6-8) | FINAL |
| D-051 | Calibration register CAL-01…23 as the source of config validation ranges; register rows render live in GUI | Quant+Auditor | P7 §4, P8 §1.2 | Register sprawl → register IS the config source (§6-10) | FINAL (4 starting values on sheet: H7–H9) |
| D-052 | Graveyard ratified: manual scalp cockpit (2–8), swap-dodge scheduler (1–9), operator flight simulator (3–7, survives as onboarding doc), warm-standby core (1–9) | Board | P7 §3 | — | FINAL |
| D-053 | CUSUM display language: ARL/h-value labels replace percent labels | Quant+FE | P8 §1.5 | — | FINAL |
| D-054 | Broker-offset drift: 60 s + session-entry block (supersedes 90 s WARN-only) | Networking | P8 §1.7 | — | FINAL |
| D-055 | Viability hysteresis pair register-governed (1.5/1.8); dossier-local pairs superseded; per-child overrides only via Lab artifact | Quant+Auditor | P8 §1.9 | — | FINAL |
| D-056 | Build order M0–M8 with acceptance criteria and scope fences (§4) | Architect | P8 §4 | — | FINAL |

**Counts: 56 decisions — 49 FINAL, 7 OPEN-FOR-HUMAN** (D-016, D-017, D-033, D-035, D-042, D-045, D-048-arming; all appear in §5 with their matrices).

---

## §3 Findings close-out — F-001…F-042

Every finding accounted for. "Record" cites the section(s) of final resolution. CAL-nn = residual number lives in the calibration register (procedure exists; value remains hypothesis until calibrated — this does not reopen the finding).

| ID | Sev | Subject (short) | Final status | Record |
|---|---|---|---|---|
| F-001 | CRIT | Partial fill during pending confirmation | **RESOLVED** | P3 §2.1 r5,15–21 · P4 §1.10/§1.11 · P5 §1.6/§1.8 (audit "what they saw") |
| F-002 | CRIT | Netting vs tranches vs broker stops | **OPEN-FOR-HUMAN** (design complete; posture + ratify shipped default) | P3 §8.7 · P4 §1.7 · P6 §1.4/§4.2 · P8 §1.3 · sheet H1 |
| F-003 | CRIT | Viability formula units/numerator | **RESOLVED** (threshold CAL-01, starting value on sheet H7) | P1 (formula) · P2 §1.3 · P3 §7.1 C-VIAB · P7 CAL-01 |
| F-004 | CRIT | Event-log integrity | **RESOLVED** | P3 §1.1/§1.3/§7.4 · P6 §6 (money joins chain; verify-on-restored-backup) |
| F-005 | CRIT | No margin/notional limit; BE frees budget | **RESOLVED** (caps CAL-03) | P3 §2.3/§2.6 #8–10 · P5 display duty |
| F-006 | HIGH | Sessions vs DST vs broker time | **RESOLVED** | P4 §1.0 · P8 §1.12 (mismatch-window unblock rule) |
| F-007 | HIGH | SPEC_CHANGED with open positions | **RESOLVED** | P4 §1.5 (analyzer + hot-poll) · P3 §2.2 r19 |
| F-008 | HIGH | Three actors race one confirmation | **RESOLVED** | P3 §2.1 STA · P5 §1.8/§3.4 (race truth) |
| F-009 | HIGH | Interface outage converts hybrid→auto | **RESOLVED** | P3 §2.1 r6,10–11 · P5 §2.3/§2.4 (ack ladder, degraded modes, dead-man's-channel) |
| F-010 | HIGH | Cancel races fill | **RESOLVED** | P3 §2.1 r20/§2.2 r16 · P4 §1.9/§3.5 (freeze pre-arm, OCO arm, reconnect ordering) |
| F-011 | HIGH | Weekend gaps vs sizing identity | **RESOLVED** (k CAL-02, on sheet H8) | P3 §2.3/§2.6 #8 · P4 §1.3/§4.7 (measured gap fills close the loop) |
| F-012 | HIGH | "Earns spread" / limits-don't-slip | **RESOLVED** (AS term CAL-14) | P1 (claim) · P4 §1.6/§4.6 (trade-through sim) · P6 §2.3 (sign convention, fact/expectation law) |
| F-013 | HIGH | MC-cone demotion, no alpha control | **RESOLVED** | P7 CAL-08 (CUSUM spec + ARL calibration + C-CUS) · P5 §5.1 display · P8 §1.5 label fix |
| F-014 | HIGH | Restart replay trusts broker history | **RESOLVED** | P3 §4.5 (validator/rebuild/canary) + P1 property P1 |
| F-015 | HIGH | Two processes, one SQLite writer | **RESOLVED** | P3 §1.4 (total core ownership) |
| F-016 | HIGH | MT5-on-Linux contradiction | **OPEN-FOR-HUMAN** (matrix complete, default (b)) | P3 §8.1 · sheet H2 |
| F-017 | HIGH | Gross-vs-net ambiguity | **RESOLVED** | P3 §2.6 (declared semantics, exclusive classes, macro-factor caps, register examples as tests) |
| F-018 | MED | Regime confidence/hysteresis | **RESOLVED** (weights CAL-15 plateau study) | P2 §4.1 E0 |
| F-019 | MED | Opposing-intent netting window | **RESOLVED** | P3 §2.6 (pre-route only; POSITION_CONFLICT) · P4 §1.7 · P8 §1.3-2 naming |
| F-020 | MED | T3 rebalance window + swap drag | **RESOLVED** | P2 §2.3 (Monday-London window, swap math, shorts-off) · P6 §2.2 (books + verification) |
| F-021 | MED | OCO double-fill economics | **RESOLVED** (T_grace CAL-10) | P2 §2.4 (kill term) · P4 §1.1/§3.5 |
| F-022 | MED | Realized ≠ approved risk | **RESOLVED** | P3 §2.3 r1/r5 (recompute, RISK_TRIM, never-move-stop) · P4 §1.6/§5 (signed refs) · P6 §2.3 (money mirror) |
| F-023 | MED | Stale tick_value/conversion | **RESOLVED** | P3 §2.2 r1 · P4 §1.5/§1.8 (swap fields) · P6 §3 (hierarchy + timestamp law) |
| F-024 | MED | Anomaly breaker unimplementable | **RESOLVED** (CAL-07) | P3 §2.4 (24 h R vs portfolio-MC windows) |
| F-025 | MED | Calendar-blind staleness | **RESOLVED** (CAL-18) | P4 §1.0 (expected-bar grid) · P5 §3.5 (display) |
| F-026 | MED | Runtime overrides silently win | **RESOLVED** | P5 §5.4 (drawer, provenance, conflict flow, /overrides) |
| F-027 | MED | Param edits hit open positions | **RESOLVED** | P3 §2.3 r6 (pinned params) · P5 §6.2 (surfaced) |
| F-028 | MED | Event-loop stalls | **RESOLVED** (CAL-19) | P3 §4.6 (budgets, ProcessPool, loop-lag) |
| F-029 | MED | Learning-loop circularity/thresholds | **RESOLVED** (CAL-13) | P4 §2/§4.8 (min-samples, floors, flip-reset) · P6 §2.1 · C-CELL |
| F-030 | MED | Demo gate weak evidence | **RESOLVED** | P4 §4.8-5 (drift check) · P7 §2.1 G2 redefinition · P8 §1.2 adoption |
| F-031 | MED | Unauthenticated command path | **RESOLVED** | P3 §8.5 (HMAC channel) · P5 §2.7 (three layers + kill exemption) · P6 §4.3 (money actors) |
| F-032 | MED | Post-crash attribution | **RESOLVED** | P3 §3.1/§3.3 (intent-persisted authority, quarantine) · P6 §4.1 (1900 bucket) |
| F-033 | MED | Clock drift unmonitored | **RESOLVED** (CAL-17) | P3 §8.3 · P4 §1.0 · P6 §3.2 · P8 §1.7 (60 s ruling) · P5 §3.5 display |
| F-034 | MED | Vol-scalar breaches hard cap | **RESOLVED** | P3 §2.6 #1 (re-clamp + pinned test) |
| F-035 | LOW | EXPIRED applies post-fill | **RESOLVED** | P1 · P3 §2.1 expiry scope |
| F-036 | LOW | Dead limits / binding order | **RESOLVED** | P3 §2.6 (binding-order report) · P5 §4 (display) |
| F-037 | LOW | Unlabeled performance numbers | **RESOLVED** | P1 convention; applied in every subsequent pass |
| F-038 | LOW | params_hash canonicalization | **RESOLVED** | P3 §4.2 + property P7 |
| F-039 | LOW | quiet_hours vs severity taxonomy | **RESOLVED** (confirmation-class default on sheet H5) | P5 §2.5 (total mapping) |
| F-040 | (P7) | Shadow-book contamination | **RESOLVED-AT-BIRTH** | P7 (P15 + C-SHDW + write-time refusal) |
| F-041 | (P7) | A/B assignment nondeterminism | **RESOLVED-AT-BIRTH** | P7 §2.4 (hash-of-seed) + determinism CI |
| F-042 | (P7) | Sentinel action-set drift | **RESOLVED-AT-BIRTH** | P7 §2.5 (CI static check, close-only rule, drills) |

**Totals: 42 findings — 40 RESOLVED (8 carrying CAL-registered numbers whose *procedures* are final and *values* are hypothesis), 2 OPEN-FOR-HUMAN (F-002, F-016). Zero dangling dispositions; zero SUPERSEDED-BY (no finding was overtaken — the two doc-05 supersessions in §1.13f/§1.2 are of baseline-doc text, not of findings).**

---

## §4 Updated build order — milestones M0…M8

### 4.1 Reconciliation basis

Doc 00's 7 steps survive as the skeleton; the summit added: the testing pyramid and chaos harness (P3 §7), calendar service as hard predecessor of every session child (P4 §1.0, P2 §7-10), the execution simulator behind the FillModel seam (P4 §4), interface contracts (P5), the money ledger + SimAccount admissibility rule (P6: a backtest whose books don't balance is not G1 evidence), and Pass 7's placements (Lab skeleton at B1, shadow seam at B2, Sentinel at B4, card strip at B5, Lab/A-B/scorecard at B6) plus the constitution rule: **the gate-control suite precedes the first G1 verdict ever issued.** Mapping: M0+M1 ⇒ 00-step 1 (B1) · M2+M3 ⇒ steps 2–3 (B2/B3) · M4 ⇒ step 4 (B4) · M5 ⇒ step 5 (B5) · M6 ⇒ step 6 · M7 ⇒ B6/G3 · M8 ⇒ step 7.

### 4.2 The milestones

**M0 — Trustworthy skeleton** *(no market data, no broker, no strategies)*
Scope: repo + pyproject; config schema (`config/schema.py`: caps, F-034 re-clamp, F-017 memberships, binding-order report, reload classes, CAL-row-sourced ranges); `core/` clock, events envelope + registry + canonical JSON, chained event log + snapshots + archive + backup/restore-verify job, projections, recovery boot sequence, bus (critical-tier subscribers), STA skeleton; property tests P4–P8 + P11 groundwork; CI pipeline skeleton (PR tiers).
Acceptance: (a) corruption drills (truncate, bit-flip payload, bit-flip hash, delete row, sidecar corrupt) each produce `RECOVERY_REQUIRED`, never a clean boot; (b) same-input determinism: identical event stream twice ⇒ identical chain head; (c) sole-writer enforced (second writer attempt fails a test); (d) config validation rejects every Pass-1 register counter-example (F-034 compose, F-017 membership).
Discharges: D-007, D-008 (mechanism), F-004, F-015, F-034/F-017 validation halves, F-035, F-038.
Must NOT contain: any broker code, any indicator, any GUI beyond nothing, any strategy. *Fence rationale: every later milestone stands on this log; scope creep here delays everything.*

**M1 — Time, data, features, kernel** *(the compute-once engine + the backtester are one deliverable)*
Scope: `calendar_svc/` complete (session tables, DST-mismatch windows + named test cases, news ingestion fail-closed, expected-bar grid, broker-offset measurement, day boundaries); ingest + BarClock; feature engine (registry ADAPT, incremental nodes for every §4.3-of-P3 indicator incl. E0/EWMA/session baselines, state store + replay validator + canary); frozen lake + **committed** manifest; run-card CLI; backtest kernel (SimClock, SimBrokerAdapter + `ConservativeFillModel`, ConfirmationPolicy seam); Threshold-Lab harness *skeleton* (decision-event replay plumbing only); golden-replay parity harness.
Acceptance: (a) property P1 (incremental==batch) and P9 (BarClock independence) green across all nodes; (b) DST test-case dates pass; F-025's two failure examples pass; (c) run-card determinism: same manifest ⇒ bit-identical events chain; (d) 15-year replay of the lake with zero canary failures (CAL-16 baseline data); (e) kernel produces a chained per-run log that itself passes the M0 corruption drills.
Discharges: F-006 (logic), F-014, F-018 (E0 built), F-025 (thresholds seeded), F-028 (budget scaffolding), D-013, D-014, D-019.
Must NOT contain: RealisticFillModel (M2), any child beyond a test stub, any live connection. *Fence: the temptation to "just try a strategy" before P1 is green is how zero-drift dies.*

**M2 — Risk, money, realistic fills, first children, shadow seam**
Scope: risk sizing (ADAPT Titan math) + §2.6 ledger + 11-limit stack + breakers (incl. F-024 shell) + viability gate; **double-entry money engine** (chart of accounts, posting rules, marks, waterfall, invariants I1–I10 at-write, P11–P14) wired into the kernel's SimAccount; `RealisticFillModel` per P4 §4 (both models selectable); T1 and M2 children implemented against the child ABC with pinned params; signal machine complete (all §2.1 rows incl. hold_applied per §1.1); `book` envelope dimension + shadow fold isolation (P15) — *seam only, no stage machinery*.
Acceptance: (a) C-VIAB regression (the 30%-win-rate example fires the gate); (b) F-005 scenario (6 BE positions, 7th wave rejected on margin/notional); (c) both children produce signals in backtest with balanced books — P11–P14 pass on the run's own log; (d) STA race-storm scenario (100 seeds, exactly one resolution); (e) P15 shadow isolation.
Discharges: D-010, D-011, D-028 (build), D-036, D-037, F-001 (machine), F-003 (gate), F-005, F-013 (statistic computable), F-019, F-022, F-024, F-036, F-040.
Must NOT contain: **any G1 verdict** (controls don't exist yet — constitution rule); any broker adapter; Stage-L arming. *Fence: an "informal" G1 run here becomes an anchor nobody admits to.*

**M3 — The constitution: gate controls, then the first admissible G1**
Scope: gate-control suite complete (NC-1…5, PC-1/2 specimen children on the fixture lake slice; C-VIAB, C-AUDIT w/ 6 planted errors, C-CUS, C-MC, C-SIM, C-CELL, C-FEAT, C-SHDW; admissibility preconditions in the report generator; control-edit governance header); CUSUM implementation per CAL-08 with per-child ARL simulation; then Stage-R/G1 runs for T1 and TC-2 (TC-2's features are trivial additions).
Acceptance: (a) every control row green nightly; specimen-verdict-change merge-block demonstrated (mutate a threshold in a branch, watch CI refuse); (b) first admissible G1 report for T1 exists with both fill models, cost waterfall, plateau grid, run-card complete; (c) NC-4 asserts *refusal*, not failure.
Discharges: D-050, D-003 (first execution), Pass-1 T7, D-001 end-to-end.
Must NOT contain: live/demo connections; roster beyond T1/TC-2/M2/M1-in-research. *Fence: growing the roster before the pipeline can kill a bad child produces unkillable children.*
**Honest note (Auditor):** if T1 *fails* Stage-R here, the project pauses at M3 and the roster question reopens before another line of broker code is written — see §6 abandon criteria. Building M4–M5 first and discovering the flagship child is dead after would be sunk-cost machinery.

**M4 — Broker reality: adapter, OMS, reconciliation, execution intelligence, Sentinel**
Scope: bridge_win extensions (/deals_since, /deals_range, /balance_ops, /specs_full incl. swap fields, /statement, clock endpoint); mt5_bridge client (BORROW); discovery + capability tagging + account-mode gate (F-002 behaviors both modes, reduce-only guard); OMS (§2.2 machine, client_key, SENT_UNKNOWN probe/dedup); reconciler (state §3.3 + money daily §5.2 + quarantine); execution intelligence (mechanism matrix, spread gate, news/rollover/storm gates + queues, freeze guard, OCO manager, weekend policies, SL-in-request); spec-diff analyzer; swap accrual + verification (per §1.8 layering); Sentinel process + its three chaos rows; chaos harness live (docker-compose + toxiproxy, 25-seed kill-9 suite).
Acceptance: (a) chaos suite 25/25 incl. randomized injection points, stop-verified, zero duplicates, ledger==simbroker exact; (b) C-EXEC: every P4 §1 scenario row asserts its (F) behavior (news blowout w/ resting orders, rollover burst, Sunday gap both policies, storm-during-exit, stops_level widen, freeze-band trail, netting reduce-only race, OCO double-fill both orderings + reconnect-discovered, disconnect mid-send w/ SL verified); (c) Sentinel drills (core-kill alarm ≤ 3 min; commanded flatten reconciles as `closed_by=sentinel`, zero unexplained diffs; sentinel-death detected); (d) against a real demo account: discovery completes, one full order round-trip, daily money reconcile CLEAN.
Discharges: F-002 (behaviors), F-007, F-010, F-011 (execution arms), F-012 (live capture), F-020/F-023 (money), F-021, F-029, F-031 (channel), F-032, F-033, D-019–D-028, D-038–D-041, D-048, F-042.
Must NOT contain: interfaces beyond `/status`-grade stubs; any real-money account; A/B experiments. *Fence: interfaces built against a fantasy adapter get rebuilt; adapter first.*

**M5 — Humans: modes, Telegram, GUI**
Scope: interface process (:8790) + command channel HMAC + roles/tickets/auth; Telegram (delivery-ack ladder, edit-in-place lifecycle, command grammar, quiet hours, digests); GUI seven pages + WS contract (snapshot/delta/resume/heartbeat) + confirmation cards (field order, partial-fill mutation, version pinning, hold, race truth, child-health strip) + graduation panel + overrides drawer + binding-order display + journal waterfalls; fake-controller dev harness regenerated.
Acceptance: (a) real-transport guard tests (uvicorn/websockets dep pin, nginx-path WS smoke, Telegram mock round-trip over real HTTP); (b) F-001/F-008/F-009 interface scenarios: partial-fill card mutation precedes resolution in the journal; unacked-card timeout degrades and *renders* the degrade; race-loser text verbatim; (c) kill-path throttle-exemption pinned test; (d) 3-second card test on phone-sized mock walked by both trader seats; (e) STALE_CARD approve → re-render flow.
Discharges: F-001 (display), F-008 (UX), F-009 (full), F-026, F-031 (interface), F-039, D-029–D-035, D-046, hold_applied (D-030) live.
Must NOT contain: any control that edits entry logic live; optimistic outcome rendering; manual-ticket anything (graveyard D-052). *Fence: the graveyard is a fence.*

**M6 — Validation operations: G2 machinery, shadow stage, calibration data**
Scope: shadow stage full machinery (stage transitions, virtual-equity ledger, hatched displays, guardrails G1–G4); nightly kernel-parity (shadow/live signals vs backtest on same bars); demo infra soak per CAL-23; monthly statement recon + month-close artifact; Threshold Lab nightly sweeps live on CAL-01/CAL-11 grids; 60-demo-day accumulation for CAL-04/CAL-05; simulator drift check operating; T1 (+TC-2) through redefined G2.
Acceptance: (a) T1 G2 exit: ≥ 4-week shadow soak with zero parity diffs + CAL-23 demo soak criteria met; (b) 30 consecutive daily money reconciles CLEAN on demo; (c) backup restore-verify green 30/30 nights; (d) first Lab artifacts render with CIs and badges; (e) CAL-04/05 tolerances re-fit from clean-day distributions and planted-error suite still 100% detected.
Discharges: D-043, D-044, F-030 fully operational, CAL-04/05/23 procedures executed.
Must NOT contain: real money; graduation of any child past G2 without its dossier-named measurements (G4: M1's adverse selection etc.). 
**Calendar honesty:** M6 is bounded by wall-clock, not effort — ≥ 60 demo days for tolerance calibration is irreducible. Use the time to run M-family children in shadow/research and accumulate Lab data.

**M7 — First real money: G3 probation + hardening (B6 opens)**
Scope: live account (per H1/H2/H11 decisions); T1 at 25% risk ≥ 4 weeks (05 §B4 G3 unchanged — it survives the G2 redefinition untouched); execution-profile cells accumulate; F-024 breaker armed on the real portfolio artifact; first broker scorecard month; A/B experiments become legal (post-probation children only); CAL-06 bands re-fit from first 3 live months; Sentinel drill re-run against the live terminal (read-only paths) before first live week.
Acceptance: (a) G3 exit criteria: ≥ 4 weeks, no anomaly flags, no CUSUM ACTION, money recon CLEAN throughout, realized execution costs within CAL-06 bands; (b) risk scales to 100% only on (a); (c) zero duplicate executions (the counter renders red at any value).
Discharges: D-047 (first legal use), D-049 (first scorecard), CAL-06/CAL-13/CAL-20 procedures begin.
Must NOT contain: more than one child entering G3 simultaneously (00's "one child graduates at a time" survives); any Lab-driven threshold change inside the first quarter.

**M8 — Steady state: roster growth + governance cadence**
Scope: children promoted per Pass-2 priority through the shadow queue (M2 next, then M1 gated on its adverse-selection measurement, M4 gated on open-spread decay curves); quarterly Lab reviews (per H10 cadence); quarterly re-validation (05 §D6); annual CAL-02 recalibration; scorecard verdicts; Antibody-style periodic review of the control suite itself.
Acceptance: perpetual — the CI gates, control suite, and register *are* the acceptance criteria from here on.

### 4.3 The honest critical path and where a solo developer's time actually goes

The critical path is **M0 → M1 → M2 → M3 → M4 → M6 → M7**: log integrity → feature/kernel parity → money+risk engines → controls+first G1 → broker reality → calendar-bound calibration → probation. M5 (interfaces) is off the critical path until M6 (G2 needs delivery-acks only in hybrid; the first children can run auto on demo with Telegram-only stubs) — but M5 cannot slip past M6's end because quiet-hours and confirmation contracts gate hybrid operation.

Effort distribution (board estimate, hypothesis, for a competent solo developer): **testing/drills/controls ≈ 30%** (the pyramid, chaos harness, and gate controls are the majority of what makes this design different from the average bot), **execution/broker/reconciliation ≈ 25%**, **core/event-log/feature engine ≈ 20%**, **interfaces ≈ 15%**, **strategy code ≈ <10%** — the children are deliberately tiny; the system around them is the product. Wall-clock is dominated at the back end by irreducible calendar gates: ≥ 60 demo days (M6) + ≥ 4 shadow weeks (G2) + ≥ 4 probation weeks (G3). Nothing in the build order can compress those; only overlap them (start demo data accumulation the day M4's acceptance passes).

---

## §5 The human decision sheet

*The owner reads this section first. Each item: the question, why the board could not default it, the options with the matrix of record, the board's recommendation and vote, and what blocks until decided.*

### H1 — F-002: account posture and netting default (matrices: P3 §8.7 · P4 §1.7 · P6 §1.4 · consolidated below)

**Question.** (i) Should you seek a hedging account (posture)? (ii) Ratify the shipped default `netting_policy: DEGRADED` for netting accounts (vs `REFUSE`).
**Why not defaultable.** Account choice is a product/jurisdiction decision — some operators' only option is netting; "degraded" trades away concurrent children per instrument, which changes what the roster can express. The board can recommend; it cannot know your broker constraints.

| Criterion | A: require hedging | B: netting degraded (one child/instrument) | C: synthetic tranches |
|---|---|---|---|
| Broker-side stop integrity (02§A5) | native | native (single owner) | **violated on link loss** |
| Child attribution | full | full (by restriction) | full until crash |
| Concurrent children per instrument | yes | **no** | yes |
| Books reconcile per-deal (P6 addition) | native-exact | trivially exact | needs full translation machinery |
| Operator reach | excludes netting-only | includes all | includes all |
| New failure modes | none | reduce-only guard (small) | high, correlated with outages |

**Recommendation:** posture A where you have the choice (open a hedging account); shipped behavior = auto-engage B on netting with one-time acknowledgment; C rejected for v1 **10–0**. Matrix votes: B-as-default carried across three passes; P8 harmonization unanimous.
**Blocks until decided:** nothing before M4 (both behaviors ship); the *account you open* blocks M7.

### H2 — F-016: platform topology (matrix: P3 §8.1)

**Question.** (a) all-Windows VPS vs (b) Linux core + Windows MT5 bridge over WireGuard.
**Why not defaultable.** ~$25–40/mo vs ~$40–70/mo, two boxes to administer vs one, and your own ops comfort — cost and preference are yours.
**Recommendation: (b)**, because every architectural commitment (systemd recovery, chaos-CI parity, sole-writer SQLite on ext4, off-box backup) assumes Linux-grade ops, and the bridge is deployed prior art in this repo. Infra seat's cost objection stands in the matrix. Board: 9–1 shape (Infra noting cost).
**Blocks until decided:** M4 provisioning (the code is topology-agnostic behind the adapter; the *deployment* needs the answer).

### H3 — Sentinel auto-flatten arming (P7 §2.5)

**Question.** Arm `sentinel.autoflatten` (deadman stale > 15 min AND naked positions > 0 ⇒ flatten without a human), or keep alert-only + operator-commanded flatten?
**Why not defaultable.** This is a loaded gun wired to a heartbeat (Auditor): a false trigger flattens a healthy book at market cost; *not* arming it means a dead core + dead operator phone = positions ride on broker stops alone. The trade-off is your sleep schedule and risk temperament.
**Recommendation:** ship **OFF** (board-adopted); revisit after one clean quarter of Sentinel drills and ≥ 1 real deadman event handled manually. Vote: adopted as design condition 9–1 (BE dissenting on the Sentinel itself).
**Blocks until decided:** nothing — OFF is safe-by-omission; the arming question simply stays open on this sheet.

### H4 — `accounting.tax_lot_policy` (P6 §1.4/§7.2)

**Question.** FIFO or specific-lot for the tax-view (Book T) exports.
**Why not defaultable.** It is a jurisdiction/accountant decision; a silent default would put words in your accountant's mouth (P6's "no silent default" rule).
**Recommendation:** none — ask your accountant; the GUI prompt explains both. Also decide the **pre-registration policy for expected balance ops** (deposits/withdrawals you plan — pre-registered ops auto-accept instead of raising `BALANCE_OP_UNSEEN` CRITICALs).
**Blocks until decided:** tax exports only (trading is unaffected; exports refuse to run).

### H5 — Quiet-hours confirmation default ratification (P5 §2.5)

**Question.** Ratify per-child default `{deliver: silent, timeout_action: unchanged}` — i.e., overnight, hybrid children with `timeout: execute` will execute without waking you, with a mandatory eyes-open notice at child setup.
**Why not defaultable.** Both alternatives are mode-contract violations from someone's viewpoint (Swing: "auto with extra steps"; Day: "manual-overnight nobody asked for"). The board built the honest middle; the operator must own it because it governs what happens while they sleep.
**Recommendation:** ratify as shipped (unanimous after wording, P5 §8-4). **Blocks:** first overnight hybrid operation (M6/M7).

### H6 — Graduation thresholds ratification (P5 §6.4, CAL-09)

**Question.** Ratify starting values: ≥ 30 human decisions and |decision-value| < 0.03 R/trade (with CAL-09's CI-based per-child flexing) as the evidence bar displayed for hybrid→auto graduation.
**Why not defaultable.** These numbers gate how quickly *you* delegate supervision to the machine — a personal risk-governance constant, not an engineering one.
**Recommendation:** ratify; CAL-09 will replace "30" with a CI-derived per-child n in [20, 60]. **Blocks:** nothing (display-only until you act on it).

### H7 — CAL-01 viability starting pair (P7 §4)

**Question.** Ratify disable < 1.5 / re-enable ≥ 1.8 (hysteresis) as the starting viability gate, noting P8 §1.9 made this pair govern every child (dossier-local pairs superseded).
**Why not defaultable.** This bar decides which children are allowed to trade *your* money at marginal economics; P2's own worked numbers put T1-on-STD-pricing at 1.1–1.3 — i.e., **at these settings, several children only trade on RAW-tier pricing** (see H11). The bar and the broker choice are one decision.
**Recommendation:** ratify 1.5/1.8 (QNT+AUD sign-off row); first Lab review may move it with evidence. **Blocks:** first G1 verdict consumes it (M3).

### H8 — CAL-02 gap-k starting values (P7 §4)

**Question.** Ratify k: fx major 1.3 · fx cross 1.5 · metal 2.0 · index CFD 3.0 · crypto 1.0/1.5 — the multipliers that shrink your weekend book.
**Why not defaultable.** They directly cap how much trend exposure survives a Friday; too low understates tail risk, too high forfeits the trend sleeve's weekend edge. Risk appetite is the operator's.
**Recommendation:** ratify (SWG+AUD sign-off); annual recalibration from the lake + live gap tags. **Blocks:** M2 ledger config.

### H9 — CAL-08 CUSUM parameters (P7 §4)

**Question.** Ratify κ=0.5, WARN h=2.5, ACTION h=4.0 (sustain 2), ARL₀ ≥ 40/200, ARL₁ ≤ 8 as the edge-decay alarm's operating characteristics.
**Why not defaultable.** This sets how fast you find out an edge died vs how often you get false alarms — the operator lives with both error rates.
**Recommendation:** ratify (QNT sign-off; per-child simulation calibration before Stage-L arms regardless). **Blocks:** Stage-L arming (M6).

### H10 — Threshold Lab quarterly cadence (P7 §1.2/§6-3)

**Question.** Ratify: threshold changes rate-limited to one per item per quarter absent CRITICAL, each citing a sweep artifact. The Auditor voted No on the Lab partly to force this ratification.
**Why not defaultable.** The cadence is the governor on the garden-of-forking-paths risk; only the human whose money is exposed can set how often they allow themselves to be tempted.
**Recommendation:** ratify quarterly (8–2 vote of record). **Blocks:** first Lab-driven change (not before M7+1 quarter anyway).

### H11 — Broker tier selection (implied by P2 throughout; surfaced here)

**Question.** Open a RAW-spread + commission account (recommended) or a standard-markup account?
**Why not defaultable.** It is a real-world account decision with KYC/jurisdiction constraints — but the board's dossiers make its consequence explicit: **M1, MC-1, and M4 are RAW-only children; T2/T4/M3 are marginal on STD; on a standard-markup feed the deployable roster is approximately T1 + TC-2 + M2.** The viability gate will enforce this honestly either way — but you should choose the tier knowing it chooses your roster.
**Recommendation:** RAW-tier, hedging-mode (with H1), demo first (the same demo broker should be the G2/G3 broker — switching brokers between gates invalidates execution-profile continuity; P4 §4.9-6).
**Blocks:** M6 demo account opening; M7 live account.

**Sheet summary: 11 items. Immediately blocking the build: none before M3 (H7/H8 ratifications are one sitting). Blocking first live money: H1, H2, H11. Safe-by-omission: H3, H4, H10.**

---

## §6 Risk register — the summit's honest close

**R-1 · The roster is ~2.3 bets, and one of them carries the house.** (P2 §6.1) Eight-plus children decompose to a trend/TSMOM factor, a reversion-liquidity factor, and session-timing residual; N_eff ≈ 2.3 (hypothesis). The E1 core (TSMOM, vol clustering) carries the roster; half the remaining evidence base is pre-2010 published material with documented decay. **The honest base case for bad years: if TSMOM is in one of its normal multi-year droughts, expected return ≈ the M-family's marginal viability ≈ zero.** The dashboard prints N_eff on page one by board vote precisely so this is never forgotten.

**R-2 · Regime engine as common mode.** Every activation and the family arbitration hang on one rule-based labeler. Systematic misclassification correlates the whole book instantly. Mitigants: E0 hysteresis/dwell, regime-attribution monitoring, CAL-15 plateau study. Residual risk accepted and printed.

**R-3 · The fill model is now inside the evidence chain.** Shadow-stage G2 evidence and Lab counterfactuals both lean on `RealisticFillModel`; its known blind spots (no queue model, B-book behavioral shifts, marginally-calibrated news correlations, tails beyond data — P4 §4.9) are stated, and the only bound is the monthly drift check (CAL-06) plus the both-models rule. A subtly optimistic model flatters shadow children *and* threshold sweeps in the same direction. This is the summit's largest epistemic concentration; the board accepted it knowingly in the 9–1 shadow vote.

**R-4 · Cost-wedge fragility.** Most of the roster's worked viabilities sit between 0.6 and 1.7 — the entire enterprise lives inside the spread between edge and cost, and the broker sets the cost. A 0.3-pip markup change kills children (M1's dossier says so verbatim). Mitigants: viability gate with hysteresis, scorecard, per-cell measurement. Residual: the broker can always reprice faster than a quarterly Lab cadence reacts.

**R-5 · Operational single points.** One broker, one terminal, one bridge hop, one operator. The Sentinel removes the *stopless-book-during-total-death* tail; SL-in-request removes the stopless-fill window; nothing removes: solo-operator bus factor (nobody else can run, audit, or wind down the system), Telegram as the dominant ops channel (mitigated by the sentinel's independent token + dead-man's escalation, not eliminated), and single-VPS-pair infrastructure. Warm standby was rejected for good reasons (D-052); the accepted consequence is minutes-scale RTO forever.

**R-6 · Calibration debt is real debt.** 23 register rows are hypotheses with procedures. Until M6/M7 execute those procedures, every tolerance, k-factor, boundary, and band is a documented guess. The system is *honest* from day one but only becomes *calibrated* after ~60 demo days + 3 live months. Trading real money at M7 means trading on partially calibrated alarms — at 25% risk, by design, for exactly this reason.

**R-7 · Slow falsification at the top of the roster.** TC-2 (and T3 if built) cannot be live-falsified on any useful horizon (20-trade blocks ≈ years); the board monitors them against the published effect class instead — which means the roster's ballast is epistemically anchored *outside* our own telemetry. Accepted with eyes open (P2 §5.1).

**R-8 · Deferred macro-factor blindness.** E3 (risk-on/off composite) is deferred; the static macro-factor caps (limit #6) close the worst F-017 hole, but cross-asset sympathy moves inside the caps remain unmodeled in v1. Documented as accepted (P2 §6.4-2).

**R-9 · Spec mass vs solo velocity.** This summit produced an unusually complete spec; the corresponding risk is a half-built system that has M0–M2's rigor and M4's ambition but no M3 controls — the fences in §4 exist to make partial states safe (nothing trades before controls; nothing goes live before drills), but the *schedule* risk of a solo build of this scope is unbounded and unowned by any mitigation in this document.

### The abandonment statement (consistent with P2 falsification criteria; board-unanimous)

We stop — not tune, stop — when any of the following holds:
1. **Research kill:** T1 **and** TC-2 both fail their pre-registered Stage-R criteria on the full-cost, swap-inclusive, both-fill-model backtests (P2 §2.1f/§5.1). The E1 carrier is the load-bearing wall; if the two purest expressions of the best-documented anomaly class in the roster cannot clear a PF ≥ 1.2–1.3 bar at our costs, no amount of M-family marginalia rescues the project, and the pre-registration discipline forbids re-tuning them until they pass. Trigger point: end of M3.
2. **Live kill:** across ≥ 2 consecutive quarters of G3+/full operation, portfolio net expectancy after realized costs ≤ 0 **while** the money reconciliation is CLEAN and the CAL-06 drift check confirms the cost model matches reality (i.e., the losses are real and correctly measured, not an accounting or model artifact), **and** every remaining live child has independently tripped its Stage-L ACTION boundary. That conjunction means the edges are gone and we know our instruments are telling the truth about it — the system worked; the market moved on.
3. **Integrity kill:** recurring `DUPLICATE_EXECUTION`, `UNKNOWN_LEDGER_LINE`, or unattributed-bucket CRITICALs that survive two remediation cycles — a system that cannot keep its books exact has no license to trade regardless of edge (Auditor's standing condition, adopted).
4. **Honesty-machinery kill:** the gate-control suite (D-050) catches the *pipeline itself* certifying a planted lie post-remediation — if the machinery that checks the checkers fails twice, every downstream verdict is void and the project halts for re-audit before any further trading.

What does **not** trigger abandonment, and is pre-committed here to prevent panic-quitting the plan: multi-year trend droughts (they are the E1 profile, priced in R-1), individual M-family child deaths (the gate exists to kill them), single bad quarters inside CUSUM boundaries, and drawdowns within the breaker/budget envelope.

---

## §7 Board sign-off

**Chief Systems Architect.** I got the architecture I argued for: one log, one writer, one transition owner, one kernel for live and backtest, and a shadow stage that turns calendar time into evidence. I conceded the embedded control server (my Titan-derived instinct) to the process split, and I accept that the sole-writer principle cost us warm standby forever. My warning: the design's integrity is load-bearing on M0/M1 discipline — if the first two milestones are rushed, every downstream guarantee (parity, replay, chain) becomes decorative, and nobody will notice until reconciliation does.

**Senior Quant Researcher.** I got pre-registration, block statistics with real operating characteristics, controls for every judge, and a calibration register instead of folklore constants. I conceded the HMM and the broad session-regime model — the auditable rule engine won, correctly. My warning: N_eff ≈ 2.3 is the truest number in seven documents; do not let the roster's headcount, the dashboard's green ribbons, or a good trend year convince you that you own more than roughly two bets, one of which spends years asleep.

**Master Trading Strategist.** I got dossiers that treat every child as a hypothesis with a named loser, and a card that finally shows the child's live record at the decision moment. I conceded T3's demotion, the short legs, weekend breakout stops, and my snooze objection — each to better evidence than mine. My warning: the machinery is now so good at killing children that the residual risk is sterility — a pipeline that never promotes anything because every marginal child dies at CAL-01's bar. Watch the PC-2 control: the gray zone must stay a gray zone, not become a wall.

**Principal Algo-Bot Developer.** I got SL-in-request, the intent-persisted attribution spine, the reduce-only guard, and an OMS whose unknown-outcome path is designed instead of discovered. I conceded my manual cockpit — the board was right that it builds a button for the documented anti-pattern. My warning: the EA/bridge/terminal layer will produce behaviors no spec anticipated — brokers are adversarial middleware; when reality and this document disagree at M4, write the scenario into C-EXEC *first* and fix second, or the scenario library rots into history.

**Networking & Infrastructure Specialist.** I got the owned time service, the WireGuard perimeter, measured broker offsets, and the Sentinel — the one lever that outlives the stack. I conceded the second VPS cost onto the matrix and lost my 90 s drift threshold to Pass 4's stricter number, correctly. My warning: the bridge/terminal box is the least observable component and holds the credentials; treat every Windows-side anomaly (clock, restart, update) as a trading event, not an IT event — the calendar service can only compensate for the drift it can measure.

**A-Tier Auditor & Accountant.** I got double-entry in integers, two truths per money number, planted-lie controls with a constitution rule, and an abandonment statement with my integrity-kill clause in it. I conceded the Threshold Lab's existence against my forking-paths vote — with the quarterly ratification now on the human sheet, which is where I wanted the temptation governed. My warning: every tolerance in this system is a place a small theft can hide; the trend guard exists because per-line passes are not innocence. Read the 4400 and 4900 balances monthly like they are accusations, because they are.

**Profitable Retail Day Trader/Scalper.** I got the news gates with teeth, the 1.5× release rule, open-window quarantines, the storm detector, and honest RAW-only labels on the children I'd actually trade. I conceded price-first cards and my shadow No vote — G4 protects the scalps from model flattery, which was my whole point. My warning: the open-spread decay curve measurement gates M4-the-child for a reason; if anyone ships an open-drive fade before that curve exists on your actual broker, they have reinvented the exact cost-blindness this project was chartered to kill.

**Profitable Swing Trader.** I got gap-stressed risk as a first-class number, k-budgets that bind on Fridays, swap books that verify against the broker nightly, and weekend pending-order sanity. I conceded my swap-dodge scheduler to the front-door rule — the measurement survives, which is what mattered. My warning: the weekend is where this system's honesty is tested — every Friday hold is an unlabeled bet on the gap distribution, and CAL-02's k values are hypotheses until enough Mondays have voted. Do not let a quiet year lower them.

**Frontend Architect.** I got a confirmation surface that never lies about control — race truth, no optimistic outcomes, version-pinned approvals, fail-closed rendering — and interfaces demoted to renderers of core truth. I conceded my own optimistic-rendering draft and the flight simulator. My warning: the operator's mental model *is* a system component; every place the UI simplifies (silent quiet-hours executes, held signals, analytics-grade counterfactuals), the setup notices and captions are the only thing standing between design intent and 3 a.m. misunderstanding. Never let copy edits weaken them — the banned-phrase list is a safety device, not style.

**Backend Architect.** I got total single-writer ownership, the HMAC command channel, typed schemas with upcasters, and a WS contract with resume semantics instead of vibes. I conceded the warm standby (the arithmetic was against me) and hold my Sentinel dissent on record while accepting its conditions — the drill suite proving GHOST_CLOSED adoption is what makes the second actor tolerable. My warning: schema versioning is the quiet long game; the first careless payload change that skips an upcaster orphans every archived month. Treat `schema_version` bumps with the same ceremony as money code, because replay *is* money code.

---

*End of Pass 8, and of the summit. 56 decisions (49 final), 42 findings closed or on the human sheet, 23 calibration rows with procedures, 9 milestones with fences, 11 human decisions, 4 abandonment triggers. Every number in this document set is labeled; the ones that matter most are still hypotheses — that is not a weakness of the plan, it is the plan.*
