# titan-ict-bot — idea backlog (ideas hold a slug, never a session number)

<!-- MIG-BACKLOG-TABLE -->
| slug | track | status | source | needs | unblocks | added | desc |
|------|-------|--------|--------|-------|----------|-------|------|
| fix-plan-06-flake-test-research | ? | promoted | brainstorm |  |  | 2026-07-18 | fix Plan-06 flake: test_research_run spread/net_r — SHARPENED DIAGNOSIS (S001 gate, 2026-07-19): fails deterministically in isolation in a worktree WITHOUT untracked data/specs.json but passed in isolation on main checkout WITH it => spec resolution reads data/specs.json; fix = hermetic spec fixture + tearDown reset. Related: commit-or-discard-untracked-data-specs |
| featurebus-bar-index-single-counter-defect | ? | inbox | brainstorm |  |  | 2026-07-18 | FeatureBus _bar_index single-counter defect — REQUIRED fix before any M5 strategy (per v15 advisory) |
| intent-arbiter-priority-is-hardcoded-make | ? | inbox | brainstorm |  |  | 2026-07-18 | Intent Arbiter priority is hardcoded — make config-driven (v15 Plan 07+ advisory) |
| cross-symbol-exposure-cap-missing-v15 | ? | inbox | brainstorm |  |  | 2026-07-18 | cross-symbol exposure cap missing (v15 Plan 10 advisory) |
| m0-1-tradebot-skeleton-top-level | S | promoted | brainstorm |  |  | 2026-07-18 | M0-1 tradebot skeleton: top-level tradebot/ package + pyproject + config/schema.py (pydantic: hard caps, F-034 risk re-clamp, F-017 correlation-group memberships, F-036 binding-order report, live/next-signal/restart reload classes); acceptance = rejects every pass1 register counter-example. Spec: brainstorm-v2/pass8 M0 + pass3 SS6.1 |
| m0-2-tradebot-core-clock-py | S | promoted | brainstorm | m0-1-tradebot-skeleton-top-level |  | 2026-07-18 | M0-2 tradebot core/clock.py (Clock protocol, LiveClock monotonic+NTP, SimClock) + core/events.py (envelope: seq/causality/idempotency/schema-version, registry, canonical JSON, upcasters); acceptance = same-input determinism, identical stream twice => identical serialization. Spec: pass3 SS1 |
| m0-3-tradebot-core-event-log | S | promoted | brainstorm | m0-2-tradebot-core-clock-py |  | 2026-07-18 | M0-3 tradebot core/event_log.py: sole-writer chained SQLite log (seq + prev_hash/row_hash), snapshots every 10k/24h, archive, backup + restore-verify job; acceptance = 5 corruption drills (truncate, payload bit-flip, hash bit-flip, row delete, sidecar corrupt) each produce RECOVERY_REQUIRED, never a clean boot. RISKY-ADJACENT: this is the money-truth substrate. Spec: pass3 SS1.3 |
| m0-4-tradebot-core-projection-py | S | promoted | brainstorm | m0-3-tradebot-core-event-log |  | 2026-07-18 | M0-4 tradebot core/projection.py (state=fold(events)) + core/recovery.py (verify_and_replay boot sequence) + sole-writer enforcement; acceptance = second-writer attempt fails a test, chain-head determinism. Spec: pass3 SS1.3-1.4 |
| m0-5-tradebot-core-bus-py | S | promoted | brainstorm | m0-2-tradebot-core-clock-py |  | 2026-07-18 | M0-5 tradebot core/bus.py (ADAPT src/core/bus.py: keep sync deterministic delivery + stats; ADD critical-tier subscribers never circuit-broken, exception=halt+alert) + core/sta.py Signal Transition Actor skeleton. Spec: pass3 SS2.1 + SS6.1 |
| m0-6-tradebot-ci-skeleton-property | S | promoted | brainstorm | m0-1-tradebot-skeleton-top-level |  | 2026-07-18 | M0-6 tradebot CI skeleton + property tests P4-P8 + P11 groundwork (hypothesis lib decision needed: stdlib-only vs add hypothesis dep — flag at spec time per ask-before-new-deps rule). Spec: pass3 SS7 |
| hash-anchor-the-archive-live-seam | S | promoted | review-carry |  |  | 2026-07-27 | hash-anchor the archive<->live seam in event_log.verify_chain: _write_parquet stores chain_last_row_hash in the Parquet metadata and NOTHING ever reads it, so after an archive the retained log is anchored on a seq watermark only. RS004 MINOR. This is why the S004 MAJOR (archive holding a different history at the same seqs) was undetectable rather than merely refusable — the row_hash check added in e012d6e refuses at write time, but a verify_chain() after archiving still cannot prove the retained chain continues the archived one. Fenced out of m0-4/S005 because that spec forbids touching event_log.py. |
| chain-protect-or-explicitly-adr-the | S | promoted | review-carry |  |  | 2026-07-28 | chain-protect or explicitly ADR the unchained actor column before M2 command-audit — RS007 carry: actor sits outside the §1.1 row_hash pre-image, so who-issued-a-command is rewritable in events.sqlite3 without verify_chain noticing; widening the pre-image is a schema-version + upcaster decision (pass3 §8.5 logs the commanding actor for every interface→core command) |
<!-- /MIG-BACKLOG-TABLE -->

## Promoted
<!-- MIG-PROMOTED-LOG -->
- m0-1-tradebot-skeleton-top-level → minted S001 (2026-07-18)
- fix-plan-06-flake-test-research → minted S002 (2026-07-19)
- m0-2-tradebot-core-clock-py → minted S003 (2026-07-27)
- m0-3-tradebot-core-event-log → minted S004 (2026-07-27)
- m0-4-tradebot-core-projection-py → minted S005 (2026-07-27)
- m0-5-tradebot-core-bus-py → minted S006 (2026-07-27)
- m0-6-tradebot-ci-skeleton-property → minted S007 (2026-07-27)
- hash-anchor-the-archive-live-seam → minted S008 (2026-07-28)
- chain-protect-or-explicitly-adr-the → minted S009 (2026-07-28)
- mig-cannot-retire-backlog-rows-delivered → minted S010 (2026-07-28)
- retired commit-or-discard-the-untracked-test (delivered by commit 2ae4dbb) — mig triage 2026-07-28
- retired wire-scripts-gui-demo-server-py (delivered by commit a9e678f) — mig triage 2026-07-28
- retired commit-or-discard-untracked-data-specs (delivered by commit d05efd3) — mig triage 2026-07-28
- retired decide-fate-of-docs-trading-bot (delivered by commit 3979ade) — mig triage 2026-07-28
- retired mig-cannot-retire-backlog-rows-delivered (delivered by commit 17d4e76) — mig triage 2026-07-28
<!-- /MIG-PROMOTED-LOG -->
