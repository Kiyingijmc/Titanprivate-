# titan-ict-bot — idea backlog (ideas hold a slug, never a session number)

<!-- MIG-BACKLOG-TABLE -->
| slug | track | status | source | needs | unblocks | added | desc |
|------|-------|--------|--------|-------|----------|-------|------|
| commit-or-discard-the-untracked-test | ? | inbox | brainstorm |  |  | 2026-07-18 | commit or discard the untracked test tests/unit/test_check_bridge_ip.py |
| wire-scripts-gui-demo-server-py | ? | inbox | brainstorm |  |  | 2026-07-18 | wire scripts/gui_demo_server.py into the frontend dev workflow or delete |
| fix-plan-06-flake-test-research | ? | promoted | brainstorm |  |  | 2026-07-18 | fix Plan-06 flake: test_research_run spread/net_r — SHARPENED DIAGNOSIS (S001 gate, 2026-07-19): fails deterministically in isolation in a worktree WITHOUT untracked data/specs.json but passed in isolation on main checkout WITH it => spec resolution reads data/specs.json; fix = hermetic spec fixture + tearDown reset. Related: commit-or-discard-untracked-data-specs |
| commit-or-discard-untracked-data-specs | ? | inbox | brainstorm |  |  | 2026-07-18 | commit or discard untracked data/specs.json (broker spec cache from check_bridge session) |
| featurebus-bar-index-single-counter-defect | ? | inbox | brainstorm |  |  | 2026-07-18 | FeatureBus _bar_index single-counter defect — REQUIRED fix before any M5 strategy (per v15 advisory) |
| decide-fate-of-docs-trading-bot | ? | done | brainstorm |  |  | 2026-07-18 | DELIVERED 2026-07-18 (commit 3979ade): docs/trading-bot-brainstorm/ (00-05 + brainstorm-v2 passes 1-8 + INDEX.md) committed to main |
| intent-arbiter-priority-is-hardcoded-make | ? | inbox | brainstorm |  |  | 2026-07-18 | Intent Arbiter priority is hardcoded — make config-driven (v15 Plan 07+ advisory) |
| cross-symbol-exposure-cap-missing-v15 | ? | inbox | brainstorm |  |  | 2026-07-18 | cross-symbol exposure cap missing (v15 Plan 10 advisory) |
| m0-1-tradebot-skeleton-top-level | S | promoted | brainstorm |  |  | 2026-07-18 | M0-1 tradebot skeleton: top-level tradebot/ package + pyproject + config/schema.py (pydantic: hard caps, F-034 risk re-clamp, F-017 correlation-group memberships, F-036 binding-order report, live/next-signal/restart reload classes); acceptance = rejects every pass1 register counter-example. Spec: brainstorm-v2/pass8 M0 + pass3 SS6.1 |
| m0-2-tradebot-core-clock-py | S | promoted | brainstorm | m0-1-tradebot-skeleton-top-level |  | 2026-07-18 | M0-2 tradebot core/clock.py (Clock protocol, LiveClock monotonic+NTP, SimClock) + core/events.py (envelope: seq/causality/idempotency/schema-version, registry, canonical JSON, upcasters); acceptance = same-input determinism, identical stream twice => identical serialization. Spec: pass3 SS1 |
| m0-3-tradebot-core-event-log | S | promoted | brainstorm | m0-2-tradebot-core-clock-py |  | 2026-07-18 | M0-3 tradebot core/event_log.py: sole-writer chained SQLite log (seq + prev_hash/row_hash), snapshots every 10k/24h, archive, backup + restore-verify job; acceptance = 5 corruption drills (truncate, payload bit-flip, hash bit-flip, row delete, sidecar corrupt) each produce RECOVERY_REQUIRED, never a clean boot. RISKY-ADJACENT: this is the money-truth substrate. Spec: pass3 SS1.3 |
| m0-4-tradebot-core-projection-py | S | inbox | brainstorm | m0-3-tradebot-core-event-log |  | 2026-07-18 | M0-4 tradebot core/projection.py (state=fold(events)) + core/recovery.py (verify_and_replay boot sequence) + sole-writer enforcement; acceptance = second-writer attempt fails a test, chain-head determinism. Spec: pass3 SS1.3-1.4 |
| m0-5-tradebot-core-bus-py | S | inbox | brainstorm | m0-2-tradebot-core-clock-py |  | 2026-07-18 | M0-5 tradebot core/bus.py (ADAPT src/core/bus.py: keep sync deterministic delivery + stats; ADD critical-tier subscribers never circuit-broken, exception=halt+alert) + core/sta.py Signal Transition Actor skeleton. Spec: pass3 SS2.1 + SS6.1 |
| m0-6-tradebot-ci-skeleton-property | S | inbox | brainstorm | m0-1-tradebot-skeleton-top-level |  | 2026-07-18 | M0-6 tradebot CI skeleton + property tests P4-P8 + P11 groundwork (hypothesis lib decision needed: stdlib-only vs add hypothesis dep — flag at spec time per ask-before-new-deps rule). Spec: pass3 SS7 |
| mig-cannot-retire-backlog-rows-delivered | S | inbox | discovered |  |  | 2026-07-27 | mig cannot retire backlog rows delivered outside a session: _slug_delivered (mig:142) only recognises DONE sessions in _INDEX, and triage Cat-1 auto-retire (mig:1474) only deletes rows already status=done whose _row_cited_id matches a session id — commit SHAs never match, so the hand-set 'decide-fate-of-docs-trading-bot' row is permanently stuck. Needs a 'mig backlog done <slug> --by <sha>' path. Rows awaiting it: commit-or-discard-the-untracked-test + wire-scripts-gui-demo-server-py + commit-or-discard-untracked-data-specs (all delivered 2026-07-27 by 2ae4dbb/a9e678f/d05efd3) |
<!-- /MIG-BACKLOG-TABLE -->

## Promoted
<!-- MIG-PROMOTED-LOG -->
- m0-1-tradebot-skeleton-top-level → minted S001 (2026-07-18)
- fix-plan-06-flake-test-research → minted S002 (2026-07-19)
- m0-2-tradebot-core-clock-py → minted S003 (2026-07-27)
- m0-3-tradebot-core-event-log → minted S004 (2026-07-27)
<!-- /MIG-PROMOTED-LOG -->
