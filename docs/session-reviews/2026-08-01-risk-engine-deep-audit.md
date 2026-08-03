# Risk-engine deep audit — 2026-08-01

**Scope:** `src/risk/` (risk_manager, exposure, correlation) + every controller call path
(`_execute_signal`, reserved risk, daily-anchor persistence, heartbeat/EXECUTION coupling),
`StateManager` risk surfaces, `TradeManager`'s emergency guard, and the risk test modules.
**Tree audited:** working tree on `feat/swap-survey` (contains the merged RISK-01 anchor fix —
`restore_daily_anchor` + boot-restore block are present).
**Method:** full read of the four risk modules and every call site; cross-checked line-by-line
against `docs/audit-2026-07-30/` (RISK-01…13) and `docs/session-reviews/RS-RISK-01.md` so this
report only *adds* or *re-verifies*, never re-litigates. Risk test modules run: **80/80 OK**.

---

## 1. Verdict

The core discipline of the engine is genuinely good — fail-safe sizing without specs, a
fail-closed book-wide $ cap with operator alerting, in-flight risk reservation, net-of-commission
consistency between sizer and cap, and sanity-bounded spec ingestion. The dangerous gaps are
almost all **at the boundaries** of the engine, not inside it: what the count gates can't see
(resting orders), what nothing refreshes (broker specs), what trips silently (the daily breaker),
and what the anchor fix still gets wrong across an outage (RS-RISK-01 MAJOR-1, already tracked).

## 2. Status of previously-reported findings (re-verified against this tree today)

| Finding | Status in this tree |
|---|---|
| RISK-01 daily anchor resets on restart | **Fixed** (persist/restore present). RS-RISK-01 verdict is still CHANGES: MAJOR-1 (stale anchor re-labelled under the new day key across an outage-spanning restart), MEDIUM-2..5, MINOR-6/7 all **still open** here — `_persist_daily_anchor` still runs *before* the 23:45 block (`system_controller.py:432`), reset is still level-triggered on the one-minute window (`:433`). Tracked: backlog row opened `146764f`. |
| RISK-02 count caps blind to resting pendings | **Still open.** `check_exposure` gets `self.current_open_positions` only (`system_controller.py:516`); arbiter caps likewise. Per-symbol=1 and max-6 are unenforced in the book's normal (limits-resting) state; only the 5% $ cap counts pendings. |
| RISK-03 correlation fails open | **Still open** (`correlation.py:105-106`), plus errors go to `print`, not the audit log. |
| RISK-04 correlation direction-blind | Still open. |
| RISK-05 saturation substring/len==6/hardcoded 2 | Still open (`exposure.py:33,107-120`). US30/US100/BTCUSD/ETHUSD/XTIUSD (and effectively XAUUSD) exempt. |
| RISK-11 `round(lots, 2)` vs sub-0.01 vol_step | Still open (`risk_manager.py:298`). BTCUSD/ETHUSD with `vs=0.001` can silently never trade. |
| RISK-12 commission solver skipped when comm dominates | Still open (`risk_manager.py:278-287`). |
| §3.5 silent breaker trip | Still open — see NEW-3 below for the sharper framing. |
| EXIT-03 CANCEL fire-and-forget then row delete | Still open (`system_controller.py:845-846`). |
| SEC-05 spec poisoning | **Partially remediated:** `SPEC_BOUNDS` + `MAX_SPEC_JUMP` + reject-is-NOOP (`risk_manager.py:94-156`) and loopback bind are in this tree. Transport is still unauthenticated. |

## 3. New findings (not in the 07-30 audit or RS-RISK-01)

### NEW-1 [MEDIUM] — Broker specs are fetched once per process lifetime; tick_value goes stale
`GET_HISTORY` — the only carrier of `tv/ts/vm/vs` — is sent exactly twice per symbol, in
`_perform_warmup` (`system_controller.py:1024,1027`). Nothing ever re-requests it: not on EA
reconnect, not daily, not on spec rejection. MT5 `tick_value` for non-USD-quote instruments
(GBPJPY, USDJPY, XAUUSD in some quotings) is the account-currency value *at quote time*; it moves
with the cross rate. On a soak measured in weeks, a 5% USDJPY move is a ~5% systematic sizing
error on every JPY-quoted trade — silently, with all tests green. This also interacts badly with
the (correct) `MAX_SPEC_JUMP` guard: if a legitimate >10× spec change ever occurs, the symbol is
pinned to stale specs forever, because no refresh cycle exists for a *later* good frame to land
in steps.
**Fix:** periodic (e.g. daily, post-23:45) `GET_HISTORY` re-request per active symbol, or a
dedicated lightweight `GET_SPECS`; alert if a symbol's specs age beyond N hours.

### NEW-2 [MINOR] — First `OPENED` releases the *whole* symbol's reserved risk
`_reserve_risk` deliberately **accumulates** per symbol ("adding is the conservative reading",
`system_controller.py:571-585`), but `_release_reserved_risk` (`:604-617`) pops the entire symbol
key on the first `EXECUTION:OPENED`. If two orders for one symbol are ever in flight (the
documented two-intents case the accumulate defends against), the first fill releases *both*
reservations while the second order still has no DB row — a brief under-count in exactly the
scenario the accumulation was built for. Narrow window (OPENED latency ≪ bar cadence), but the
release should subtract the released order's own risk, not clear the key.

### NEW-3 [MEDIUM, sharpened restatement of §3.5] — Breaker trips are invisible *and* leave resting risk armed
`check_can_trade()`'s only caller is `calculate_lot_size` (`risk_manager.py:236-237`), which
returns 0.0 with **no log line** (the missing-specs branch logs; this one doesn't), no Telegram,
no state change. Beyond silence: a trip blocks *new sizing only*. Resting LIMIT/STOP orders
placed before the trip remain live and can fill **after** the daily loss limit is already
breached, adding fresh risk on the worst day. The engine's own uncomputable-book alarm
(`_alert_uncomputable_book`) exists precisely because "a total trading stop is indistinguishable
from a quiet market" — the same rationale applies verbatim to the breaker, and it has no alarm.
**Fix:** on first trip per day: log + Telegram once, and cancel Titan-owned PENDING rows (the
DB already knows them).

### NEW-4 [MINOR] — `pending_signal_meta` is symbol-keyed; two in-flight orders collide
`self.pending_signal_meta[symbol] = {...}` (`system_controller.py:562`) and
`pending_signal_meta.pop(sym)` on OPENED (`:732`). With RISK-02 unfixed, a second same-symbol
order dispatched while the first's OPENED is in transit overwrites the first's metadata; the
first OPENED then registers with the *second* order's entry/SL/lots, and the second falls to the
degraded no-meta path (`status="ACTIVE"`, sl=0 → book goes uncomputable → full trading halt).
Keying by an order correlation id (or per-symbol FIFO queue) removes the collision; fixing
RISK-02 removes the trigger.

### NEW-5 [MINOR] — Exposure count/saturation gates and the correlation filter have zero unit tests
`tests/unit` has no test constructing `ExposureManager.check_exposure` or `CorrelationManager`
at all — the only tested exposure surface is `check_total_risk`/`aggregate_open_risk` (47 tests,
good ones). The gates with the known open defects (RISK-02/03/04/05) are exactly the untested
ones; any fix there currently lands without a red-first test to anchor it.

### NEW-6 [INFO] — Cosmetics/latents
- `equity_min` initialises to `float('inf')`; a no-heartbeat day would print `$inf` in the 23:45
  report (`system_controller.py:863`).
- `min_vol`-vs-floor edge in `calculate_lot_size`: the `< min_vol` check runs *before*
  floor-to-step (`risk_manager.py:293-297`), so a value can pass the check then floor below
  `min_vol` when `vm` is not a multiple of `vs` (exotic, broker-dependent).
- `max_currency_saturation = 2` and correlation `threshold = 0.8` / 1h cache are hardcoded
  (config-blind), already noted as part of RISK-05 but worth folding into its fix.

## 4. What was attacked and held (don't re-spend the effort)

- **Sizing math** (`calculate_lot_size`): spec-driven, fails safe to 0 without specs, breaker →
  0, `diff==0` → 0, `/0` guarded on `vm/vs`, hard cap applied before flooring. Consistent with
  the cap's net-of-commission basis via `risk_to_stop` (+comm both sides — no permissive bias).
- **`aggregate_open_risk`**: fail-closed on any uncomputable row, names the culprit
  (`last_uncomputable_row` → Telegram), dedups filled-limit double counting by ticket, counts
  pendings from the DB (not the SL-less heartbeat `orders`), abs() overstates BE+ trades
  (conservative). The known manual-pending blind spot is documented and needs an EA change.
- **Spec ingestion**: bounds are broker-plausible not symbol-true, rejects are NO-OPs, jump guard
  baselines only on *accepted* frames, rejection is logged with symbol+field+value.
- **Anchor plumbing in-day**: restore is a pure guarded setter; corrupt/NaN/negative persisted
  values can't wipe a live anchor; `_trading_day_key` rolls exactly at 23:45 EAT (all re-verified
  by the 80-test run; deeper adversarial verification lives in RS-RISK-01's "held" table).
- **Reserved-risk TTL** (300s) correctly ages out never-opened sends; over-states until expiry
  (safe direction).

## 5. Priority order (this auditor's recommendation)

1. **RS-RISK-01 MAJOR-1 remediation** (already backlogged, `146764f`) — edge-trigger the daily
   reset on `_trading_day_key`; fixes MINOR-6 for free. It's live in the demo soak now.
2. **RISK-02** — pass pendings (DB rows) into `check_exposure` and the arbiter caps; smallest
   diff with the highest weekly-probability payoff; also defuses NEW-4.
3. **NEW-3** — breaker trip: one alert + cancel Titan-owned pendings.
4. **NEW-1** — daily spec refresh + staleness alert.
5. **RISK-03/04/05 + NEW-5** — rework the correlation/saturation layer behind red-first tests.
6. **RISK-11** — step-aware rounding (blocks the BTC/ETH universe expansion candidates).
