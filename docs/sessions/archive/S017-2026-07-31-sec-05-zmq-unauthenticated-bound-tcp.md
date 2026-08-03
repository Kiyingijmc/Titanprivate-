---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S017"
date:          "2026-07-31"
slug:          "sec-05-zmq-unauthenticated-bound-tcp"
parent_session: "none"
task_domain:   "risk_management"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S017 · 2026-07-31 · "sec-05-zmq-unauthenticated-bound-tcp"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Fail-closed sanity bounds on broker-supplied symbol specs, and bind the ZMQ sockets to the configured host instead of every interface (SEC-05, parts 1–2)

**Why it matters / what it unblocks:** `update_symbol_specs` accepts whatever floats arrive on an unauthenticated socket, so one bad `HISTORY` message — hostile *or* a broker misquoting `tick_value` after a symbol-spec change — makes `ticks_at_risk ≈ 0` and every subsequent trade size to `hard_max_lots: 5.0` against an intended 1% risk, with `risk_to_stop` validating it as safe off the same poisoned numbers. This is a risk control at least as much as a security control. Verified live on 2026-07-31: the running bot has 32768/32769/32770 bound `0.0.0.0` while holding positions.

**Exact scope (what "doing this task" means):**
- `src/risk/risk_manager.py` `update_symbol_specs` (currently `:62`): reject an update whose values are non-finite, or where `ts ∉ [1e-6, 100]`, `val ∉ [1e-4, 1e4]`, or `vm <= 0` / `vs <= 0`; additionally reject any value that is a **>10× change** from the last accepted value for that symbol. A rejected update must be a **no-op** — the previously accepted specs stay in place, and a symbol that never had accepted specs stays spec-less — and must emit a `logger.log_event("RISK", …)` naming the symbol, the offending field and the value. Never silently coerce a bad value into the store.
- `src/execution/bridge_zmq.py` (`:25`, `:36`, `:53`): bind the host declared in config instead of the literal `tcp://*`. `config/config.yaml:27` already declares `host: "127.0.0.1"` under the bridge block and the code never reads it — read it, and default to `127.0.0.1` when the key is absent. Ports are unchanged.
- Tests under `tests/unit/`: a table of accepted specs; one case per rejection class (each bound, non-finite, `<= 0`, the >10× jump); proof that a rejected update leaves prior specs intact; proof that a symbol whose only update was rejected still makes `calculate_lot_size` return `0.0` (the existing fail-safe must survive); and a bridge test asserting each socket's bind string is built from the configured host.

**Explicitly OUT of scope (do NOT touch this session):**
- **The HMAC / shared-secret part of SEC-05 (part 3) and any MQL5 change** — `mql5_bridge/Experts/Titan_Gateway.mq5` and `TitanZmq.mqh` require a manual MetaEditor recompile on Windows, so nothing touching them can be built or verified headlessly. It stays its own backlog row.
- Every other audit row, including SEC-04 (systemd hardening), SEC-02 (HTTP bridge `0.0.0.0`), RISK-01, RISK-02.
- `hard_max_lots`, the sizing formula, `aggregate_open_risk`, the exposure caps — do not "improve" them while you are in the file.
- The running live process: do not stop, restart or reconfigure it.

**Relevant project docs / decisions:** `docs/audit-2026-07-30/02-AUDIT-REPORT.md` §9.3 (SEC-05) and §10.3 (OPS-07, "specs sanity"); `docs/audit-2026-07-30/07-VERIFICATION-AGAINST-LIVE-TREE.md` §1 and §3; `CLAUDE.md` — sizing is broker-spec driven and **fails safe to 0 when specs have not loaded**; that property is load-bearing and must still hold after this change.

> ⚠️ **Operator note, carry it into the session report:** changing the bind from `*` to `127.0.0.1` is only safe because WSL is in **mirrored** networking mode (the EA's `InpIP` is `127.0.0.1`). If the host is ever moved back to NAT mode the EA will not reach a loopback bind. The next restart after this lands must be validated with `scripts/check_bridge.py` **before** the bot is left unattended.

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] Premise confirmed in the report with citations: `bridge_zmq.py:25,36,53` still bind `tcp://*`, and `risk_manager.py:62–76` still coerces with `float()` and no bounds.
- [ ] `update_symbol_specs` rejects non-finite values, `ts ∉ [1e-6, 100]`, `val ∉ [1e-4, 1e4]`, `vm <= 0`, `vs <= 0`, and any >10× change from the last accepted value for that symbol.
- [ ] A rejected update is a no-op: previously accepted specs are unchanged, and a `RISK` event is logged naming symbol + field + value.
- [ ] A symbol whose only spec update was rejected still yields `calculate_lot_size(...) == 0.0` — the existing fail-safe is preserved, proven by a test that fails without the change.
- [ ] All three sockets bind the configured host (default `127.0.0.1`), proven by a test on the bind string; ports unchanged.
- [ ] New unit tests cover every rejection class plus the accepted-spec happy path, and the full suite is green (`VERIFY_CMD`).
- [ ] No MQL5 file and no other `src/` module modified.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
