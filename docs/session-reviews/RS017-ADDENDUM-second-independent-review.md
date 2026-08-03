# RS017 — independent session review of S017 (`sec-05-zmq-unauthenticated-bound-tcp`)

Fresh, adversarial review. I did not build this. Audited **only** the committed work
on `session/S017` (`db13b21`, single commit on base `ab2ad69`) against
`.mig/state/S017.prompt.md` §2/§4, the project `CLAUDE.md`, `config/config.yaml`,
the real FBS broker specs in `data/specs.json`, and the **live running process**.

Domain is `risk_management` (RISKY per `.mig/config`) and the demo-forward bot is
LIVE while I write this, so every claim below is verified by execution, not by
reading prose. Nothing in this commit had been reviewed before: the build agent
died before committing, the work was salvaged, and one defect was fixed on top.

---

## Footprint

```
src/core/system_controller.py                 +9/-3
src/execution/bridge_zmq.py                  +19/-6
src/risk/risk_manager.py                     +80/-11
tests/unit/test_bridge_zmq_bind_host.py     +162  (new)
tests/unit/test_risk_manager_specs_sanity.py +277  (new)
```

No MQL5 file touched. No other `src/` module touched. **Scope is clean.**

## Premise check — confirmed live, not taken on trust

- `wslinfo --networking-mode` → **`mirrored`**.
- The live bot (PID 1738208) still listens on the wildcard:
  `LISTEN 0.0.0.0:32768`, `0.0.0.0:32769`, `0.0.0.0:32770`.
- At `ab2ad69`, `bridge_zmq.py` bound `f"tcp://*:{...}"` on all three sockets,
  and `risk_manager.py:62-76` coerced with bare `float()` inside one
  `try/except ValueError: pass` — no finiteness check, no envelopes, no jump rule.
- `config/config.yaml:27` has declared `host: "127.0.0.1"` all along; nothing read it.

Premise is real on both parts.

---

## What this session got right (verified, not assumed)

**1. The loopback bind does NOT break the live EA path.** I did not accept the
mirrored-mode claim; I checked what the EA is actually doing. Its three live
connections are:

```
ESTAB 127.0.0.1:32770 <- 127.0.0.1:59897   (pid 1738208)
ESTAB 127.0.0.1:32768 <- 127.0.0.1:59895
ESTAB 127.0.0.1:32769 <- 127.0.0.1:59894
```

The EA's traffic already arrives on the **loopback local address**, so a bind to
`127.0.0.1` will still accept it. Combined with `wslinfo` = mirrored and the EA's
`Titan_Gateway.mq5:13` `InpIP = "127.0.0.1"`, part 1 is safe to restart onto.
Nothing else in the tree connects to 32768–32770 from a non-loopback address
(the HTTP bridge is :8766 on Windows, the GUI is :8770; neither touches ZMQ).

**2. The numeric envelopes reject nothing a real FBS symbol sends.** Checked
`SPEC_BOUNDS` at `risk_manager.py:68` against every cached real broker value in
`data/specs.json` (11 symbols, including all but three of the 12 live `pairs`):

| field | observed real range | envelope | tightest margin |
|---|---|---|---|
| `val` | 0.01 (BTCUSD) … 10.0 (XBRUSD) | `[1e-4, 1e4]` | 100× |
| `ts`  | 1e-5 (5-digit FX) … 0.01 | `[1e-6, 100]` | 10× |
| `vm`/`vs` | 0.01 | `> 0` | n/a |

No live pair is at risk of being silently rejected into "stopped trading". The
envelopes are defensible.

**3. Rejection is a genuine no-op and the fail-safe survives.** `clean` is built
locally and only assigned at `risk_manager.py:130`; every reject path returns
before it. I confirmed by execution that a never-specced symbol whose only update
was rejected stays absent from `symbol_specs`, so `calculate_lot_size` keeps
returning `0.0` — the `CLAUDE.md` invariant holds. A reject also does not disturb
any *other* symbol.

**4. The jump baseline really is the last ACCEPTED value.** `prior` reads
`self.symbol_specs` (`:113`), which only ever holds accepted values. A rejected
frame cannot become the baseline; a sequence of *rejected* frames cannot walk it.

**5. The new tests genuinely bite.** I ran a 13-mutant harness against the source
and re-ran the two new modules each time. **13/13 killed** — widened envelopes,
deleted jump guard, `MAX_SPEC_JUMP` 10→100, writing `clean` before the jump check,
`setdefault` instead of assignment, `<= 0` → `< 0`, dropped `math.isfinite`,
reverting `incoming[field]` to the leaked `raw`, `DEFAULT_HOST` → `0.0.0.0`,
`host or` → `host if host is not None`, and re-wildcarding the PUSH and REQ binds
(including the `_init_req_socket` reset path), plus making the controller ignore
the config key. Nothing survived. The tests assert the invariant, not a proxy.

**6. Adjacent suites are green.** `test_risk_manager_sizing`, `test_money_for_move`,
`test_risk_manager_normalize_price`, `test_risk_manager_exposure_cap`,
`test_controller_events`, `test_trade_manager` → **86 tests OK**. The two new
modules → **25 tests OK**. The spec-touching property class
`test_tradebot_properties.TestP8NormalizePriceOnTickGrid` → 3 tests OK in 0.2s
(all `TICK_BANDS` values sit inside the new envelopes).

**7. On the mig `FAIL`:** `.mig/state/S017.test.log` ends `>>> FAILED (rc=124)`
with zero `FAIL:`/`ERROR:` blocks — a wall-clock timeout, not a broken test.
Corroborating: `tests/unit/test_tradebot_properties` alone exceeds **400 s**, and
its spec-touching class accounts for 0.2 s of that. The suite cost is pre-existing
and unrelated to this change. Not counted as a finding.

---

## Findings

### MAJOR-1 — A single *accepted, in-envelope* HISTORY frame still drives every live pair to `hard_max_lots`. The session's stated purpose is not achieved.

`risk_manager.py:113-128` applies `MAX_SPEC_JUMP = 10.0` to each field
**independently**. But sizing does not depend on `val` or `ts` separately — it
depends on their ratio. From `risk_manager.py:237-239`:

```python
ticks_at_risk    = diff / spec['ts']
money_loss_per_lot = ticks_at_risk * spec['val']      # == diff * (val/ts)
```

So one frame that moves `val` down 10× **and** `ts` up 10× — each exactly at the
maximum the guard permits, each therefore accepted — moves the quantity that
actually sizes trades by **100×**. Starting from the *real* FBS specs in
`data/specs.json`, at $10,000 equity, 1% risk, `hard_max_lots: 5.0`:

| symbol | healthy lots | after ONE accepted frame (`val÷10`, `ts×10`) | true risk taken |
|---|---|---|---|
| EURUSD | 0.19 | **5.00** (hard max) | 26 % of equity |
| GBPUSD | 0.16 | **5.00** | 31 % |
| USDJPY | 0.31 | **5.00** | 16 % |
| AUDUSD | 0.24 | **5.00** | 21 % |
| USDCAD | 0.27 | **5.00** | 19 % |
| GBPJPY | 0.19 | **5.00** | 26 % |
| XAUUSD | 0.09 | **5.00** | 56 % |
| US30   | 0.04 | **3.70** | 93 % |
| BTCUSD | 0.06 | **4.54** | 76 % |
| XBRUSD | 0.09 | **5.00** | 56 % |

And `risk_to_stop` reports the poisoned figure — for the EURUSD row it returns
**$60.00** for a position whose real risk-to-stop is **$2,535.00** — so
`max_total_open_risk_pct` validates it as safe off the same poisoned numbers.

That is, verbatim, the failure the session prompt says this work exists to prevent:

> "one bad HISTORY message … makes `ticks_at_risk ≈ 0` and every subsequent trade
> size to `hard_max_lots: 5.0` against an intended 1% risk, with `risk_to_stop`
> validating it as safe off the same poisoned numbers."

**The single-frame worst case is unchanged for all ten pairs I could test with real
specs.** The guard bounds the *per-field* move but not the outcome.

A second, independent path to the same place: a symbol with **no prior specs** has
no jump baseline at all, so a first frame of `val=1e-4, ts=100` (both exactly on the
envelope, both accepted) sizes EURUSD at **5.00 lots**. Worse, the guard then
*latches* it — the subsequent legitimate frame (`val=1.0, ts=1e-5`) is rejected as a
10,000× jump, so the poison survives every good frame until the process restarts.
Verified by execution.

A third: four consecutive **accepted** 10× steps walk `val` from 1.0 to 1e-4
(`0.19 → 5.00` lots). The code comment at `:114-116` claims the accepted-baseline
design stops the specs being walked "anywhere they like"; it stops *rejected*
frames from walking them, and `test_a_rejected_update_does_not_become_the_new_jump_baseline`
asserts exactly that, which reads as broader assurance than it gives.

**The DoD checkboxes are met literally** — the enumerated bounds and the ">10×
change" rule are implemented exactly as written. I am raising this anyway because
the session's own success criterion is the *outcome*, the domain is `risk_management`,
and the fix is small and squarely inside the function already being changed.

Suggested remediation (author's call, all inside `update_symbol_specs`):

1. Apply the ≤10× jump rule to the derived quantity `val/ts` as well as to each
   field. A genuine 4→5-digit regrade moves that ratio by exactly 10× (`ts`
   1e-4→1e-5, `val` unchanged), so legitimate regrades still pass, while the
   compound 100× frame does not. Real observed ratios: BTCUSD 1, US30 10,
   XAUUSD 100, USDJPY 618, XBRUSD 1,000, EURUSD/GBPUSD/AUDUSD 100,000.
2. Add an absolute floor on `val/ts` for the **first** frame, where there is no
   baseline. The real minimum across every cached symbol is 1 (BTCUSD); a floor
   of ~0.01 leaves 100× margin and rejects the `1e-4 / 100` first-frame poison
   (ratio 1e-6).
3. Consider making a *persistent* reject (n consecutive rejects for a symbol)
   drop the symbol to spec-less rather than latching stale specs forever — today
   a symbol whose broker genuinely regrades past the guard keeps trading off
   values now known to be wrong, and only a log line says so.

### MAJOR-2 — A malformed HISTORY frame still kills the bot, one line after the new guard safely rejects it. (Pre-existing, adjacent, one line.)

`system_controller.py:613-622` calls the newly hardened `update_symbol_specs`, then
immediately does:

```python
self._publish(SpecsUpdated(
    symbol=sym,
    tick_value=float(msg.get('tv', 0) or 0),   # :618
    ...
```

Executed against `{"type":"HISTORY","symbol":"EURUSD","tv":"abc",...}`:

```
guard state (correctly rejected): {}
RAISED OUT OF _process_incoming_data: ValueError could not convert string to float: 'abc'
```

The main loop's `try` at `system_controller.py:316` wraps the **whole** `while True`
(handler at `:368`), so this is not a skipped message — it sends
`☠️ FATAL SYSTEM CRASH` to Telegram and `raise e`s the bot dead. The very
non-numeric input the session taught `update_symbol_specs` to survive still takes
the process down two lines later.

Same call site, second problem: `SpecsUpdated` is published **unconditionally**,
carrying the raw values whether or not they were accepted. The event tape therefore
records specs that the RiskManager rejected. No runtime consumer reads it today
(`SpecsUpdated` appears only in `events.py`, this publish, and the tape tests), but
the tape is the replay/audit record and it now disagrees with the state it mirrors.

Not a regression and not in the literal DoD — but `system_controller.py` is already
touched by this commit, and guarding `:618-622` behind the accept/reject outcome
fixes both halves in one edit.

### MINOR-1 — This commit ships a recovery instruction that its own change breaks.

`bridge_zmq.py:19-22` (new) tells the operator:

> "If the host is ever moved back to NAT mode the EA will NOT reach a loopback bind:
> set `connection.zeromq.host` in `config/config.yaml` to the WSL IP and re-check
> with `scripts/check_bridge.py`."

But `scripts/check_bridge.py:56` is `bridge = ZMQBridge()` — no `host` argument, no
config read — so it now hard-binds `127.0.0.1` regardless of what the operator put
in `config.yaml`. In NAT mode with a correctly-configured bot, `check_bridge.py`
would bind loopback, the EA (pointed at the WSL IP) could not reach it, and the tool
would print `❌ No PONG` on a healthy configuration. Before this commit it bound
`tcp://*` and worked in either mode. `scripts/smoke_test_execution.py:96` has the
same shape and it places real orders.

Zero impact today (mirrored mode verified above), but the DoD's operator note names
`check_bridge.py` as *the* validation step for this change, so the tool should read
the same config key the bot does.

### MINOR-2 — `vs` has no lower bound, and the comment asserting that is fine is wrong.

`risk_manager.py:69-71`:

> "'vm'/'vs' have no upper bound … They only have to be positive so the volume math
> cannot divide by 0."

Division by zero is not the only failure mode. `vs = 5e-324` is finite and positive,
so it is **accepted**, and then `risk_manager.py:271`
`lots = math.floor(adjusted_lots / vol_step) * vol_step` raises:

```
OverflowError: cannot convert float infinity to integer
```

Given the `:316`/`:368` structure above, that is fatal too. Reachability is
pre-existing (the old code stored the same value), and no real broker sends a
denormal — but the session's own comment claims this class is closed, and it is not.
A `vs`/`vm` lower bound (or a `math.isfinite` check on the quotient) closes it.

### MINOR-3 — An existing test was silently defanged by this change.

`tests/unit/test_risk_manager_sizing.py:46-50`:

```python
def test_zero_volume_step_does_not_crash(self):
    """A broker reporting volume_step=0 must not cause a divide-by-zero."""
    rm.update_symbol_specs("XAUUSD", val=1.0, size=0.01, v_min=0.0, v_step=0.0)
    lots = rm.calculate_lot_size(2000, 1990, "XAUUSD", "BULLISH")
    self.assertGreaterEqual(lots, 0.0)
```

`v_min=0.0` is now rejected, so XAUUSD stays spec-less, `calculate_lot_size` returns
`0.0` on the no-specs path, and `assertGreaterEqual(lots, 0.0)` passes **without ever
reaching** the guard it was written to protect
(`risk_manager.py:242-243`, `spec['vm'] if spec['vm'] > 0 else 0.01`). That guard is
now unreachable via `update_symbol_specs` at all. The test is green and vacuous —
the exact pattern this project's standing lessons flag ("a change can defang an
existing test without turning it red"). Either retire the test with a comment
pointing at the new rejection, or re-point it at the surviving path.

---

## Relationship to the RS017 already committed on `main`

While I was reviewing, the orchestrator finalized S017 (`1365357` committed a
different RS017 with **MIG-VERDICT PASS**; `c397ab0` merged and indexed it). That
review is thorough and I agree with almost all of it — its bind analysis, its
12-pair envelope measurement and its 20-mutant test audit reach the same
conclusions I did independently.

We diverge on one thing, and it is the thing that decides the verdict. That review
records the poisoning risk as *"an attacker … can be walked `1.0 → 1e-4` in four
frames"* and *"at the envelope corner … still saturates at `hard_max_lots`"*, and
classifies it as accepted residual risk (OBS-2, "cannot fire on a first-frame
broker misquote"; "costs the attacker a handful of crafted frames").

**It does not cost a handful of frames. It costs one.** Because the guard is
per-field, `val ÷ 10` and `ts × 10` in the *same* frame are both individually
legal and compound to 100× on `val/ts`. Measured against the real specs in
`data/specs.json`, that single accepted frame takes **all ten** pairs from healthy
size to `hard_max_lots` (or ~90% of it) — starting from a *healthy* baseline, with
no walk and no envelope corner required. That means the jump guard does not reduce
the single-frame worst case for any live pair, which is the premise the PASS rests
on. I therefore reach a different verdict on the same code.

Given the session has already merged, this may be more appropriately actioned as a
follow-up backlog row than a re-open — that is the operator's call. The defect is
real either way, and the fix is ~5 lines in `update_symbol_specs`.

## Verdict rationale

Part 1 (the bind) is correct, minimal, config-driven, covered on the reset path, and
I verified against the live process that it will not break the EA. Part 2's
mechanics — no-op rejection, accepted-only baseline, preserved fail-safe, operator
logging, envelopes wide enough for every real FBS symbol — are all sound, and the
tests are the strongest I have seen in this chain (13/13 mutants killed).

But MAJOR-1 is not a hypothetical: with the real broker specs this bot trades on,
one accepted frame still produces a `hard_max_lots` position at 16×–93× the intended
risk on every pair, and the portfolio cap still waves it through. The session
delivered its checklist without delivering its purpose, on a live trade-sizing path,
in a RISKY domain, while a forward test is running. That has to go back.

MIG-VERDICT: CHANGES
