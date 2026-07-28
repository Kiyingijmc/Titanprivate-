# 0001 — Widen the `row_hash` pre-image to chain-protect `actor`

- **Status:** Accepted
- **Date:** 2026-07-28
- **Session:** S009 (`chain-protect-or-explicitly-adr-the`)
- **Decided by:** owner (ratified 2026-07-28 by approving the S009 spec)
- **Supersedes/amends:** `docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md` §1.1
- **Closes:** RS007 finding 4 (`docs/session-reviews/RS007.md:74`) — by implementation, not deferral

## The gap

`pass3-systems.md` §1.1 originally defined the event-log row hash over six fields:

```
row_hash = SHA-256(prev_hash ‖ seq ‖ schema ‖ schema_version ‖ ts_event ‖ canonical_json(payload))
```

`tradebot/core/event_log.py` implemented that faithfully. The consequence, called out
in RS007 finding 4: `actor` — *who* issued the event — is stored in the `events` table
but sits outside the pre-image, so `EventLog.verify_chain()` cannot detect it being
rewritten. Anyone with write access to `events.sqlite3` could reassign a command from
`human:tg:<attacker>` to `core`, or vice versa, and the chain would still verify clean.

That matters more than the other unchained columns because `actor` is the *provenance*
field. §8.5 specifies that the interface→core command channel "event-logs the command
with actor before executing", and M2's command audit is built on exactly that record.
An audit trail whose subject can be silently edited is not an audit trail.

Two further properties made the gap easy to miss: `verify_chain`'s row `SELECT` did not
even fetch `actor` (nothing downstream needed it), and `TestP4PreImageBoundary` asserted
the gap as intended design — pinning it against silent drift, but also making it look
settled.

## Decision

**WIDEN NOW.** The pre-image becomes seven fields:

```
row_hash = SHA-256(prev_hash ‖ seq ‖ schema ‖ schema_version ‖ ts_event ‖ actor ‖ canonical_json(payload))
```

`actor` is inserted between `ts_event` and `payload_json`, using the existing `\x1f`
separator and UTF-8 encoding convention. `prev_hash` continues to enter as raw bytes.

The alternative considered was to defer: write an ADR recording the gap, leave the
six-field pre-image in place, and re-decide at M2. That was put to the owner explicitly
on 2026-07-28 alongside widen-now. Widen-now was chosen, because the deferral gets
strictly more expensive and never gets cheaper — see below.

## Why now: the blast radius is provably empty

Right now is the uniquely cheap moment. Changing a hash pre-image invalidates every
previously computed hash; the cost of that change is entirely a function of how many
hashes already exist. Today: none.

Evidence, from commands actually run in the S009 worktree before any edit:

```
$ find . -name 'events.sqlite3*' -not -path './.git/*'
(no output)

$ git ls-files | grep -i events
src/core/events.py
tests/unit/test_controller_events.py
tests/unit/test_events.py
tests/unit/test_tradebot_events.py
tradebot/core/events.py
        # no .sqlite3 / .db among them

$ grep -rlE "\b[0-9a-f]{64}\b" tests/ tradebot/ docs/TRADEBOT_CI.md
(no output)
```

So: **no `events.sqlite3` exists anywhere in the tree** — not deployed, not committed,
not fixture data. (The two tracked databases, `data/db/titan_core.db` and
`data/db/trade_state.db`, belong to the legacy `src/core/state_manager.py` and have no
hash chain.) And **no 64-hex literal appears in any test, module, or the CI doc**, so no
golden chain hash was pinned that a widening would silently invalidate. Every event log
in existence is created inside a `tempfile.TemporaryDirectory()` by a test and destroyed
at teardown.

The verification of that second point is not just the grep: the seven-field change
landed with **no test needing an update to a hardcoded hash**. Every test computes the
expectation through `compute_row_hash` itself, so a change of pre-image reaches them as
a signature change (caught at call time), never as a stale constant.

This is the same argument that justified S007's F-038 `canonical_json` fix — a hash
change made safe by the absence of anything already hashed. At M2, with a live log
under an audit obligation, the identical change would require a chain migration:
re-hash every historical row (destroying the tamper-evidence of the originals), or dual
verification paths keyed by a format version. Both are strictly worse than doing it
today, and neither buys anything the widening doesn't.

## What deliberately remains unchained

Five envelope columns stay outside the pre-image, and this is a choice, not an
oversight:

| Column | Why unchained |
|---|---|
| `event_id` | UUID7 identity assigned by the writer. Redundant with `seq`, which *is* chained and is the citable key; rewriting it defaces a debugging handle, not a fact. |
| `ts_ingest` | Commit-time bookkeeping. The audit-substantive timestamp is `ts_event` (when the fact became true), which is chained; `ts_ingest − ts_event` is a health metric (F-028), not a claim about the world. |
| `correlation_id` | Delivery/causality routing metadata. Tampering degrades traceability across a signal→order→position chain but cannot alter what any individual event asserts. |
| `parent_ids` | Same: a causal-graph edge list for debugging and replay ordering, not part of the event's assertion. |
| `idempotency_key` | Dedup bookkeeping enforced by a `UNIQUE` index at write time. Its integrity guarantee is the constraint, not the hash; a rewritten key cannot retroactively admit a duplicate that was already rejected. |

The dividing line: **audit substance is chained; delivery and bookkeeping metadata is
not.** `actor` crossed that line because it answers "who did this", which is the
substance of a command record. Widening the pre-image further is a §1.1 spec change and
needs its own decision record.

`TestP4PreImageBoundary` continues to pin this list, so the boundary cannot drift
silently in either direction.

## No format-version / upcaster machinery — a considered omission

No `chain_format_version` column, no per-version hash dispatch, no upcaster was added.

This was considered and rejected on the same ground that makes the widening cheap:
versioning exists to let new code read old data, and **there is no old data**. A
`chain_format_version` introduced now would be a column that is `1` on every row that
will ever exist, plus a branch that no input can reach — untested weight carrying an
implied promise (that format migration is a supported operation) which nothing
implements.

Recorded explicitly so a future reader knows the omission was deliberate. If the
pre-image ever needs to change again *after* a log is deployed, that session must build
the versioning machinery, and the absence of it here is precisely why it must.

## Consequences

- Every hash produced under the six-field pre-image now mismatches. Since no such hash
  is persisted anywhere, this is a no-op in practice.
- `compute_row_hash` gains a required `actor` parameter — a signature change, so any
  caller not updated fails loudly at call time rather than silently hashing wrong.
- `verify_chain`'s row `SELECT` now fetches `actor` so the recompute sees the stored
  value; a rewritten `actor` surfaces as the existing
  `"row_hash does not match the row contents"` refusal.
- S008's archive/live seam checks (`archived_through_row_hash`, Parquet tail continuity)
  are unaffected: they compare *stored* hashes and never recompute a pre-image, so they
  are hash-agnostic by construction. They were not modified.
- `actor` tampering is now covered twice: as a fuzz damage kind in
  `TestP4HashChainDetectsAnyMutation`, and by the unit drill
  `test_rewritten_actor_is_refused`.

## Files changed

- `tradebot/core/event_log.py` — pre-image, both call sites, `verify_chain` `SELECT`, module docstring
- `tests/unit/test_tradebot_event_log.py` — `test_rewritten_actor_is_refused` (written red first), two `compute_row_hash` call sites
- `tests/unit/test_tradebot_properties.py` — `actor` added to P4 damage kinds, removed from `TestP4PreImageBoundary.UNCHAINED`
- `docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md` §1.1 — amended definition + dated note
- `docs/TRADEBOT_CI.md` §2 — P4 boundary note
