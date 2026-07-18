---
# ── MACHINE-READABLE PROVENANCE (the ledger reads this — do not delete) ──
session_id:    "S001"
date:          "2026-07-18"
slug:          "m0-1-tradebot-skeleton-top-level"
parent_session: "none"
task_domain:   "models"
spec_state:    "approved"
status:        "DRAFT"
---

# titan-ict-bot — Session S001 · 2026-07-18 · "m0-1-tradebot-skeleton-top-level"

## 0 · CONTEXT LOAD (first, silently)
Read this project's authority docs (CLAUDE.md / README / docs/) and `.mig/config`.
The project's own rules override anything generic in this prompt.

## 2 · THE ONE TASK (scope is sacred)

**Task title:** M0-1: `tradebot/` package skeleton — pyproject + `config/schema.py` (Pydantic caps, F-034/F-017/F-036, reload classes)

**Why it matters / what it unblocks:** This is the first brick of the new-bot M0 milestone (pass8-synthesis.md §4.2): a trustworthy config layer that structurally forecloses the three Pass-1 register findings (F-034 vol-scalar cap breach, F-017 gross/net limit ambiguity, F-036 dead-limit invisibility) before any engine code depends on it. Nothing in M0/M1 (event log, clock, feature registry) can be wired to real risk numbers until this schema exists and is proven to reject the known bad configs.

**Exact scope (what "doing this task" means):**
- Create top-level `tradebot/` Python package (sibling to `src/`, `tests/`, per the tree in `docs/trading-bot-brainstorm/brainstorm-v2/pass3-systems.md` §6.1) with `tradebot/__init__.py` and `tradebot/config/__init__.py`.
- Add `tradebot/pyproject.toml` (or a root-level one scoped to the package — match whatever `python -m build`/`pip install -e` convention the repo already uses for `src/`; if none exists, use a minimal PEP 621 `[project]` table) declaring the package and its runtime deps needed *by this session only*: `pydantic` (v2). Do not add fastapi/uvicorn/httpx/pyarrow/etc. yet — those belong to later M0/M1 scope per the §6.1 tree; this session is schema-only.
- Implement `tradebot/config/schema.py` as Pydantic v2 models covering exactly the fields pass8 M0 assigns to this file:
  - **Per-trade risk cap + F-034 re-clamp**: a risk model with `risk_pct` and a `vol_scalar` range `[0.5, 1.5]` (pass3-systems.md §2.6 limit #1) plus a `hard_cap` (default 1.0%), with a Pydantic model-validator enforcing `effective_risk = min(risk_pct * vol_scalar, hard_cap)` — i.e. the *composed* max must never exceed `hard_cap`, closing F-034 (pass1-audit.md F-034: T3 at 1.0% × 1.5 vol_scalar must not silently approve 1.5%).
  - **F-017 correlation-group / asset-class membership**: every instrument entry declares exactly one `asset_class` (validated against a closed enum/list) and zero-or-more `correlation_groups` (validated against a declared group list); each limit-stack row declares its `gross`/`net` counting mode explicitly (schema fields only for this session — the runtime aggregation engine is `risk/ledger.py`, later milestone). Reject configs where an instrument's `asset_class` isn't declared, or a `correlation_groups` entry isn't in the declared group set.
  - **F-036 binding-order report**: a schema-level (not runtime-ledger) validator/helper that, given the configured limit values (per-trade %, per-instrument %, per-asset-class %, per-correlation-group %, account-total %, max-positions), computes which limits can mathematically bind and which are dead (pass3-systems.md §2.6: "12 × 0.5% = 6% < 8%" example) and surfaces this as a structured report (e.g. a `BindingOrderReport` model/method), matching the wording pattern in pass3 §2.6 / pass5-interfaces.md ("limit #7 dead under current #1/#11").
  - **Reload-class tagging**: a mechanism (e.g. a `Literal["live","next-signal","restart"]` field or per-field metadata) tagging each top-level config field/section with its reload class per `docs/trading-bot-brainstorm/04-architecture-config.md` §B4 (Live: modes/enable-disable/risk %/timeouts/notification prefs; Next-signal: child params/instrument lists; Restart: timeframes/feature-graph/adapter/process topology).
  - **Hard caps**: enforce the per-trade hard cap (1.0%) and any other numeric range caps named in pass3-systems.md §2.6's limit table (#1–#11) that are schema-expressible today (ranges/types/existence checks) — do not implement the runtime ledger aggregation (Σrisk, gross/net totals across live positions); that's `risk/ledger.py`, a later M2 deliverable.
- Add unit tests under `tests/unit/tradebot/test_config_schema.py` (so `VERIFY_CMD` — `unittest discover -s tests/unit` — picks them up) that construct the exact Pass-1 register counter-examples and assert rejection/correct behavior:
  - F-034: a child at `risk_pct=1.0%` with `vol_scalar=1.5` must validate to `effective_risk == 1.0%` (clamped), not 1.5%.
  - F-017: an instrument declared in two overlapping ways that the register flags (e.g. gold in `metal` asset_class *and* `safe_haven` correlation_group; NAS100 in `index` asset_class *and* `risk_on` correlation_group) must be *accepted* only if each instrument still resolves to exactly one asset_class (multiple correlation_group memberships are legal — that's the "zero-or-more" design); an instrument with zero or two asset_classes must be *rejected*.
  - F-036: given the pass3 §2.6 default numbers (12 max positions × 0.5% per-trade cap = 6%, vs 8% account-total cap), the binding-order report must flag the account-total limit as dead, matching the documented example.

**Explicitly OUT of scope (do NOT touch this session):**
- Any code under `core/`, `features/`, `risk/ledger.py`, `risk/sizing.py`, `execution/`, `strategies/`, `calendar_svc/`, `interfaces/`, `ops/`, `research/` (all later M0/M1/M2 scope per pass3 §6.1).
- `config/defaults.yaml` and `config/broker/` overlay files — this session is the Pydantic schema only, not the shipped default config values or broker-discovery overlay mechanism.
- The runtime limit-stack *ledger* / aggregation engine (Σ risk across live positions, breaker wiring) — that's `risk/ledger.py` (M2).
- CAL-row-sourced ranges (calendar-service-derived validation ranges) mentioned in the same pass8 M0 bullet — deferred until `calendar_svc/` exists (M1); do not stub calendar coupling here.
- Any change to the existing Titan v14 bot (`src/`, `config/config.yaml`, `main.py`) — `tradebot/` is a new, separate top-level package and must not import from or modify `src/`.
- CI pipeline wiring, event log, clock, or bus code (separate M0 bullets, separate sessions).

**Relevant project docs / decisions:** brainstorm-v2/pass8-synthesis.md §4.2 (M0); pass3-systems.md §2.6 (limit stack) and §6.1 (repo tree); pass1-audit.md F-017/F-034/F-036; 04-architecture-config.md §B3–B4

> Premise check (blocking): before any edit, confirm the gap this task asserts
> still exists in the live tree (cite file:line). Stale premise → STOP and report;
> never invert an edit to force the diff to match the prompt.

## 4 · DEFINITION OF DONE (testable checklist for THIS task)

- [ ] `tradebot/` package exists with `__init__.py` and `config/schema.py`; importable via `.venv/bin/python -c "import tradebot.config.schema"` with no errors.
- [ ] `pyproject.toml` for the package exists and declares `pydantic` as a dependency; `pydantic` is installed in `.venv` (or added to `requirements.txt` if that's how deps are managed here) and the schema module imports successfully.
- [ ] `tests/unit/tradebot/test_config_schema.py` exists and its F-034 counter-example test fails (raises/clamps as expected) against a naive `risk_pct * vol_scalar` implementation, proving the test has teeth, then passes against the re-clamped implementation.
- [ ] F-017 counter-example tests pass: overlapping correlation-group membership is accepted, but multi/zero asset-class membership is rejected.
- [ ] F-036 binding-order report test passes: the pass3 §2.6 default numbers correctly identify the account-total limit as dead.
- [ ] Every field/section in the schema carries a reload-class tag matching 04-architecture-config.md §B4's three-way split (live / next-signal / restart).
- [ ] `VERIFY_CMD` (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`) passes clean, including the new `tests/unit/tradebot/` tests, with zero regressions to existing Titan v14 tests.
- [ ] No files under `src/`, `config/config.yaml`, or `main.py` touched; new files confined to `tradebot/` and `tests/unit/tradebot/`.
- [ ] Changes committed forward-only, by explicit path; no out-of-scope files touched.
