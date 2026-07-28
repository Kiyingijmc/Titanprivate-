---
name: mig
description: Drive the mig session-chain orchestrator in titan-ict-bot — backlog, spec gate, gated headless builds. Use when asked to add ideas, promote/spec/approve sessions, run the loop, or check status.
---
# mig workflow (titan-ict-bot)

Idea → build, two human gates (spec approve + merge gate):
  mig idea "<desc>" [--track T]     add to the backlog
  mig backlog done <slug> --by <sha>  mark a row delivered by a plain commit (no session); triage retires it
  mig triage · mig digest           ranked board / founder analytics
  mig auto <track>                  promote top-ranked + model-draft its spec
  mig spec <ID> · mig approve <ID>  draft / human-approve §2+§4
  mig run <track>                   build → verify → review → (remediate → re-review) → gate
  mig confirm|pause|reject <ID>     act on an armed gate · mig tick drives countdowns
  mig status · mig doctor           board · requirements/preflight check

Invariants (do not violate in any session):
- Never hand-edit _INDEX.md, archive/, pointer files, or _BACKLOG.md — mig owns them.
- The requirements gate (.mig/requirements) must pass before run/start.
- Risky domains and non-PASS outcomes never auto-proceed; a human confirms.
