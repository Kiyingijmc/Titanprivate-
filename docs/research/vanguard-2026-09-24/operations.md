# M. Operational design, recovery and pre-mortem

Proposed requirements, not claims that current Titan already satisfies them. Existing shared safety controls remain binding.

## Safety invariants

1. A native budget may reduce permitted exposure but never override Titan's global veto or increase its limits.
2. One authority owns each broker position's protective policy. Existing unrelated strategies keep their current management profile.
3. Every nonzero filled position has a verified broker protective stop, or enters a defined protection-failure response. A failed initial stop placement must not silently become ordinary managed exposure.
4. Confirmed stop protection never moves backward in the adverse direction. Proposed protection is not confirmed protection; gaps remain possible.
5. Entry, pending, partially filled, reserved and outcome-unknown commitments all consume capacity. Deferred candidates do not consume capacity until atomically reserved.
6. Reservations are released by confirmed cancellation/rejection/absence or transfer to confirmed exposure, not merely by a timer.
7. A campaign in UNWINDING may create cancellation/close commands, never new exposure. Any fill racing with cancellation becomes an unwind obligation.
8. Duplicate input events and retries cannot create duplicate logical acquisition, realized profit or released capacity. Commands have durable IDs and precondition versions.
9. “Exactly once” is an effect objective implemented with durable identity, reconciliation and idempotent targets; transport acknowledgement alone does not provide it.
10. Broker positions/deals are the exposure/accounting truth. Strategy intent is the hypothesis/desired-state truth. Disagreement is explicit, never papered over.
11. Raw MFE and unrealized profit grant no risk credit. Realized profit is not counted once in equity and again as a second capital deposit.
12. Equity-to-stop loss, entry-relative loss, stress loss, margin and notional are distinct limits. Entry-positive SL does not eliminate current-equity downside.
13. Bar availability precedes decisions; accepted command time precedes its simulated effects. Historical correction cannot alter what was available to a past decision.
14. Missing/stale state blocks new exposure while preserving broker protection and available safety management. Unknown state is not an empty portfolio.
15. Volume is rounded down to the broker grid and risk recomputed; an untradeable minimum yields rejection. Partial targets leave legal volume or follow an explicitly approved full-close policy.
16. A trend/campaign restart cannot reset cumulative failed-attempt or loss constraints. Configuration and R denominators are immutable for existing trades.
17. Critical state/reservation/outbox updates commit before dispatch. If critical persistence fails, new risk creation stops; broker protection remains and the operator is alerted.
18. Replay/live execute the same policy functions, state transition order and configuration. Different observed market paths may cause different results; identical recorded event streams must not.

## Execution realism

Represent long entry at ASK and exit at BID; short entry at BID and exit at ASK. Stops, pending triggers and historical extrema use the correct quote side. BID OHLC plus fixed spread is an approximation, explicitly labeled. Spread included in executable prices must not be deducted again. Include commission, financing/swap, conversion, slippage and legal lot sizes.

Validate stop/freeze distance, price tick, volume min/max/step, margin and allowed fill/order modes at submission. If executable entry differs from planned entry, recompute actual R and excess-risk handling. STOP gaps can fill away from intended prices. LIMIT fills can be partial or improved; a favorable bar extreme before entry is unavailable to the position. The current source's assumptions must not be inherited as guarantees.

Three command classes require different recovery:

| Class | Desired effect | Retry rule |
|---|---|---|
| Entry | Create identified exposure once | UNKNOWN → reconcile request/order/deal/position mapping before retry; never blindly resubmit |
| Stop modification | Reach a monotonic target SL | Retry only if current broker stop is worse and command precondition/profile still valid |
| Reduction/close | Reach remaining volume target | Retry target, not repeated quantity; account for broker deal IDs and live remaining volume |

The Gateway needs persistent or otherwise reconciliable entry identity before multi-entry campaigns. A strategy comment alone is not a reliable full command identifier. Where the current protocol cannot establish whether a request filled, block further relevant exposure and reconcile; do not promise automatic retry safety.

On netting accounts additions can alter the average entry and inherited SL/TP. Maintain immutable tranche fills for attribution, while physical broker position is one object. Initial independent-lifecycle campaigns require hedging support; capability must be observed, not assumed.

## Persistence and recovery contract

Persist observer state/counters and last processed event; trend identity/attempt ledger; campaign membership/state; trade fills/R/profile/lifecycle/evidence counters; quote/bar watermarks and source revisions; confirmed versus desired SL/volume; all outstanding order IDs and reservations; deferred candidate expiry; risk numeraire, drawdown anchor, gross issuance window and cumulative losses; configuration/schema/strategy versions; unique processed input/deal IDs.

Use an existing SQLite transactional extension for the live Titan path, not a second VANGUARD database. A write-ahead decision/outbox record and state transition should commit together. The `tradebot/` event-log design is a useful precedent but is not a drop-in live dependency.

Recovery sequence:

1. Acquire exclusive ownership of the account strategy executor. Load and validate snapshot/config/version and critical event suffix. Incompatible/corrupt state puts new risk in HALTED.
2. Rebuild pure state from the last valid checkpoint and deduplicated events. Do not regenerate past orders from historical signals.
3. Obtain a fresh complete broker snapshot plus deal/order history needed to resolve outstanding commands. A partial/incomplete snapshot cannot establish absence.
4. Reconcile known tickets, netting position identifiers and deal IDs. Unknown positions are quarantined for ownership/accounting resolution while included in global risk. Preserve their current stops; do not adopt them into a campaign by symbol guess.
5. Reconcile desired versus confirmed protection and remaining volume. Resend only idempotent safe targets whose current preconditions still hold.
6. Rebuild risk from broker exposure plus all unresolved reservations. No profit credit until confirmation and stress accounting agree.
7. Backfill complete missing bars for state continuity with original availability/revision policy. Mark the outage interval; no fictitious historical acquisitions. Expire deferred setups whose executable opportunity has passed.
8. Resume new exposure only when data, book, protection and persistence readiness all pass. Journal recovery decisions and unresolved exceptions.

Duplicate bars with identical identity/content are no-ops. Conflicting same-time bars are revisions, not duplicates: preserve original observation and record the revision with its later availability. Freeze affected trading if the active inference cannot safely reconcile it. Out-of-order events may enrich history but cannot retrospectively trigger commands. Gaps distinguish scheduled market closure from missing expected observations; do not synthesize directional evidence with forward-filled OHLC.

## Failure-mode matrix

| Scenario | Detection | Containment | Recovery | Telemetry |
|---|---|---|---|---|
| Prolonged chop | High transition/attempt rate, low net displacement, realized attempt losses | Fixed attempt/loss cap; no native leverage escalation | New causal trend qualification, not arbitrary timer forgiveness | TREND_ATTEMPT_CAP, turnover/cost decomposition |
| False ignition | Local contradiction after breakout | Registered thesis exit and broker SL | Re-entry only under permitted mode/cumulative cap | IGNITION_INVALIDATED, saved/missed continuation |
| Volatility shock | Realized range, quote spread and stress exposure jump | Block additions, retain confirmed SL, execute global reduction if needed | Fresh specs/quotes; observe stable valid evidence | VOL_SHOCK, stress loss before/after |
| Gap through SL | First executable price beyond resting stop / actual deal | Account actual loss; no assumed −1R bound; halt additions if caps violated | Reconcile fills/costs and remaining book | GAP_SLIPPAGE, risk overrun |
| Spread explosion | Two-sided executable quote exceeds operational limit | No new entries; do not silently widen stop or disable required exits | Revalidate fresh quotes; retain urgent safety actions | SPREAD_BLOCK, actual exit spread |
| Flash reversal | Structural reversal or broker stop before software decision | Broker protection acts first; campaign unwind, cancel pending | Reconcile all outcomes before opposite entry | STOP_BEFORE_SOFTWARE, CAMPAIGN_UNWIND |
| Deep staircase pullbacks | Local contrary move with intact slower state | Fixed/retention policy holds unless own guard trips; no reactive arbitrary tightening | Normal causal continuation | HOLD_STRUCTURAL_VALID; conditional giveback |
| Slow grind | Small persistent drift, little local breakout | Baseline measures missed exposure; no post hoc trigger relaxation | New experiment only if missed-participation hypothesis registered | MISSED_TREND, acquisition delay |
| Parabolic trend | High realized move/volatility and concentrated equity sensitivity | No unlimited maturity/confidence sizing; marginal stress cap | Hold or exit under registered policy, not predicted top | CONCENTRATION_CAP, late-add attribution |
| Correlated portfolio shock | Signed common-factor stress exceeds envelope | Global safety precedence; stop all new allocations | Fresh book/spec/covariance state; controlled resume | FACTOR_STRESS, global versus native veto |
| Repeated M5 false entries | Same trend attempt/loss ledger | Fixed ceiling; fatigue not assumed predictive | A new ID cannot reset unresolved loss accounting | ATTEMPT_LIMIT, failed-family counts |
| Stale H1 state | Expected-close watermark/age breached | Block new entries and graduation; preserve current broker SL | Backfill with availability policy; no retroactive fills | STALE_STRUCTURAL, duration and source |
| Missing M15/M5 bars | Source-count/completeness and calendar checks | No fabricated complete higher bar; freeze affected counters | Valid backfill/replay, reset only by explicit rule | INCOMPLETE_BAR, expected/actual counts |
| Restart during campaign | Startup broker/local mismatch | New-risk HALTED, retain exposure/reservations | Snapshot + suffix replay + broker reconciliation | RECOVERY_REQUIRED, unresolved IDs |
| MT5 disconnect | Freshness/heartbeat/command status failure | No new exposure; broker SL stays; no credit release | Fresh full broker snapshot plus deals | BROKER_UNAVAILABLE, unknown commitments |
| Rejected stop modification | Retcode or observed SL remains old | Old SL remains risk basis; no satellite financed from request | Retry legal target or escalate if protection inadequate | STOP_UNCONFIRMED, retry/age/retcode |
| Duplicate signal/command | Durable event/trade/command ID conflict | Idempotent no-op; do not use TTL alone as dedup | Reconcile result by identity | DUPLICATE_EVENT/COMMAND |
| Satellite fills as anchor exits | Fill event with changed campaign/book version | Count fill; if unwind, cancel remainder and close filled quantity; never promote automatically | Fresh reconciliation; close campaign only when all clear | FILL_DURING_UNWIND |
| Opposite trend while entry pending | Trend ID invalidation before fill/cancel confirmation | Cancel pending, retain its capacity; handle late fill as unwind | New opposite participation only after reconciliation | STALE_TREND_ORDER, CANCEL_FILL_RACE |
| Max-risk race | Book version mismatch / concurrent reservations | Atomic compare-and-reserve; reject/recompute loser | Retry evaluation, not blind send | BOOK_VERSION_CONFLICT |
| Partial fill / partial close | Deal quantities differ from request | Manage actual fill, reserve remainder, target remaining volume | Dedup deals, reconcile volume and costs | PARTIAL_FILL, VOLUME_TARGET_PENDING |
| Unknown manual position/order | Fresh broker object absent locally | Include in global exposure; stopless/uncomputable book blocks entries | Resolve ownership, preserve broker truth | UNOWNED_EXPOSURE, RISK_UNCOMPUTABLE |
| Disk failure or dropped critical log | Commit error/sequence gap | No new risk; do not infer successful command persistence | Restore valid state and reconcile broker | PERSISTENCE_FAILURE, sequence/hash |
| Broker spec/currency conversion change | Spec version/age or price-risk inconsistency | Recompute legal quantity and risk; no hardcoded fallback | Refresh and reconcile existing exposure valuations | SPEC_CHANGED, RISK_REVALUED |
| Config change with active trades | Hash/profile mismatch | Keep original trade policy; global tightening explicit | New campaigns use new profile only | CONFIG_TRANSITION, inherited profile |

## Observability

Every material decision records `event_id`, event/arrival/decision times, strategy/config/data/cost versions, trend/campaign/trade IDs, phase/state, entry family, horizon readings, quality flags, contradiction counter, management horizon, actual initial R, MFE/MAE-to-date, confirmed/desired SL, realized/unrealized/stressed protected PnL, requested/approved risk, binding capacities, decision and reason codes.

Keep numeric inputs and rule thresholds sufficient to reproduce the result. Do not log a made-up “0.91 vitality probability.” Role and score fields absent from the actual policy are omitted, not populated with arbitrary placeholders.

Required explanations:

- Entry: activation/trigger bars, availability, quote/cost eligibility, admission and sizing record.
- 0.37 RU: named binding cap and volume rounding, with monetary numeraire.
- HOLD through a pullback: evidence guards not violated, current stop and gap exposure still present.
- Early exit: exact contradiction observations, request time, actual fill and counterfactual comparator ID.
- Rejected third satellite: parent campaign version, attempt count, current/pending/reserved/stress capacity, binding veto.

Critical events must be durable and unsampled. Sampled debug features are acceptable only if they are not needed for replay. Daily operational summaries report data coverage, unknown orders, pending management confirmations, unsupported broker capabilities and suppressed decisions. Process heartbeat alone is not healthy observation coverage, as Titan's September shadow review demonstrated.
