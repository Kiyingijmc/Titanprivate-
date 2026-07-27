# tradebot CI tiers + property tests (M0-6)

What exists after M0-6, what does not, and the one dependency decision this
milestone owed an answer to. Design source: `pass3-systems.md` §7 (testing
pyramid) and §8.6 (pipeline); milestone scope: `pass8-synthesis.md` §4.2 (M0).

## 1 · Pipeline tiers

`pass3-systems.md` §8.6 specifies the PR row as:

```
PR: ruff+mypy -> unit -> property (P1-P10) -> sim scenarios (§7.3)
    -> golden parity (pinned) -> build image
```

`.github/workflows/ci.yml` implements the tiers whose subject matter exists
today and declares the rest as named, commented placeholders. A tier that
passes without asserting anything is worse than a missing tier — it reads as
coverage the repo does not have.

| Tier | State | Blocked on |
|---|---|---|
| lint (ruff + mypy) | **not wired** | No lint config exists (`CLAUDE.md`: "There is no linter/build step configured"). Turning it on needs an agreed rule set plus a per-directory ratchet — `tradebot/` strict, inherited `src/` grandfathered — which is its own session. |
| unit (§7.1) | **wired, blocking** | — Runs `.mig/config`'s `VERIFY_CMD` verbatim, so CI and the mig session gate cannot disagree about "green". |
| property (§7.2) | **wired, blocking** | — P4–P8 + P11 groundwork. See §2. |
| sim scenarios (§7.3) | not wired | The §5 kernel (M1) and the risk/execution machinery every row of that table asserts against (M2). |
| golden parity (§5.6 / §7.5) | not wired | M1's frozen lake **and its committed manifest**. The v15 Plan-07 lesson applies directly: a gitignored manifest makes the parity job resolve nothing and pass. |
| build image | not wired | No Dockerfile; deployment topology (§8.1(b)) is still an open human decision. |
| nightly (chaos §7.4 · corruption drills · determinism · full golden) | not wired | Separate schedule-driven workflow; needs the docker-compose harness (core + simbroker + toxiproxy) built at M1. |

## 2 · Property invariants

`pass3-systems.md` §7.2 names P1–P10; `pass6-accounting.md` §6.3 adds P11–P14;
`pass7-innovation.md` adds P15. Live in `tests/unit/test_tradebot_properties.py`:

| ID | Invariant | Subject |
|---|---|---|
| P4 | Any mutation, row deletion or truncation of a chained log is detected — `verify_chain` never returns clean | `tradebot/core/event_log.py` |
| P5 | No transition out of a terminal state; a losing request resolves as a counted `race_loser`, never raises | `tradebot/core/sta.py` |
| P6 | Replaying a log twice — or one whose duplicate idempotency keys the writer dropped — yields identical projections | `tradebot/core/projection.py` |
| P7 | Equivalent params collide, distinct params never do (F-038) | `tradebot/core/events.py` `canonical_json` |
| P8 | `normalize_price` results always land exactly on the broker tick grid | `src/risk/risk_manager.py` |
| P11 | A posting balances exactly after half-even rounding to micro-units, residual absorbed by the largest line | groundwork: executable reference law |

Deferred with their subjects: **P1** (incremental == batch) and **P9** (BarClock
independence) need the feature engine — M1. **P2** (sizing), **P3** (ledger
conservation), **P10** (reconcile) need M2. **P12–P15** land with the money
engine and the shadow seam.

Two boundary notes worth carrying forward:

* **P8 targets `src/`, deliberately.** `pass3-systems.md` §6.1 marks Titan's
  sizing math **ADAPT** into `tradebot/risk/sizing.py` at M2. Pinning the
  invariant against the implementation that will be copied is what stops the
  copy arriving pre-broken. It is a *test* importing `src/`; no module under
  `tradebot/` does, so the M0 fence holds.
* **P4 is bounded by the §1.1 pre-image.** `row_hash` covers exactly
  `prev_hash | seq | schema | schema_version | ts_event | canonical_json(payload)`
  (`pass3-systems.md`:30). `event_id`, `ts_ingest`, `correlation_id`,
  `parent_ids`, `actor` and `idempotency_key` are stored but **unchained**, so
  editing them in the database is undetectable. `TestP4PreImageBoundary` pins
  that as the current design rather than leaving it implicit — it matters
  because §8.5 event-logs the commanding `actor`, and widening the pre-image is
  a schema-version change with an upcaster, which needs its own decision.

### F-038 defect found and fixed by P7

Writing P7 surfaced a real collision in `canonical_json`. The float branch fell
back to `f"{value:.17f}"` whenever `repr()` produced exponent notation
(|value| < 1e-4), which truncates at 17 decimal places: **every float below
~1e-17 rendered as the string `"0.0"`**, so `{n: 1e-20}` and `{n: 2e-20}` — two
genuinely different strategy params — hashed identically. That is exactly the
collision F-038 exists to forbid.

Fixed in `tradebot/core/events.py` by formatting `Decimal(value)` (the *exact*
binary value of the float) with `'f'`: lossless, injective, still free of
exponent notation. Regression guard:
`TestP7ParamsHash.test_sub_micro_floats_do_not_collapse_onto_one_string`.

This changes the canonical bytes of any payload holding a non-integral float
below 1e-4, and therefore its `row_hash`. No stored log is affected — M0 is a
skeleton with nothing deployed — but after M1 the same change would need a
chain migration, not an edit.

## 3 · Dependency decision: no `hypothesis`

The M0-6 backlog line flagged this explicitly ("hypothesis lib decision needed:
stdlib-only vs add hypothesis dep — flag at spec time per ask-before-new-deps
rule"), and `pass3-systems.md` §7.2 is headed "Property-based (hypothesis lib)".

**Decision: stdlib-only** — seeded `random.Random` plus `unittest.subTest`. No
new dependency; `requirements.txt` is unchanged.

Reasons, in order of weight:

1. `CLAUDE.md` requires asking before adding a dependency, and this session ran
   unattended. "Add a dep" is not a call an unattended session may make.
2. Every runner in this repo is stdlib `unittest`. `hypothesis`'s real value is
   shrinking and its `@given`/`@settings` decorators; its example database and
   deadline machinery add run-to-run variability that the mig verify gate reads
   as flake (this repo has already spent a session on one flake).
3. Fixed seeds make a CI failure reproducible from the seed alone, with no
   `.hypothesis` directory to ship or ignore.

**The cost, named:** no shrinking, so a counter-example arrives at full size;
and coverage is only as good as the hand-written generators. Neither bites yet
— P4–P8 have small, well-understood input spaces.

**Revisit at M1**, where P1 (incremental == batch across every feature node) is
the invariant that genuinely wants shrinking over long random bar streams. If
`hypothesis` is adopted then, adopt it as an ADR with the owner in the loop,
not in passing.
