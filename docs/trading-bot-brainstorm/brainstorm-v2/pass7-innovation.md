# PASS 7 — INNOVATION ROUND + CALIBRATION & GATE-CONTROL SWEEP

**Chairs:** rotating — §1–§3 open floor (each seat chairs its own proposal); §4–§5 co-chaired by Senior Quant Researcher + A-Tier Auditor & Accountant (the two seats every earlier pass named as calibration owners).
**Inputs (read in full):** `00-overview.md`–`05-…`, `pass1-audit.md` (F-001…F-039), `pass2-research.md`, `pass3-systems.md`, `pass4-execution.md`, `pass5-interfaces.md`, `pass6-accounting.md`.
**Standing state honored:** F-002 (netting default) and F-016 (topology) remain OPEN-FOR-HUMAN with the pass3 §8 matrices — nothing below assumes either answer. Pass4's SL-in-entry-request rule and the safety-modify-class rule are treated as non-negotiable. Pass5's `confirm.hold_applied` amendment remains pending Pass-8 adoption (nothing here depends on it). Pass6's admissibility rule — the backtester's SimAccount must emit real posting streams or G1 evidence is inadmissible — is adopted as a gate-control precondition (§5.1).
**Labeling:** every number is **(measured)**, **(literature-informed)**, or **(hypothesis)**, per the Pass-2 honesty rules. Build-order milestones cite 00 §Build-order steps **B1–B5**, plus **B6** = post-G3 hardening/scale-up (the summit's working extension; Pass 8 formalizes).

**Innovation-round rules applied (from the charter):** one proposal per seat; each states what is genuinely NEW versus passes 1–6 with citations; each is checked against the locked requirements — especially **no online self-modification of entry logic** (the learning loop may adjust execution/costs/throttles/on-off only); the Auditor red-teams every winner; majority YES ⇒ full design section (§2); losers get one graveyard line (§3).

---

## §1 Innovation proposals — ten seats, ten pitches, ten votes

Vote key: seat abbreviations ARCH (Chief Systems Architect), QNT (Senior Quant Researcher), STR (Master Trading Strategist), DEV (Principal Algo-Bot Developer), NET (Networking & Infrastructure), AUD (A-Tier Auditor & Accountant), DAY (Retail Day Trader/Scalper), SWG (Swing Trader), FE (Frontend Architect), BE (Backend Architect).

### 1.1 ARCH — Shadow-mode children: paper children inside the live engine

**Pitch (ARCH):** "The most expensive thing we own is calendar time on the G2/G3 clock. A demo account buys forward-testing at the cost of a second venue whose fills lie (F-030) and whose infrastructure differs from production. I propose **shadow stage**: candidate children run inside the *live* core — live ticks, live features, live calendar, live risk-engine code paths — but their orders route to an in-process `RealisticFillModel` book instead of the broker. Zero market cost, zero second venue, production-identical code path, and the forward test starts the day the child passes G1 instead of the day a demo slot frees up."

**What's genuinely new vs passes 1–6:** Pass 2 §1.4/pass1 F-030 define G2 as *demo-account* soak reframed as logic-parity; pass3 §5.6 replays a demo day through the backtest kernel *offline*; pass4 §6-4 mentions one narrow "shadow accounting" for the cancelled weekend-stop cohort. Nobody specified paper children executing *forward, continuously, inside the live process* against the production feed with the pass4 fill model. This claims and develops charter example #1.

**Sketch:** `child.stage ∈ {research, shadow, live}` — a **deployment stage, not a fourth mode** (the locked three-modes-per-child requirement applies to `live` children only; shadow children are always auto-resolved, no cards). New envelope dimension `book ∈ {live, shadow}` on `signal.*`, `exec.*`, `position.*`, `ledger.*` events; single log, single writer (pass3 §1.4 untouched). SimBroker instance mounted in-core behind the same `BrokerAdapter` protocol (pass3 §5.2 seam); shadow ledger = a second `LedgerSnapshot` fold filtered on `book=shadow` (limits exercised, never binding on live). Full design §2.1. **Cost: M.**

**Objection (DAY):** "Paper fills at London open are exactly where the fill model is most wrong — shadow forward-tests the model, not the market." **Response (ARCH+QNT):** correct, and priced: shadow evidence is *logic-parity + model-consistency* evidence (the F-030 reframing, strengthened), never execution evidence; G3 live probation still exists and still gates risk scale-up; and the monthly simulator-drift check (pass4 §4.8-5) bounds how wrong the model is allowed to be while shadow evidence is admissible.

**Locked-requirement check:** no entry-logic modification (shadow children are frozen versions); exits automated (shadow book uses identical management code); kill paths unaffected (shadow book has none to need).

**VOTE — 9 YES / 1 NO → WINNER.** ARCH Y (production-identical forward test is the cheapest honest evidence we can buy) · QNT Y (turns G2 calendar time into data on day one; conditional on shadow evidence being labeled model-grade) · STR Y (candidates queue in shadow instead of rotting in research) · DEV Y (one adapter seam already exists; SimBroker is built for §5 anyway) · NET Y (kills the second-venue ops burden of long demo soaks) · AUD Y (conditional: shadow numbers carry the pass6 §8-10 analytics badge everywhere, and shadow trades never count toward any live-trade minimum) · DAY N (worried shadow green-lights model-flattered scalps; wants M-family excluded — recorded, addressed in §2.1 guardrail G4) · SWG Y (lets slow children accumulate blocks years earlier) · FE Y (one more `book` filter, reuses every existing view) · BE Y (log dimension is cheap; loop budget must be enforced — condition accepted).

### 1.2 QNT — The Threshold Lab: counterfactual calibration of gates on live decisions

**Pitch (QNT):** "Pass 1 voided the viability threshold; passes 2–6 left this pass a register of ~20 numbers labeled hypothesis. The classic failure is calibrating them once, by argument, in a document — this document — and never again. I propose the **Threshold Lab**: every gate decision already logs its inputs (viability evaluations, queue holds/releases, CUSUM updates, breaker checks are all events); a nightly job replays each decision function under a **pre-registered grid** of alternative thresholds and scores the counterfactual — trades forgone and their modeled outcome, false alarms avoided, disable-days incurred. The calibration register (§4) stops being a table of guesses and becomes a table of measured trade-off curves that a human re-reads quarterly."

**What's new vs 1–6:** pass1 F-003/F-013/F-029 and pass3 §10, pass4 §7, pass6 §9 all *defer* calibration here but specify no calibration *machinery* — only per-item hand procedures. The Lab is the machinery: one harness, all registered thresholds, counterfactuals from the same kernel-replay + fill-model stack (pass3 §5.6, pass4 §4).

**Sketch:** `calib.sweep` nightly job; per register item: decision-event query → replay under grid → artifact `calib/<item>/<date>.parquet` (grid point × {decisions flipped, modeled ΔR with CI, alarm counts}); GUI Research page gains a Calibration tab reading these artifacts. Threshold *changes* remain ordinary config events — human-applied, schema-validated, rate-limited (§2.2 guardrails). **Cost: M** (harness S once shadow/replay infra exists; the grid definitions are the work).

**Objection (AUD):** "A nightly machine that shows the operator 'threshold 1.3 would have made +4R' is a garden of forking paths with a UI. This is how honesty gates get quietly loosened." **Response (QNT):** three teeth, adopted as conditions — grids pre-registered per item and frozen in the register (§4); counterfactual ΔR always displayed with bootstrap CI and the analytics-grade badge; and threshold changes are **rate-limited to one per item per quarter** absent a CRITICAL, each change event citing the sweep artifact that justified it. Loosening a gate is possible — silently or casually loosening one is not.

**Locked-requirement check:** thresholds in scope are exactly the allowed class (execution/costs/throttles/on-off); entry logic and child parameters are **out of scope by construction** (the Lab refuses grids over strategy params — that path is a new child version through G1).

**VOTE — 8 YES / 2 NO → WINNER.** ARCH Y (one harness instead of twenty ad-hoc studies) · QNT Y (proposer) · STR Y (finally answers "is 1.5 the right viability bar" with data) · DEV Y (decision events already carry their inputs; replay is cheap) · NET Y (batch job, off-loop, no live surface) · AUD N (residual forking-paths risk even with rails; wants Pass-8 to ratify the quarterly cadence — recorded) · DAY Y (queue-release threshold finally gets its expiry-vs-cost curve) · SWG Y (gap-k gets annual evidence instead of anecdote) · FE Y (artifacts render on existing run-card components) · BE N (worried about sweep-job sprawl; conditional on artifact retention caps — accepted, 90-day artifact retention, summaries forever).

### 1.3 STR — Expectation-context confirmation cards (the child's live record, in the F-013 frame)

**Pitch (STR):** "The card asks a human to veto anomalies (pass5 §1.1) but hides the one context that most changes the prior: *how this child has actually been doing*. An operator approving a T2 signal deserves to know T2 is one WARN block into a drawdown, or that it's four green blocks deep. I propose a **child-health strip** on every card: viability number and state, the last four block-ribbon cells, CUSUM state, live sample size — the same block-frame statistics pass5 §5.1 already renders, frozen into the card at render time." This develops charter example #3 — but deliberately *not* as a per-trade expectation cone, which pass5 banned for F-013 reasons; the strip is the block-frame version of that idea.

**What's new vs 1–6:** pass5 §1.2 card fields carry signal-local context (why/against/risk) plus system AGAINST lines; child-level live performance appears only on the Children page (§4-3). Nothing puts the child's monitored state *in the decision moment*.

**Sketch:** extend `card:json` with a `child_health` block (schema §2.3), populated core-side from the monitoring projection at `confirm.requested`; one added card line + one renderer rule; card_version semantics untouched (health is frozen, not live-updating — a material CUSUM state change mid-window does **not** bump the card; the human decides on render-time truth like every other field). **Cost: S.**

**Objection (QNT):** "Anything that smells like a per-trade cone re-opens the F-013 wound; and humans anchor — a ⚠ cell will veto good signals." **Resolution:** block-frame only (no per-trade numbers, no projections); the pass5 §5.1 caption discipline applies on the card in miniature ("blocks, not trades"); children with < 20 live/shadow trades render `insufficient live sample — G1 expectancy (hypothesis)` instead of an empty ribbon; and the §5.3 decision-value analytics will *measure* whether the strip improves or degrades human filtering — the strip is itself an experiment with a named metric.

**Locked-requirement check:** display only; touches no logic, no thresholds, no timing.

**VOTE — 10 YES / 0 NO → WINNER.** ARCH Y (frozen projection read, zero new state) · QNT Y (block-frame satisfies F-013; measurement condition accepted) · STR Y (proposer) · DEV Y (renderer-only change) · NET Y (no transport impact) · AUD Y (more truth at the decision point, honestly labeled) · DAY Y (this is the context I flip to the Children page for today, under a countdown) · SWG Y (same) · FE Y (one card block, existing ribbon component) · BE Y (schema addition, versioned).

### 1.4 DEV — Randomized execution A/B: causal mechanism selection

**Pitch (DEV):** "Pass 4 §2's adaptive mechanism flips are observational: we compare broker-stop fills against synthetic-stop *simulated shadow costs* and flip on the difference. Observational comparisons of execution mechanisms are confounded by exactly the thing that matters — *which market states each mechanism got used in*. I propose **randomized A/B within a cell**: where two mechanisms are both live-legal and both pre-checked, entry orders in the cell are block-randomized between arms; the per-cell profiles (pass4 §5) then estimate a *causal* cost difference, and the existing flip machinery consumes it with half the sample and none of the confounding." Charter example #2, claimed and developed.

**What's new vs 1–6:** pass4 §2 flips on observational telemetry plus a *simulated* counterfactual for the unused arm; nothing randomizes real order flow, so nothing produces an unconfounded comparison.

**Sketch:** `exec.experiment` config objects (cell, arms, allocation, budget, stop rule); assignment computed deterministically from the run seed + client_key (replayable, pass3 §5.5 discipline); `exec.order_record.experiment{exp_id, arm}`; weekly-block interim analysis; auto-stop and adoption via the *existing* pass4 §2 flip event. Guardrails in §2.4. **Cost: M.**

**Objection (AUD):** "An experiment deliberately routes real money through the arm you believe is worse. That is a cost with no cap in the pitch." **Resolution (adopted as design):** per-experiment worst-case budget — expected inferior-arm excess cost, priced from the current cost model, capped at **2R per experiment and 0.5R per month per cell (hypothesis)**; experiments only on *entry* legs (SL placement is 02§A5 territory, excluded forever); only in cells with n ≥ 50 existing fills so the prior on "worse" is informed. **Objection (QNT):** interim peeking re-imports the F-013 optional-stopping disease into execution. **Resolution:** analysis at weekly block boundaries only, group-sequential spending (O'Brien-Fleming-style bounds, spec §2.4) — the same block discipline the rest of the system lives by.

**Locked-requirement check:** the adjustable surface is mechanism choice — explicitly the allowed learning-loop class; randomization changes *how* an approved entry is executed, never whether/what.

**VOTE — 8 YES / 2 NO → WINNER.** ARCH Y (deterministic assignment keeps replay bit-exact) · QNT Y (causal beats observational; block-bounded analysis satisfies F-013 discipline) · STR N (uneasy paying tuition on live edges this thin; wants experiments barred while a child is on probation — condition adopted, still No on principle) · DEV Y (proposer) · NET Y (no new transport paths) · AUD Y (with the 2R cap and cost-waterfall visibility, tuition is bounded and booked) · DAY Y (finally settles broker-stop vs synthetic on DAX with numbers) · SWG N (my children trade too rarely to ever fill an experiment; cost falls on others — fairness noted, cap answers it) · FE Y (experiment badge on execution dashboard, trivial) · BE Y (config objects + one record field).

### 1.5 NET — The Stop Sentinel: an independent last-resort watchdog beside the terminal

**Pitch (NET):** "Pass 3 §8.4 prints our scariest line: *bridge/terminal down → exits are impossible while down*. Our whole answer is broker-side stops — correct, and single-layered. I propose the **Sentinel**: a ~300-line independent process co-located with the terminal (Windows box under F-016(b); same box as everything under (a)) with exactly two jobs: (1) continuously verify every open position carries a broker-side SL, alarming through its **own** Telegram bot token and its own healthchecks ping when one doesn't or when the core's deadman goes silent; (2) execute a flatten-all on explicit operator command through that independent channel — a kill path that survives the death of the core, the Linux box, and the WireGuard link simultaneously."

**What's new vs 1–6:** pass3 §8.4's dead-man ping detects total death but can *act* on nothing; kill paths (pass5 §2.7) all route through the core. No prior pass gives the operator any lever when the core is gone. This is defense-in-depth on the one guarantee the charter calls non-negotiable ("kill paths always available").

**Sketch:** read-mostly MT5 session (positions/orders enumeration); close-only order permission; no shared state with the core (it reads the broker, the single truth); its closes surface to the core as reconcile `GHOST_CLOSED` events — a path pass3 §3.3 already handles. Full design §2.5. **Cost: M** (small code, but it is safety-critical code and gets chaos-drill coverage).

**Objection (BE):** "A second process that can close positions is a second actor in the money path — we spent pass3 killing multi-writer designs." **Resolution:** the Sentinel writes nothing we own (no DB, no log, no config); it acts only on the broker, whose state the reconciler already treats as truth; its action set is close-only, so the worst bug flattens a book into cash — the same worst case as the human red button it is backstopping. **Objection (AUD):** "Default-on auto-flatten is a loaded gun wired to a heartbeat." **Resolution (adopted):** v1 ships **alert-only + operator-commanded flatten**; any *automatic* flatten policy is operator-armed config, default OFF, with the arming choice on the Pass-8 human decision sheet.

**Locked-requirement check:** strengthens "kill paths always available"; touches no entry logic; its existence never blocks the core's own exits.

**VOTE — 9 YES / 1 NO → WINNER.** ARCH Y (an independent failure domain is the only honest answer to correlated death) · QNT Y (no statistical surface, pure safety) · STR Y (I hold weekend positions; I want a lever that outlives the stack) · DEV Y (close-only MT5 code is small and testable; I've written this twice in production) · NET Y (proposer) · AUD Y (with auto-flatten default OFF and its own drill row) · DAY Y (the 2 a.m. scenario this kills is real) · SWG Y (ditto, Fridays) · FE Y (sentinel status chip in the health strip, read-only) · BE N (maintains the two-actor objection; accepts the vote, asks that the drill suite prove GHOST_CLOSED adoption of sentinel closes — condition adopted).

### 1.6 AUD — Broker scorecard & migration dossier: the ledger prices your broker

**Pitch (AUD):** "Pass 6 built books that decompose every cost; pass 4 built per-cell execution profiles. Nobody yet *adds them up per broker and compares*. I propose the monthly **broker scorecard**: effective spread vs published, slippage quantiles by mechanism × session, storm frequency, swap true-up drift, conversion markup (account 4400 as basis points of converted volume), commission mismatches, trade-channel uptime — composited into one measured number: **cost drag in R/year, per child and total**, against a reference tier. When drag exceeds a threshold and a candidate broker's sampled profile beats the binding cells, the system emits a **migration dossier** — evidence, not action; the human migrates or doesn't." Charter example #4, claimed.

**What's new vs 1–6:** pass4 §1.4 uses storms as "a broker-quality metric" and pass6 trends per-class residuals, but no pass aggregates across dimensions, prices the broker in R, compares brokers, or produces a recommendation artifact.

**Sketch:** `broker.scorecard` monthly event + artifact fed entirely from existing telemetry/ledger cells (zero new capture); candidate-broker evaluation via a demo account on the candidate running discovery + the spread/swap samplers for ≥ 2 weeks — labeled **demo-grade evidence** with the known optimism stated (pass4 §4.9-6). Full design §2.6. **Cost: S** (aggregation + report; the inputs all exist).

**Objection (STR):** "Broker-hopping costs edge too — remapped symbols, new specs, re-run gates, weeks of disruption. A scorecard that nags monthly will churn us." **Resolution:** the dossier includes a **switching-cost line** (re-validation runs, spec re-discovery, historical-data re-verification, estimated downtime) and the recommendation rule requires the measured drag to exceed switching cost amortized over 12 months (hypothesis horizon) before it recommends anything. **Objection (DEV):** demo-account candidate evidence overstates the candidate (pass4 §4.9-6). **Resolution:** dossier prints both numbers with the demo-grade label and applies a candidate haircut (×1.3 on candidate costs, hypothesis) before comparison.

**Locked-requirement check:** produces evidence for a human decision; the bot never migrates itself; nothing adaptive touches trading.

**VOTE — 10 YES / 0 NO → WINNER.** ARCH Y (pure fold over existing events) · QNT Y (the cost wedge is the edge wedge — F-003's point, finally trended per venue) · STR Y (with the switching-cost line, this is decision support not churn fuel) · DEV Y (inputs exist; report job is a weekend) · NET Y (uptime/storm metrics finally have a consumer) · AUD Y (proposer) · DAY Y (RAW-vs-STD stops being folklore, per session, on my fills) · SWG Y (swap drift per broker is real money on month-holds) · FE Y (scorecard page reuses waterfall components) · BE Y (one monthly batch job).

### 1.7 DAY — Manual scalp cockpit: discretionary tickets through the bot's risk engine

**Pitch (DAY):** "I still trade discretionary setups the children don't cover. Today that means a raw terminal beside the bot — unsized, unlogged, unjournaled. Give me a GUI ticket that routes a *manual* entry through the same risk engine, limits, execution intelligence, and journal: my discretion, the bot's discipline."

**What's new vs 1–6:** everything — no pass contemplates operator-originated entries. That is the problem.

**Objections (many):** STR — the charter is a bot with human *veto*, not a brokerage front-end; a second flow of human-originated risk competes for the same budgets and muddies every portfolio number. AUD — attribution catastrophe-in-waiting: manual trades share instruments with children, and on netting accounts (F-002 degraded mode) a manual position *occupies the instrument slot*, silently disabling a child; pass4 §1.7 explicitly documents "don't hand-trade bot symbols" as an operator rule — this proposal builds a button for the anti-pattern. QNT — human-decision analytics (§5.3) are designed around veto decisions; mixing origination poisons them. FE — the cockpit would need its whole own UX safety layer (fat-finger, sizing, confirmation) for a non-goal.

**DEV's partial defense:** a risk-checked manual ticket is safer than the raw terminal the operator will use anyway. **Board synthesis:** true but out of scope — the honest v1 answer to off-system trading is the existing reconciler quarantine path (pass3 §3.3), which already adopts and flags externally-originated positions. Revisit only as a separate product decision post-v1.

**VOTE — 2 YES / 8 NO → GRAVEYARD.** ARCH N (second origination path, first-class scope creep) · QNT N (poisons the decision analytics) · STR N (not this product) · DEV Y (safer than the terminal) · NET N (new attack surface on the command channel) · AUD N (attribution + netting-slot hazards) · DAY Y (proposer) · SWG N (agree with STR) · FE N (large UX safety surface for a non-goal) · BE N (new command class, new invariants, no v1 payoff).

### 1.8 SWG — Swap-dodge exit scheduler: shift exits around triple-swap nights

**Pitch (SWG):** "Pass 6 §2.2 gives us exact swap accrual and the discovered triple day. When a trend position's expected overnight drift is smaller than the night's swap charge — especially the 3× night — the bot should be allowed to close hours early, or defer a signal-flip close past the charge boundary. Free money from bookkeeping we already do."

**Objections:** STR — "close early when swap > expected drift" *is an exit rule*; exits are the child's thesis (02§B6), and modifying exit timing by a new criterion is strategy modification wearing an accounting hat — the exact move the no-online-self-modification lock exists to stop, even though this variant would be config-driven rather than learned. QNT — the counterfactual is unpriced: dodging the night means being flat through it; for trend children the overnight drift *is* part of the E1 edge (Pass 2 §2.1) — the proposal assumes the answer to an empirical question nobody has run. AUD — if the effect is real, the pipeline already has a lawful door: a child *version* with swap-aware exits, through Stage-R/G1 like any other rule change; TC-1 is precedent (carry-*aware entry* went through the front door as its own child).

**SWG's fallback, accepted by the board as a Threshold-Lab item instead:** the *measurement* is worth having — the Lab (§2.2) will compute, from ledger swap postings + subsequent bars, the realized "swap paid vs overnight move captured" table per child × instrument, so a future child version can be proposed on evidence. The scheduler itself dies.

**VOTE — 1 YES / 9 NO → GRAVEYARD.** ARCH N (exit-rule change outside the gates) · QNT N (unpriced counterfactual; measurement first) · STR N (thesis integrity) · DEV N (defer-past-rollover interacts badly with §1.2 rollover gates) · NET N (—) · AUD N (front door exists) · DAY N (—) · SWG Y (proposer) · FE N (—) · BE N (—).

### 1.9 FE — Operator flight simulator: drill mode for the human in the loop

**Pitch (FE):** "Pilots train on the failures they'll see twice a career. Our operator will meet their first partial-fill-during-confirmation card (§1.6 pass5) with real money on the line. I propose a drill mode: the fake-controller harness (pass5 §7) drives the real GUI/Telegram with scenario-library situations — race-loser truths, STALE_CARD retries, breaker cascades, netting banners — scoring the operator's speed and choices before graduation to smaller timeouts."

**Objections:** QNT — training on simulated cards teaches pattern-matching to the simulator's tells; the graduation thresholds (§6.4 pass5) measure the real thing and would be contaminated if drill stats fed them (FE concedes drill stats stay out of graduation). AUD — cost/value: the fake-controller dev harness already exists for development; productizing it into a scored training mode is real UX work (scenario authoring, scoring, tutorial copy) for one user who will meet each rare card within weeks of demo operation anyway — the demo/shadow phases *are* the flight simulator, with real cards. STR — mild support (the F-001 partial-fill card genuinely benefits from one rehearsal), suggests a one-page illustrated walkthrough in onboarding instead — adopted as a documentation task, not a build.

**VOTE — 3 YES / 7 NO → GRAVEYARD.** ARCH N (demo phase already rehearses with real cards) · QNT N (contamination risk; concession noted but then what's measured?) · STR Y (one rehearsal of F-001 cards has value) · DEV N (scenario-authoring cost) · NET N (—) · AUD N (cost > value pre-v1) · DAY Y (I'd use it once) · SWG N (—) · FE Y (proposer) · BE N (fake-controller stays a dev tool).

### 1.10 BE — Warm-standby core: hot failover replica

**Pitch (BE):** "systemd restart plus boot-verify (pass3 §1.3) costs up to 60 s plus reconcile; a warm standby replaying the event stream could take over in ~1 s with projections already hot. Availability engineering 101."

**Objections (fatal, fast):** ARCH — the entire pass3 §1.4 design rests on *one* writer; a standby that can promote is a split-brain machine, and the fencing protocol needed to make promotion safe (distributed lease over two boxes joined by the very link whose failure triggers promotion) is harder than the whole rest of the system — this is the checkbox-hiding-a-design pattern (pass1 T1) at maximum size. DEV — the 60 s window is already covered where it matters: SL-in-entry-request (pass4 §1.11-1) means positions are born stopped, and the Sentinel (§1.5) now covers the catastrophic tail; the standby defends the *least* dangerous part of the outage. AUD — two processes believing they own the money path is the one failure class we have engineered out everywhere else; reintroducing it for a one-minute RTO improvement fails any cost-of-risk test. BE accepts the arithmetic and withdraws the promotion half; the *replica-as-read-cache* half is redundant with the interface process's read-only DB access.

**VOTE — 1 YES / 9 NO → GRAVEYARD.** ARCH N (split-brain vs sole-writer, unfixable cheaply) · QNT N (—) · STR N (—) · DEV N (window already defended twice) · NET N (fencing over the failing link is a paradox) · AUD N (reintroduces the engineered-out failure class) · DAY N (—) · SWG N (—) · FE N (—) · BE Y (proposer, on record for v3).

---

## §2 Winner designs (schema-level)

### 2.1 Shadow stage (ARCH) — milestone: engine seam at **B2**, full stage machinery at **B5/B6**

**Config & registry.** `strategies/registry.py` gains `stage: research|shadow|live` per `child_id@version`; stage transitions are config events (`config.change_applied`, live-class for `shadow→research` demotion, restart-class for `→live` promotion since promotion re-runs gate checks). A child in `shadow` is instantiated exactly like a live child (same `required_features()`, same pre_filters, same params pinning) with two bindings swapped at the composition root: its OMS routes to `ShadowBrokerAdapter` (a `SimBrokerAdapter` fed live ticks + the current pinned `RealisticFillModel`/`CostModel`), and its mode is forced `auto` with `ConfirmationPolicy=auto_approve` (pass3 §5.3 — no shadow cards reach humans).

**Event/ledger dimensioning.** Envelope payloads for `signal.*`, `exec.*`, `position.*`, `ledger.*` gain `book: "live"|"shadow"` (schema_version bump, upcaster defaults old events to `live`). One log, one writer, one chain (pass3 §1 untouched). Projections fold per book: the shadow `LedgerSnapshot` enforces the full pass3 §2.6 limit stack against a **virtual equity = live equity at shadow-child activation** (so sizing is realistic), but no shadow verdict ever gates a live signal and vice versa. Shadow postings run the full pass6 posting rules against a shadow 1000/4000 account set (P11–P14 apply — shadow books must balance too), permanently excluded from trial-balance identities against broker truth (I5 is live-book-only) and stamped analytics-grade in every export.

**Guardrails (board conditions absorbed):**
- **G1:** shadow children ≤ 4 concurrent (hypothesis); their DAG/child callbacks run under the same 50 ms budget with a separate `loop_lag` attribution tag; sustained shadow-attributed budget breaches auto-demote the newest shadow child to `research` + WARN (F-028 protection).
- **G2:** shadow trades **never** count toward: G3 live-trade minimums, graduation decision counts (§6.4 pass5), F-029 execution-cell samples, or any ledger-grade money surface. They count toward: block-ribbon/CUSUM series *labeled `shadow`* (rendered as a separate hatched ribbon), Stage-R→G2 logic-parity evidence, and Threshold-Lab counterfactuals.
- **G3:** shadow evidence is admissible for the G2 gate **only while the simulator drift check (pass4 §4.8-5) is inside its acceptance bands** — a flagged-optimistic month invalidates shadow evidence for that window exactly as it invalidates G1 runs.
- **G4 (DAY's condition):** children whose Pass-2 viability is RAW-conditional (M1, MC-1, M4) may use shadow for *logic* parity but their G2 exit additionally requires the dossier-named live measurements (e.g. M1's measured adverse selection, M4's open-spread decay) from demo/live feeds — shadow cannot satisfy a measurement-typed criterion by construction.

**G2 redefinition (F-030 update, §7):** G2 = (a) shadow soak ≥ 4 weeks or ≥ 2 blocks with zero kernel-parity diffs (pass3 §5.6 nightly, now comparing live-process shadow signals vs backtest kernel on the same bars) + (b) infrastructure soak on demo for broker-integration paths (order round-trips, spec discovery, reconcile) + (c) any dossier-named measured-data exit criteria. Demo calendar time shrinks; evidence quality rises.

**Auditor red-team (winner obligations):** (i) *model-flattery risk* — shadow inherits every fill-model blind spot (pass4 §4.9); mitigated by G3 and by running shadow fills under **both** fill models with divergence flagged (pass4 §6-6 rule reused). (ii) *Gaming risk* — an eager operator promotes on a lucky shadow month; mitigated: promotion checklist requires the full Stage-R/G1 record and shadow adds to, never substitutes for, gate minimums. (iii) *Hidden cost* — the shadow book doubles several projections' memory and the journal's row count; bounded by G1's cap and the pass3 archive policy (shadow events archive on the same schedule). (iv) *Contamination* — a `book` mix-up is a CRITICAL-class bug; property test **P15** (§5.4) fuzzes mixed streams and asserts fold isolation.

### 2.2 Threshold Lab (QNT) — milestone: **B6** (needs telemetry volume); harness skeleton lands with the backtester at **B1**

**Registered-decision contract.** Every gate/threshold consumer already emits a decision event carrying its inputs (viability evaluations ride `risk.evaluated`/viability events; queue holds ride `exec.order_record.queue_wait_ms` + release samples; CUSUM updates are block events; breaker checks are `breaker.transition` triggers). The Lab requires each register item (§4) to name its **decision event + input fields + pre-registered grid**; an item without all three is not Lab-eligible and says so in the register.

**Sweep job.** Nightly, per item: `sweep(item, day_range)` → for each grid point, re-evaluate the decision function on logged inputs → classify flipped decisions → price flips: trades forgone/admitted are replayed through kernel + pinned fill model (pass3 §5.6 seam) to a modeled R outcome with block-bootstrap CI; alarms/disables counted directly. Artifact `calib/<item>/<yyyymmdd>.parquet` with schema `{grid_value, decisions, flipped, modeled_dR, dR_ci_lo, dR_ci_hi, alarms, disable_days}` + run-card manifest (git sha, cost_model_version, grid hash). GUI: Calibration tab on the Research page; every chart carries the analytics-grade badge and the CI whiskers (banned-phrase list from pass5 §8-7 applies).

**Change rails.** Threshold changes: ordinary config events, human-applied, schema-validated; **rate limit one change per item per quarter** (hypothesis) absent CRITICAL; the change event must cite a sweep artifact id; the register (§4) is regenerated from config so document and system cannot diverge (F-026 spirit applied to calibration).

**Auditor red-team:** (i) *forking paths* — grids frozen in §4; adding a grid point is itself a config event with a stated reason. (ii) *counterfactual optimism* — forgone-trade outcomes are fill-model outputs; the CI + model-version pinning + the pass4 drift check bound it, and the Lab's recommendation surface never says "would have made" (pass5 copy rule). (iii) *hidden cost* — replay CPU; runs in the ProcessPool off-loop, capped at 30 min/night (hypothesis), items round-robin if over budget.

### 2.3 Child-health card strip (STR) — milestone: **B5** (ships with confirmations UI)

**Schema.** `card:json += child_health: {viability: float, viab_state: "ok"|"disabled"|"hysteresis", blocks_last4: [{mean_r: float, verdict: "ok"|"warn"|"insufficient"}], cusum_state: "OK"|"WARN"|"ACTION", live_n: int, shadow_n: int, evidence_grade: "E1"|"E2"|"E3", frozen_at_seq: u64}` — populated by the STA's card builder from the monitoring projection in the same transaction as `confirm.requested`; `frozen_at_seq` makes "what the human saw" exact for the journal (F-001 audit discipline extended).

**Render (one line on Telegram, one row on GUI, between AGAINST and execution details):**
`CHILD  viab 1.6✓ · blocks ✓✓⚠✓ · CUSUM OK · n=48 live` — or, under 20 trades: `CHILD  live sample 7 (<20) — G1 expectancy +0.14R/trade (hypothesis)`. Shadow-stage history renders hatched and labeled `shadow` if the child recently promoted. `cusum_state=WARN|ACTION` renders amber/red and adds a system AGAINST line (pass5 §1.4 mechanism) — a card for a risk-halved child *says* the child is risk-halved.

**Measurement condition (QNT):** §5.3 decision-value analytics gain a covariate `card_had_health_strip` (true from release date) so the strip's effect on decision value is estimable; if per-child decision value degrades ≥ 0.05R (hypothesis) post-release with CI excluding zero, the strip's default flips to off pending redesign — the UI is subject to the same evidence standard as everything else.

**Auditor red-team:** (i) anchoring/double-gating — measured, per above; (ii) staleness — strip is explicitly frozen (label `at 05:50`), no live updates, no card_version bumps from health changes (only fills/spread-gate flips bump, unchanged pass5 §1.8); (iii) cost — one projection read, nil.

### 2.4 Execution A/B (DEV) — milestone: **B6** (requires G3-scale order flow and ≥ 50-fill cells)

**Config object.**
```
exec.experiment {
  exp_id: str, cell: {broker_id, instrument, mechanism_family, session_id},
  arms: [MechanismSpec, MechanismSpec],      # e.g. STOP(broker) vs STOP_SYNTH; LIMIT vs LIMIT_OFFSET(+1)
  allocation: 0.5, unit: "order", blocking: "session_day",
  budget: {max_excess_R_total: 2.0, max_excess_R_month: 0.5},        # (hypothesis) priced off current CostModel
  stop_rule: {alpha_spend: "obf", max_blocks: 12, min_fills_per_arm: 30},
  eligibility: {child_probation: false, news_state: "clear", account_mode_any: true}
}
```
**Assignment:** `arm = H(seed ‖ exp_id ‖ client_key) mod 2` within blocking strata — deterministic, replayable (pass3 §5.5), logged on `exec.order_record.experiment`. **Exclusions (hard):** SL placement/moves (02§A5), urgent/exit class orders, storm/news/rollover-queued releases (their assignment would confound), children on G3 probation (STR's condition).

**Analysis & adoption:** at weekly block boundaries, per-arm cost distributions (slippage + spread + requote outcomes, from order records) compared with an O'Brien-Fleming-style spending boundary over ≤ 12 blocks; crossing ⇒ experiment ends, `exec.mechanism_switched` fires with `exp_id` as evidence (the pass4 §2 flip event, now carrying causal evidence; the 20%-improvement hysteresis is waived when evidence is experimental — that margin existed to buffer confounding the experiment removed). Budget breach ⇒ experiment aborts, arm reverts to incumbent, `exec.experiment_aborted{reason}`. All experiment costs appear as a tagged column in the cost waterfall (AUD condition) and in the G3 review.

**Auditor red-team:** (i) *tuition unbounded by modeling error* — the budget is priced by the model being tested; mitigated: realized excess (measured arm-difference × inferior-arm count) is recomputed per block and the tighter of modeled/realized triggers the cap. (ii) *experiment sprawl* — ≤ 2 concurrent experiments account-wide (hypothesis). (iii) *gaming* — a mechanism vendor... n/a at retail; the realistic gaming is operator-cherry-picking start dates; mitigated by run-card pinning + the block-boundary-only rule.

### 2.5 Stop Sentinel (NET) — milestone: **B4** (ships with adapter hardening; drills before first real-money week)

**Process.** `sentinel/` — single Python process beside the terminal (Windows service under NSSM in topology (b); same box in (a)). Own credentials file (`sentinel.env`: MT5 investor→**no** — requires trade rights for close; a dedicated MT5 login with close-only is not a broker primitive, so: full account login, code-constrained to `ORDER_TYPE_CLOSE_BY`-free, close-only `PositionClose` calls — the constraint is enforced by code review + a CI static check that the sentinel module imports no order-send symbols). Own Telegram bot token + chat allowlist; own healthchecks slug.

**Loop (10 s cadence, hypothesis):** enumerate positions → for each, `sl == 0` ⇒ record; consume core deadman (core POSTs a signed heartbeat to the sentinel's localhost/WG endpoint every 30 s). States: `QUIET` (all stopped, deadman fresh) → `ALERT_NAKED` (position without SL > 60 s: alarm on own channel + own healthcheck flag; the core is probably already fixing it — the sentinel is the auditor, not the fixer) → `ALERT_DEADMAN` (deadman stale > 120 s (hypothesis): alarm "core silent; N positions, M without stops; reply FLATTEN <code> to flatten-all") → `FLATTEN_EXECUTING` on operator command (typed confirmation code, 5-min TTL, allowlisted chat only) → close-all at market with 5 attempts/position, report per-position outcomes. Optional `sentinel.autoflatten: {enabled: false, condition: deadman_stale > 15min AND naked_positions > 0}` — **default OFF**, arming decision on the Pass-8 human sheet.

**Core-side integration:** sentinel closes carry order comment `SNTL`; the reconciler maps deals with that comment to `position.closed(closed_by=sentinel)` (new enum member; upcaster-safe). Chaos suite (pass3 §7.4) gains three rows: kill core with open positions ⇒ sentinel alarms within 3 min; operator FLATTEN during core death ⇒ positions closed, core restart reconciles all as sentinel-closed with zero unexplained diffs; sentinel itself killed ⇒ its healthcheck goes silent (the watchdog is watched).

**Auditor red-team:** (i) *false flatten* — worst case = book goes to cash at market cost; bounded, visible, and human-triggered in v1; the typed-code TTL mirrors the pass5 destructive-command pattern. (ii) *credential surface* — a second holder of account credentials on the Windows box; same trust domain as the terminal itself (which already holds them); WG-only network exposure; token rotation runbook extends pass3 §8.5. (iii) *drift risk* — a sentinel that silently stops running is worse than none: its own healthcheck ping is mandatory config, and the core alarms if the sentinel's heartbeat endpoint stops answering (mutual watching, both alarms independent).

### 2.6 Broker scorecard & migration dossier (AUD) — milestone: **B6** (first scorecard after 60 live/demo days)

**Monthly job** (after the pass6 §5.5 month close; consumes closed months only):
```
broker.scorecard {
  broker_id, month,
  spread: {per (instrument, session): measured_median_ticks, published_ticks, ratio},
  slippage: {per (instrument, mechanism, session): p50, p90, n},
  storms: {count, minutes, clustered_with_news_pct},
  requote_rate, trade_channel_uptime_pct,
  swap: {true_up_drift_bps, rate_changes_count},
  conversion_markup_bps,                      # 4400 flow / converted volume
  commission_mismatches: int,
  cost_drag: {per child: R_year_vs_reference, total_R_year},   # reference = RAW-tier prior (literature-informed)
  verdict: "OK" | "REVIEW" | "MIGRATION_CANDIDATE"
}
```
`cost_drag(child) = Σ_cells (measured_cost_ticks − reference_cost_ticks) × trades_year(cell) / stop_ticks_avg` — the same tick arithmetic as F-003, so the scorecard and the viability gate can never disagree about what a cost is. **Verdict rule (hypothesis):** REVIEW at total drag > 1.5 R/yr; MIGRATION_CANDIDATE at > 3 R/yr sustained 2 months **and** a candidate profile beating the binding cells by ≥ 30% after the ×1.3 demo-grade haircut **and** drag > amortized switching cost (dossier's own estimate: re-discovery, gate re-runs at new costs, N days reduced trading). Dossier is a generated document citing every number's cell and month; the decision and the migration are human, always.

**Candidate evaluation:** a candidate broker gets a demo account; discovery + spread/swap samplers run ≥ 2 weeks; results stored as a `BrokerProfile(candidate, demo_grade=true)`. The board notes and accepts the honesty limit: B-book brokers can treat demo flow kindly (pass4 §4.9-2); the haircut is a guess; the dossier says so in its header.

**Auditor red-team (self):** (i) *reference-tier gaming* — drag depends on the reference; reference is pinned (RAW-tier literature prior) and printed; (ii) *seasonality* — month-over-month deltas shown with 3-month trend before any verdict escalates; (iii) *hidden cost* — a second demo account's upkeep; only spun up when REVIEW trips.

---

## §3 Graveyard

| Proposal | Seat | Vote | Killing reason (one line) |
|---|---|---|---|
| Manual scalp cockpit (discretionary tickets through the risk engine) | DAY | 2–8 | Second origination path outside the charter; poisons decision analytics and collides with netting occupancy (pass4 §1.7) — off-system trades stay a reconciler/quarantine concern. |
| Swap-dodge exit scheduler | SWG | 1–9 | An exit-rule change smuggled past the gates as bookkeeping; if the effect is real it enters as a child version through Stage-R/G1 — the measurement (swap paid vs overnight move captured) survives as a Threshold-Lab table. |
| Operator flight simulator (scored drill mode) | FE | 3–7 | Demo/shadow phases already rehearse with real cards; scoring risks training-to-the-sim; survives only as an onboarding walkthrough doc for the F-001 partial-fill card. |
| Warm-standby core (hot failover) | BE | 1–9 | Promotion = split-brain against the sole-writer architecture; the outage window is already defended by SL-in-request (pass4 §1.11-1) and the Sentinel (§2.5); fencing over the failing link is the harder problem. |

---

## §4 The calibration register

Consolidates every "calibrate in Pass 7" debt from passes 1–6. Columns: starting value **(all hypothesis unless marked)**; calibration procedure (data, sample, recalibration trigger); acceptance band (what "calibrated" must satisfy); sign-off (seat who must approve the number entering config). Items marked **[LAB]** are Threshold-Lab-eligible (§2.2) with pre-registered grids frozen here. The register is normative: config keys cite register row ids (`CAL-nn`); a threshold change without a register row is a schema error.

| ID | Item (owner) | Start (hyp.) | Calibration procedure | Acceptance band | Sign-off |
|---|---|---|---|---|---|
| CAL-01 **[LAB]** | Viability threshold — F-003 successor (pass1 F-003; pass2 §1.3) | disable < **1.5**, re-enable ≥ **1.8** (hysteresis pair; old "4" void) | Grid {1.2, 1.35, 1.5, 1.65, 1.8, 2.0} over ≥ 6 months G2/G3 + shadow decisions: per grid point, disable-days, forgone trades' modeled R (CI), realized R of admitted marginal trades. Recalibrate: quarterly Lab review; CRITICAL if the pass2 worked-hypothesis children (T1 STD ≈ 1.1–1.3) all sit below whatever bar is chosen — the bar must discriminate, not exterminate. | Chosen point must show: modeled net R of *admitted-below-next-notch* cohort ≤ 0 (the bar sits where marginal trades stop paying) with CI excluding large positives; false-disable rate (children re-enabled within 2 weeks by hysteresis) < 20% of disables. | QNT + AUD |
| CAL-02 | Gap-k multipliers per asset class (pass1 F-005/F-011; pass3 §2.3) | fx major 1.3 · fx cross 1.5 · metal 2.0 · index CFD 3.0 · crypto 1.0 wknd/1.5 | From the 15-yr lake: distribution of \|close-to-open gap\| / ATR(20) across all weekend + exchange-close boundaries per class; `k := P99(gap/ATR) × (avg stop distance / ATR)⁻¹`-normalized so k× risk-at-stop ≈ P99 gapped loss. Cross-checked against live `gap_fill` tags (pass4 §1.3) as they accrue. Recalibrate annually + after any observed gap > sample P99. | Historical Monday losses on simulated Friday books ≤ gap-stressed budget in ≥ 99% of boundary weeks per class; k never set below the live-measured P95 once n ≥ 20 tagged gap fills exist per class. | SWG + AUD |
| CAL-03 | Margin-utilization cap / notional-per-class caps / gap-stressed totals (pass3 §2.6 #8–10) | margin ≤ 25% · notional fx 6×/metal 3×/index 2×/crypto 1× · gap-stressed acct ≤ 12%, trend sleeve ≤ 6% | Stress replay: worst historical 1-week windows (2015 CHF, 2020-03, 2022 vol events — literature-anchored dates) applied to maximal-book configurations from the combined backtest; caps set so broker stop-out distance ≥ 2× worst simulated excursion. Binding-order report (F-036) re-run after every change. | No simulated stress week produces margin call; caps must be *reachable* (binding-order report shows each can bind — a cap that can never bind is dead config). | AUD + ARCH |
| CAL-04 | Reconciliation tolerances T_price/T_swap/T_comm/T_conv/T_cash/T_mtm (pass6 §5.3) | as pass6 §5.3 table | ≥ 60 demo days of `recon.money_run`: per class, fit clean-day residual distribution; tolerance := max(pass6 floor, P99.5 of clean residuals). Trend-guard multiplier (3×) re-derived so 10-day drift alarm has < 5% false rate under bootstrap of clean days. Recalibrate on broker change or any spec restatement. | Planted-error suite (§5.3) detected 100%; false alarms ≤ 1/week aggregate across classes on clean demo data. | AUD |
| CAL-05 | Unattributed-bucket alarms — 1900 balance / 4900 flow (pass6 §4.1) | WARN 0.1% equity · CRITICAL 0.5% | Same 60 demo days: observed clean-run bucket flows (should be ≈ rounding-scale); WARN := max(0.1%, 5 × P99 clean daily flow). CRITICAL fixed at 0.5% unless demo evidence shows structural flows (would itself be a finding, not a threshold problem). | Zero CRITICALs on clean demo months; planted MISSING_DEAL lands in 1900 and alarms within one daily run. | AUD |
| CAL-06 | Fill-simulator acceptance bands + monthly drift check (pass4 §4.8-5) | MAE ≤ 2 ticks · realized P90 ∈ [0.8, 1.3]× simulated | First 3 live/G3 months: replay realized orders through the simulator; bands re-set to (P95 of monthly MAE, symmetric P90-ratio band) such that the persistent-optimism trigger (2 consecutive months) has ≤ 5% false-fire under bootstrap of aligned months. Per-cell breakdown mandatory (a global pass hiding one rotten cell fails the spirit). | Trigger sensitivity: an injected +30% optimism in one mechanism's costs must fire within 2 months in simulation of the check itself (§5.3 control C-SIM). | DEV + QNT |
| CAL-07 | MC anomaly reference for the F-024 breaker (pass3 §2.4) | trip < P1 of `mc_windows_24h`, WARN < P5 | Artifact rebuilt at every re-validation and roster/weight change from the *current* portfolio backtest (children without live history contribute backtest streams). Verify empirical trip behavior on ≥ 6 demo/shadow months: expected WARN count ≈ 5% of days ± binomial CI. Recalibrate: any roster change, quarterly refresh regardless. | Backtest-replayed historical stress days (CAL-03 set) all trip; clean months trip ≤ 1 false CRITICAL/quarter. | QNT |
| CAL-08 | **CUSUM boundaries — F-013 spec (owed by this pass, delivered here)** | see procedure | **Spec:** per child×instrument, block statistic `x_b` = block mean-R (20 trades / 4 wks); standardized `z_b = (x_b − μ_G1) / σ_G1,block` where μ, σ come from the G1 MC of block means. One-sided decay CUSUM: `C_b = max(0, C_{b−1} + (−z_b) − κ)`, slack **κ = 0.5**; WARN at **h₉₅ = 2.5**, ACTION at **h₉₉ = 4.0** sustained 2 consecutive blocks (pass1 F-013 rule), demote-to-paused = ACTION + human ack or corroborating execution-cost regime shift (pass4 §5 profiles). Calibration: per child, simulate H₀ (G1 trade distribution) → tune (κ, h) to ARL₀ ≥ **40 blocks** for WARN, ≥ **200 blocks** for ACTION (per-child alpha budget); simulate H₁ (expectancy −0.15R shift) → detection ARL₁ ≤ **8 blocks** median. Recalibrate when a child's G1 distribution is re-validated. | Both ARL targets met in simulation per child before Stage-L arms; the §5 controls (C-CUS-null, C-CUS-decay) pass in CI. | QNT |
| CAL-09 | Human-decision graduation thresholds (pass5 §6.4) | ≥ 30 decisions · \|decision-value\| < 0.03R | n threshold := smallest n where decision-value CI half-width ≤ 0.05R given the child's measured R variance (so "30" flexes per child instead of being folklore); 0.03R band re-examined once ≥ 5 children have ≥ 50 decisions (pooled variance). Decision-value definition (pass5 export honored): approved-realized mean R − all-signals modeled mean R per block, counterfactuals via the pinned fill model, analytics-grade. | CI-based n ∈ [20, 60] sanity range; if outside, the metric definition (not the threshold) is reviewed. | QNT + FE |
| CAL-10 | OCO `T_grace` (pass4 §3.5) | 5 s; clamp [2, 15] s | As pass4 (adopted unchanged into the register): backtest `oco_gap_distribution.parquet` for f_df; after n ≥ 50 live OCO resolutions, `T_grace := clamp(P99(t_cancel_ms)+1 s, 2, 15)`, monthly; P99 > 5 s escalates broker-quality CRITICAL (never a wider window). | Whipsaw-vs-pipeline misclassification < 5% on labeled backtest double-fills. | DEV |
| CAL-11 **[LAB]** | Entry-queue release thresholds (pass4 §1.1) | gate_ratio ≤ 1.5 × 3 samples @ 2 s; review if > 30% queued signals expire | Lab grid {1.25, 1.5, 2.0, 2.5} × {2, 3, 5 samples}: expiry-in-queue rate vs realized post-release cost of admitted entries, from queued-signal events + order records; ≥ 3 months of news windows. | Chosen point: marginal admitted entries (vs next-tighter notch) have modeled net R ≥ 0; expiry rate < 30%. | DAY + QNT |
| CAL-12 | Storm detector enter/exit (pass4 §1.4) | enter ≥ 5 rejects/≤ 3 orders/60 s; exit 60 s clean | From `exec.storm` + reject streams over ≥ 3 months: choose params minimizing (missed-storm seconds + false-storm seconds) on hand-labeled episodes (label rule: any 60 s window with > 50% reject rate). | False-storm rate < 1/week; missed storms (label without detection) < 5%. | DEV + NET |
| CAL-13 | F-029 minimum samples (n=100 fills · 50 touch-episodes · 200 market fills · n₀=100 shrinkage · 0.7× prior floor) (pass4 §2/§4.8) | as listed | Simulation study on synthetic cells with known parameters: smallest n where the shrunk estimator's P90 error ≤ 20% of prior spread; floor stress-tested against the B-book drift scenario (pass4 §4.9-2) — the floor must prevent modeled costs from chasing a manipulated lucky streak. | Estimator study reproducible in CI; floor blocks the manipulated-streak scenario in the §5 control C-CELL. | QNT + AUD |
| CAL-14 | Adverse-selection term (F-012) | 0.5 × spread-avoidance credit | Replaced per cell by measured `exec.post_fill_drift` (drift at 5 bars, hypothesis horizon — horizon itself Lab-eligible {1, 5, 20}) once n ≥ 100 limit fills; prior is a floor (cost never modeled below 0.7× prior). M1's G2 exit criterion consumes exactly this (pass2 §3.1g). | Measured term stable across two consecutive 100-fill windows (ratio ∈ [0.7, 1.4]) before it replaces the prior. | QNT |
| CAL-15 | E0 regime confidence weights + dwell (pass2 §4.1) | 0.30/0.30/0.15/0.25 · dwell 3 bars (1 into CHAOS/DEAD) | Sensitivity study on the frozen lake: perturb weights ±0.1 simplex-constrained; measure regime-label churn rate and downstream child P&L variance in the combined backtest. Weights are **not** fit (that would be a learned regime model, E4's rejected path) — the study only proves the chosen weights sit on a plateau. | Label agreement ≥ 90% across the perturbation set (plateau exists); if not, the E0 formula returns to the board rather than being tuned. | QNT + STR |
| CAL-16 | Feature canary tolerance + Welford recompute cadence (pass3 §4.3/§4.5) | 1e-9 relative · recompute every 10k bars | Longest-chain float-drift study (Wilder chains, 15-yr replay): tolerance := 10 × observed max drift at the recompute cadence; twice-in-a-row canary failure stays CRITICAL. | Zero false canary failures across full-lake replay; injected single-bit state corruption always caught (§5.3 C-FEAT). | ARCH |
| CAL-17 | Clock/NTP thresholds (pass3 §8.3) & broker-offset drift bounds (pass4 §1.0) | WARN 250 ms · block 750 ms · CRIT 1 s · broker-offset drift 60 s | 90 days of measured offset series from both boxes: thresholds re-set to (P99 clean × 3) with the 750 ms entry-block retained unless measured clean P99 exceeds 200 ms (would indicate an ops problem, not a threshold problem). | False entry-blocks < 1/month on healthy chrony. | NET |
| CAL-18 | Staleness thresholds per session (pass4 §1.0, F-025) | STALE > max(10 s, 2× median inter-tick gap) · DEAD 60 s | Per (instrument, session) inter-tick gap distributions from 60 days of ticks: STALE := P99.9 gap × 1.5; DAX-evening and dead-D1-feed unit tests (pass1 F-025) re-verified against calibrated values. | False STALE < 1/instrument/week; true feed-death detection < 2 min in drills. | NET |
| CAL-19 | Loop budget & lag thresholds (pass3 §4.6) | 50 ms/callback · WARN 100 ms · CRIT 500 ms | Profile on target VPS class with max roster + 4 shadow children (§2.1 G1): budget := P99.9 callback × 2; shadow-attribution split verified. | Zero WARN on healthy steady-state; injected 200 ms stall always attributed to the offending callback. | BE |
| CAL-20 | Experiment budgets & concurrency (this pass, §2.4) | 2R/experiment · 0.5R/month/cell · ≤ 2 concurrent | After first 3 experiments: realized excess cost vs modeled (the §2.4 tighter-of rule); budgets re-set to keep annual total experiment tuition < 1.5R (hypothesis) account-wide. | Realized annual tuition ≤ budget; every experiment's tuition visible in the cost waterfall. | AUD + DEV |
| CAL-21 | Broker scorecard verdict thresholds (this pass, §2.6) | REVIEW > 1.5 R/yr · MIGRATE > 3 R/yr + 30% candidate margin + ×1.3 haircut | After 6 scorecard months: thresholds re-examined against measured month-to-month drag variance (thresholds must exceed 2× that variance or verdicts flap). | No verdict oscillation (REVIEW↔OK) more than once per quarter per broker. | AUD |
| CAL-22 | Shadow-stage caps & admissibility windows (this pass, §2.1) | ≤ 4 shadow children · G2 shadow soak ≥ 4 wks/2 blocks | After first two shadow promotions: review whether parity-diff catch rate justifies longer/shorter soak (a soak that has never caught anything at 4 weeks and catches at 2 is over-long). | At least one full promotion cycle documented before any cap change. | ARCH + QNT |

**Register governance:** the register lives in-repo as the source for config validation ranges; every row's current value + last-calibration artifact id renders on the GUI Calibration tab; Pass 8 places CAL-01, CAL-02, CAL-08, CAL-09 defaults on the human decision sheet (they gate money most directly).

---

## §5 The gate-control suite

Pass-1 T7's standing requirement, now a spec: **every gate ships with a negative control (known-bad must fail) and a positive control (known-good must pass), run in CI; a gate without passing controls is inert and its verdicts are inadmissible.** Pass 2 nominated M3 (RSI(2) transfer — famous, published, decayed) as the specimen family; pass 6 added planted-error controls for the audit job; pass 4 §6-10's scenario list is normative for the execution rows. This section is the harness.

### 5.1 Preconditions (admissibility, restated as code)

A gate run is admissible only if: (a) run-card complete (git sha, config hash, dataset manifest hash, cost_model_version, fill_model_version, seed — pass3 §5.5); (b) **both** fill models executed with divergence reported (pass4 §6-6); (c) **SimAccount emitted a full posting stream and P11–P14 pass on the run's own log** (pass6 export — a backtest whose books don't balance is not evidence); (d) the control suite relevant to that gate is green at the harness version pinned in the run-card. The report generator refuses to render a gate verdict when any precondition fails — inadmissibility is a hard error, not a footnote.

### 5.2 Specimen children (all M3 variants, built once, frozen as fixtures)

| ID | Specimen | Construction | Must-produce verdict | What it proves |
|---|---|---|---|---|
| NC-1 | `m3_random` | M3 shell; entry trigger replaced by seeded Bernoulli matched to M3's trade frequency; exits/risk identical | **G1 FAIL** (OOS PF < 1.25 band; expectancy CI spans 0) | The G1 statistical bar rejects no-edge flow at realistic costs |
| NC-2 | `m3_lookahead` | M3 with a planted 1-bar lookahead (consumes the forming bar's close via a deliberately mis-keyed feature epoch) | **Passes a naive backtest by construction; must be caught pre-G1 by the epoch/parity discipline:** feature-epoch validation rejects the mis-keyed subscription at registration, and if force-registered in the harness, golden-replay parity (pass3 §5.6) diffs shadow/live signals vs backtest ⇒ **G2 logic-parity FAIL** | Lookahead cannot survive the pipeline even when it beats the statistics |
| NC-3 | `m3_overfit` | M3 + 6 params tuned on the OOS segment (train-on-test, in-harness only) | **G1 FAIL** on plateau (single-island signature) + WF efficiency < 0.5; variant-count multiple-testing discount (05§B3) applied and logged | Plateau/WF machinery detects selection, not just bad luck |
| NC-4 | `m3_costblind` | M3 evaluated with a zero-cost fill model injected | **INADMISSIBLE** (precondition (b)/(c) violation — the harness asserts refusal, not failure) | The pipeline cannot be asked the wrong question |
| NC-5 | `m3_singlesymbol` | M3 tuned to be OOS-positive on exactly one symbol (fixture data selected accordingly) | **G1 FAIL** on the M-family cross-instrument rule (≥ 3 instruments / ≥ 2 groups, pass2 §3.3f) | Cross-robustness rule has teeth |
| PC-1 | `m3_prime` | M3 rules on lake data with a seeded synthetic reversion drift injected post-extension, sized to expectancy ≈ **1.5× cost** | **G1 PASS**, cleanly (all sub-checks green) | Gates pass known-good — a gate that rejects everything is also broken |
| PC-2 | `m3_marginal` | as PC-1, drift sized to ≈ **1.05× cost** | **G1 marginal verdict**: must NOT pass cleanly — expected outcome is fail-or-flag (expectancy CI includes threshold; both-fill-model divergence flag likely) | The gray zone behaves like a gray zone; threshold CAL-01 discriminates near the bar |

Fixture data: a dedicated 4-instrument, 6-year lake slice + the synthetic-drift injection tool (seeded, manifest-pinned); specimens re-run **nightly** against the current gate code and **on every PR** touching `research/`, `risk/viability`, or gate report code. **Any specimen verdict change is merge-blocking** — including NC verdicts *improving* (a negative control that starts passing means the gate broke open).

### 5.3 Control rows beyond G1/G2 (every automated judge gets a planted lie)

| ID | Target gate/judge | Negative control (must flag) | Positive control (must stay quiet) |
|---|---|---|---|
| C-CUS-null / C-CUS-decay | CUSUM Stage-L monitor (CAL-08) | Simulated child with expectancy shifted −0.15R from block 10 ⇒ ACTION ≤ 8 blocks median across 1,000 seeds | H₀ stream (G1 distribution) ⇒ false ACTION rate consistent with ARL₀ ≥ 200 blocks |
| C-MC | F-024 anomaly breaker (CAL-07) | Replayed historical stress-day P&L ⇒ trips at P1 | 1,000 clean simulated months ⇒ ≤ spec false-trip rate |
| C-AUDIT | pass6 daily audit job | Fixture log with 6 planted errors: unbalanced posting, parentless posting, mis-allocated deal, wrong-rate conversion (pass6 §6.3 four) **+ planted duplicate execution + planted missing-deal** (this pass) ⇒ **6/6 flagged or the build fails** | Clean fixture month ⇒ zero flags |
| C-RECON | pass6 money reconcile | Injected broker-side deal absent from ledger; injected ledger line absent from broker ⇒ MISSING_DEAL / UNKNOWN_LEDGER_LINE with correct severities | Clean day ⇒ verdict CLEAN, residual ≤ T_cash_accept |
| C-SIM | Simulator drift check (CAL-06) | +30% cost optimism injected into one mechanism's model ⇒ persistent-optimism trigger fires ≤ 2 simulated months | Aligned realized=simulated months ⇒ no trigger over 12 simulated months |
| C-CELL | F-029 floors (CAL-13) | Manipulated lucky-streak cell (B-book scenario): 40 artificially cheap fills ⇒ modeled cost never falls below 0.7× prior; mechanism flip refused below min-n | Honest 200-fill cell ⇒ shrinkage converges to truth within study bands |
| C-FEAT | Feature-state canary (CAL-16) | Single-bit corruption of a serialized node state ⇒ canary catch + rebuild event | Clean restart replay ⇒ zero canary failures |
| C-VIAB | F-003 viability gate | The pass1 register's 30%-win-rate example (edge overstated 120× under the old formula) ⇒ gate must fire under the corrected formula (regression pin, pass3 §7.1) | T1 worked-hypothesis numbers at RAW tier ⇒ gate passes |
| C-EXEC | pass4 scenario suite (§6-10 list) | Every §1 scenario row asserts its (F) fix behavior; failure of any assertion is merge-blocking | — (these are behavioral, both polarities in-row) |
| C-SHDW | Shadow-book isolation (P15, this pass) | Fuzzed mixed live/shadow event streams ⇒ folds provably isolated; a planted cross-book posting refused at write | Clean dual-book day ⇒ both books balance independently |

### 5.4 Harness mechanics

Runs as a CI tier between property tests and chaos drills (pass3 §8.6 pipeline gains a `controls` stage): PR-scope = specimens NC-1..5/PC-1..2 (cached fixtures, ~minutes) + C-VIAB + C-AUDIT; nightly = full table incl. 1,000-seed statistical controls; the harness version is itself run-card-pinned so a gate verdict always names the control suite that certified the gate. New property test **P15** (shadow isolation) joins P1–P14. Control fixtures are frozen-lake citizens: committed manifests, checksums, the Titan lesson applied (pass3 §5.5).

**The Auditor's closing rule, board-adopted:** a change that makes a control fail may not be merged by making the control agree — control edits require a board-level (Pass-8+ governance) sign-off recorded in the control file's header. Controls are the constitution of the honesty machinery; amending them is meant to be loud.

---

## §6 Board debate log (objections that changed content)

1. **AUD vs shadow evidence creep (§1.1/§2.1).** Objection: shadow months will be waved at gate meetings as if they were live months. Forced changes: analytics-grade badge on every shadow surface; shadow trades excluded from all live-trade minimums (G2 guardrail); shadow admissibility chained to the simulator drift check (G3). Signed off.
2. **DAY vs shadow for RAW-conditional scalps (§1.1).** Objection: M1/M4 live or die on measured microstructure the fill model guesses at. Forced change: guardrail G4 — measurement-typed G2 criteria can never be satisfied by shadow. DAY's No vote stood anyway; the guardrail stands regardless.
3. **AUD vs the Threshold Lab's forking paths (§1.2/§2.2).** Forced changes: pre-registered frozen grids in the register; CIs + badges mandatory; one change per item per quarter; change events cite artifacts. AUD's No vote recorded with the Pass-8 ratification request.
4. **QNT vs any per-trade expectation surface on cards (§1.3/§2.3).** Forced change: block-frame only, insufficient-sample rendering, and the strip's own effect measured via the decision-value covariate with a defined roll-back trigger. Unanimous after amendment.
5. **STR + AUD vs unbounded A/B tuition (§1.4/§2.4).** Forced changes: 2R/0.5R budgets with tighter-of modeled/realized enforcement; probation children excluded; experiments visible in the cost waterfall; ≤ 2 concurrent. STR's No stood on principle; the caps stand.
6. **BE vs the Sentinel as a second actor (§1.5/§2.5).** Forced changes: close-only action set enforced by CI static check; auto-flatten default OFF and on the Pass-8 human sheet; the drill suite must prove sentinel closes reconcile as `closed_by=sentinel` with zero unexplained diffs. BE's No recorded; conditions adopted.
7. **STR vs scorecard-driven broker churn (§1.6/§2.6).** Forced change: switching-cost line + 12-month amortization requirement + 2-month sustain before MIGRATION_CANDIDATE. Unanimous after amendment.
8. **QNT vs the "marginal" positive control's ambiguity (§5.2 PC-2).** Objection: "fail-or-flag" is a soft assertion that will rot. Resolution: PC-2's assertion is mechanical — the run must produce ≥ 1 of {expectancy CI spanning CAL-01's bar, fill-model divergence flag, plateau amber} and must NOT produce a clean-pass report; the harness asserts the disjunction. Adopted.
9. **SWG salvage of the swap measurement (§1.8).** The graveyarded scheduler's measurement survives as a Lab table (swap paid vs overnight move captured, per child × instrument), explicitly labeled as evidence *for a future child version through the front door*. Unanimous.
10. **ARCH vs register sprawl (§4).** Objection: 22 rows will decay into a second config file nobody reconciles. Forced change: register rows are the *source* of config validation ranges (CAL ids in schema), rendered live on the Calibration tab — the document and the system share one artifact. Unanimous.

---

## §7 Findings-resolution updates

| Finding | Pass-7 action | Status after this pass |
|---|---|---|
| F-003 (threshold calibration) | CAL-01: hysteresis pair 1.5/1.8 (hypothesis), Lab grid + acceptance band + sign-off; C-VIAB regression control pinned | **CALIBRATION-REGISTERED** (number remains hypothesis until CAL-01 procedure completes) |
| F-005 / F-011 (k, margin/notional calibration) | CAL-02 / CAL-03 procedures + acceptance bands; gap-fill tags close the measurement loop | CALIBRATION-REGISTERED |
| F-012 (fill-simulation spec residue) | Pass 4 delivered the simulator; this pass delivers acceptance bands (CAL-06), adverse-selection replacement rule (CAL-14), and the C-SIM control | **RESOLVED** (bands hypothesis until first 3 live months) |
| F-013 (sequential statistics) | CAL-08 delivers the CUSUM spec (κ=0.5, h=2.5/4.0, ARL₀ 40/200, ARL₁ ≤ 8 — all hypothesis with a per-child simulation calibration procedure) + C-CUS controls; pass5 §5.1 display contract confirmed compatible (two labeled boundaries) | **RESOLVED** (boundaries per-child-calibrated before Stage-L arms) |
| F-024 (anomaly breaker reference) | CAL-07 artifact lifecycle + C-MC controls | RESOLVED |
| F-029 (learning-loop thresholds/circularity) | CAL-13 estimator study + floors verified by C-CELL; pass4 min-samples adopted into the register; mechanism-flip counter-reset confirmed | **RESOLVED** |
| F-030 (G2 evidential value) | G2 redefined (§2.1): shadow logic-parity + demo infrastructure soak + dossier-named measurements; execution leg remains pass4 §4.8-5 with CAL-06 bands | **RESOLVED** (redefinition to Pass 8 for synthesis adoption) |
| Pass-1 T7 (gates need controls) | §5 gate-control suite: specimens, statistical controls, planted-error audit controls, admissibility preconditions, constitution rule | **RESOLVED** |
| Pass-5 export (graduation thresholds, decision-value definition) | CAL-09 (CI-based n, decision-value defined per pass5 with pinned fill model) | CALIBRATION-REGISTERED |
| Pass-6 exports (tolerances, unattributed thresholds, SimAccount admissibility, audit controls) | CAL-04/CAL-05; admissibility precondition §5.1(c); C-AUDIT extended to 6 planted errors | ADOPTED / RESOLVED |
| F-002, F-016 | Untouched — decision matrices (pass3 §8.1/§8.7, pass4 §1.7, pass6 §1.4) ride to the Pass-8 human sheet; the Sentinel design (§2.5) is topology-aware and prejudges neither | OPEN-FOR-HUMAN (unchanged) |
| **New — F-040** | Shadow-book contamination (a `book` mix-up mixes paper and money state) | RESOLVED-AT-BIRTH: P15 + C-SHDW + write-time refusal of cross-book postings |
| **New — F-041** | Experiment assignment nondeterminism would break replay parity | RESOLVED-AT-BIRTH: hash-of-seed assignment (§2.4), asserted by the determinism CI check |
| **New — F-042** | Sentinel action set could widen by code drift | RESOLVED-AT-BIRTH: CI static check (no order-send imports), close-only review rule, drill coverage |

**Constraints exported to Pass 8:** adopt or reject the G2 redefinition (§2.1) alongside pass5's `confirm.hold_applied` amendment; human decision sheet gains — sentinel auto-flatten arming (default OFF), CAL-01/02/08/09 starting values, the Threshold Lab quarterly cadence ratification (AUD's request), and the standing F-002/F-016 + `accounting.tax_lot_policy` items; build order: Sentinel at B4, card strip at B5, shadow seam at B2 with stage machinery B5/B6, Lab/A-B/scorecard at B6; the §5 control suite is a precondition of the *first* gate verdict ever issued — no child passes G1 before the controls exist and pass.

— End of Pass 7. Six innovations enter the build with their red-team obligations attached; four died with their reasons recorded; twenty-two numbers now have procedures instead of just labels; and every gate that judges a child is itself judged by a planted lie it must catch.
