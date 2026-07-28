---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S009"
date:          "2026-07-28"
slug:          "chain-protect-or-explicitly-adr-the"
parent_session: "none"
task_domain:   "data"
spec_state:    "approved"
status:        "DONE"
---

# titan-ict-bot — Session S009 · 2026-07-28 · "chain-protect-or-explicitly-adr-the"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** Widen the row_hash pre-image to chain-protect `actor` (owner-ratified via this spec's approval; pre-deployment, so zero migration cost)

**Why it matters / what it unblocks:** RS007 (finding 4) flagged that `actor` — who issued a command — is stored but not covered by `row_hash`, so `verify_chain` cannot detect a rewritten actor in `events.sqlite3` (`tradebot/core/event_log.py:37-44`; design at `pass3-systems.md` §1.1). M2's command-audit builds on `actor` for provenance (`pass3-systems.md` §8.5). Right now is the uniquely cheap moment to close it: no deployed/committed `events.sqlite3` exists and no golden chain hash is pinned anywhere (the same empty-blast-radius argument that justified S007's F-038 `canonical_json` change). At M2 the identical change would require a chain migration. **The owner has ratified widening now — the human approval of this spec IS that ratification** (the choice was put to the owner explicitly on 2026-07-28: widen-now vs defer-ADR; widen-now was chosen).

**Exact scope (what "doing this task" means):**
- `tradebot/core/event_log.py` `compute_row_hash` (:150-169): add an `actor: str` parameter between `ts_event` and `payload_json`; the pre-image becomes `SHA-256(prev_hash_bytes ‖ SEP seq ‖ SEP schema ‖ SEP schema_version ‖ SEP ts_event ‖ SEP actor ‖ SEP payload_json)` using the existing `\x1f` separator convention and UTF-8 encoding. Update the function's docstring to the seven-field form.
- Update BOTH call sites: the append path (:482) and `verify_chain`'s recompute (:619). If `verify_chain`'s row SELECT does not already fetch `actor`, add it to that column list — and nothing else — so the recompute has the stored value.
- TDD, red first: a regression test proving `UPDATE events SET actor='tampered' WHERE seq=1` currently leaves `verify_chain()` clean must be written and observed failing (asserting it raises) BEFORE the pre-image change, then pass after. Put it in `tests/unit/test_tradebot_event_log.py` beside the existing tamper tests.
- Move `actor` from "stored but unchained" to "chained" everywhere that boundary is pinned:
  - `tests/unit/test_tradebot_properties.py` `TestP4PreImageBoundary`: remove `actor` from `UNCHAINED` (leaving `event_id`, `ts_ingest`, `correlation_id`, `parent_ids`, `idempotency_key`) and update the class docstring, which currently names `actor` as the security-relevant reason the boundary was pinned.
  - Add `actor` as a DETECTED damage kind in the P4 tamper coverage (whichever module hosts the damage-kind list) so the new protection is fuzz-covered, not just unit-covered.
- Documentation that must agree with the new pre-image, updated in the same commit:
  - `tradebot/core/event_log.py` module docstring (:37-44) — `actor` leaves the unchained list.
  - `docs/TRADEBOT_CI.md` §2 ("P4 is bounded by the §1.1 pre-image" note).
  - `docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md` §1.1: amend the `row_hash` definition to the seven-field pre-image with a one-line dated amendment note ("amended 2026-07-28, S009, owner-ratified — actor chained pre-deployment"), and adjust the `actor` row's chained/unchained annotation if present.
- Create `docs/decisions/` and add `docs/decisions/0001-widen-row-hash-preimage-actor.md` recording: the gap; the decision (WIDEN NOW, owner-ratified 2026-07-28); the blast-radius proof (no committed `events.sqlite3` under version control, no pinned 64-hex chain hash in `tests/` — cite the actual grep commands run and their empty results); which columns deliberately REMAIN unchained (`event_id`, `ts_ingest`, `correlation_id`, `parent_ids`, `idempotency_key`) and why (delivery/bookkeeping metadata, not audit substance); and that this closes RS007 finding 4's carry by implementation rather than deferral.
- No `chain_format_version` / upcaster machinery: with zero existing logs there is nothing to version against. The decision record must state this reasoning explicitly so a future reader knows it was a considered omission, not an oversight.

**Explicitly OUT of scope (do NOT touch this session):**
- Chaining any of the other five stored-but-unchained columns — they stay out by design; the decision record explains why.
- `tradebot/core/events.py` (Envelope/schema registry/canonical_json), `tradebot/core/bus.py`, `sta.py`, `projection.py`, `recovery.py` — untouched. S008's seam checks (`archived_through_row_hash`, Parquet tail continuity) are hash-agnostic (they compare stored hashes, never recompute) and must not be modified.
- Anything under `src/`, `config/`, `main.py`, `scripts/`.
- Migration/re-hashing machinery of any kind. If the premise check below finds a committed or otherwise load-bearing `events.sqlite3` (or any pinned golden chain hash), STOP and report — the zero-blast-radius premise is dead and the defer-ADR path must be reconsidered by the owner.
- Editing `docs/trading-bot-brainstorm/brainstorm-v2/DECISIONS.md` (the ratified human decision sheet — closed; the new record lives in `docs/decisions/`).
- Editing `docs/sessions/_BACKLOG.md` or `_INDEX.md` — orchestrator-owned.

**Relevant project docs / decisions:** pass3-systems.md §1.1 (envelope/hash pre-image), §8.5 (command actor logging); RS007 finding 4 (docs/session-reviews/RS007.md); S007's F-038 fix as the pre-deployment-change precedent (docs/TRADEBOT_CI.md §2); S008's seam anchoring (RS008.md — do not disturb).

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] A regression test exists asserting `verify_chain()` raises `RecoveryRequired` after `UPDATE events SET actor='tampered'` on a chained row — and the session log/commit history shows it was observed RED (failing) against the old six-field pre-image before the widening landed (TDD, not retrofitted).
- [ ] `compute_row_hash` takes `actor` between `ts_event` and `payload_json`; both call sites (append, `verify_chain` recompute) pass the stored value; `hash(f7) != hash(f6)` trivially holds because every prior-format hash now mismatches — and no test needed updating to a hardcoded hash (proving no golden chain hash was pinned).
- [ ] `TestP4PreImageBoundary.UNCHAINED == ("event_id", "ts_ingest", "correlation_id", "parent_ids", "idempotency_key")` — `actor` removed — and its docstring no longer describes `actor` as unchained.
- [ ] `actor` tampering is covered as a detected damage kind in the P4 property fuzz, not only by the single unit test.
- [ ] `pass3-systems.md` §1.1 defines the seven-field pre-image with a dated S009 amendment note; `tradebot/core/event_log.py:37-44` and `docs/TRADEBOT_CI.md` §2 agree with it.
- [ ] `docs/decisions/0001-widen-row-hash-preimage-actor.md` exists with: the WIDEN-NOW decision + owner ratification date, the cited-and-empty blast-radius greps, the five deliberately-unchained columns with reasons, and the considered omission of format-version machinery.
- [ ] `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` fully green (620+ tests, no regressions).
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
