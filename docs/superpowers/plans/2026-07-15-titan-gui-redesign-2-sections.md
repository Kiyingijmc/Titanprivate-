# Titan GUI Redesign — Plan 2: Sections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the real section pages — Overview, Positions, Strategies, Activity, Settings — on the branded Foundation shell, wire the ⌘K command actions and the read-only-on-403 flip, and add the section-level robustness (Panel states from the connection machine, filters, virtualization). Deliverable: a complete, branded, robust redesigned cockpit.

**Architecture:** COMPOSE, don't rewrite. The Phase-1b component logic (`StatTiles`, `EquitySparkline`, `PositionsTable`, `Controls`, `EventFeed`, `StrategiesTab`, `SettingsTab`) already exists, is tested, and is reused — each section page wraps the relevant component(s) in a `<Panel>` (deriving loading/empty/error/stale from `connectionStatus`), feeds it live data from `ControllerContext`, and adds the section's specific robustness (Positions filter/sort, Activity virtualization/filter, Settings grouping/search). The section STUBS from Plan 1 are replaced. Mutations route through the existing confirm-gate / typed-id-promote flows; any `ApiError.kind==="readOnly"` (403) flips `ReadOnlyContext`.

**Tech Stack:** Same as Plan 1 (React/TS/Tailwind/shadcn/Vitest); `@tanstack/react-virtual` (already a dep) for the Activity feed.

**Spec:** `docs/superpowers/specs/2026-07-15-titan-gui-redesign-design.md` (§5 sections, §6 robustness).

## Global Constraints

- Work on `feat/gui-redesign` in the isolated worktree (main tree is the user's — never touch). BRANCH GUARD every implementer. No git remote, no merge to main.
- **No backend changes.** Reuse the existing `api` (ControllerContext) + backend contract. Python untouched.
- **Reuse the Phase-1b components** in `frontend/src/components/` (HealthStrip, StatTiles, EquitySparkline, PositionsTable, Controls, EventFeed, StrategiesTab, SettingsTab) — read each before wiring; do NOT duplicate their logic. Restyle to the new brand tokens ONLY where a component still hardcodes an off-brand value (they use role-token classes via the back-compat Tailwind aliases, so most already inherit the brand — verify visually in the live-drive, fix specific mismatches).
- **Design tokens are the brand set** (violet accent, Instrument Sans/JetBrains Mono) — components use role-token Tailwind classes, never raw hex; Lucide icons never emoji.
- **Robustness (spec §6):** every section wraps its content in `<Panel status=...>` where status is derived from `connectionStatus` + the data (loading before first snapshot, empty when no rows, stale when `connectionStatus.stale`, error+retry on an `api` fetch failure). Read-only disables every mutating control. Phone = read-only glance (Overview/Positions/Activity only; mutations hidden — already handled by BottomTabs + read-only, verify).
- Tests: run ONLY the task's test file(s) via `cd frontend && npx vitest run <file>` (env SLOW ~70-90s/run; FOREGROUND, timeout 600000; NO background+Monitor). Stage only the task's files (explicit `git add`, never `-A`).
- Commit trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

## Available to consume (committed)

- `ControllerContext` → `useController()` = `{ snapshot: Snapshot|null, events: FeedEvent[], connectionStatus: ConnectionState, api: Api }`.
- `useReadOnly()` = `{ readOnly, setReadOnly }`.
- `<Panel status title? actions? onRetry? emptyMessage? children />` (loading/empty/error/populated/stale).
- Phase-1b components (read each for its exact props):
  - `<StatTiles account arbiter dayPnl openCount />`
  - `<EquitySparkline points={{t,equity}[]} />`
  - `<PositionsTable positions onClose readOnly />`
  - `<Controls api paused readOnly onResult />` (onResult: `{readOnly?:true; error?:string}`)
  - `<EventFeed events />`
  - `<StrategiesTab api readOnly />`
  - `<SettingsTab api readOnly />`
- `api` methods: `getState/getEvents/getHistory/getSettings/getRegistry/postCommand/patchSetting/registryAction`; `ApiError{status,kind}` (kind: unauthorized|throttled|readOnly|validation|error).
- `<CommandPalette open onOpenChange actions />` + `PaletteAction{id,label,run,destructive?,disabled?}` (AppShell renders it with an `actions` array — currently empty).

---

### Task 1: Read-only-403 flip + a shared section-data helper

**Files:** Create `frontend/src/lib/useMutation.ts` (or `frontend/src/lib/mutations.ts`), `frontend/src/lib/useMutation.test.ts`; Modify `frontend/src/context/ControllerContext.tsx` if needed to expose a mutate helper.

**Interfaces:**
- Produces: `useMutate()` → `run(fn: () => Promise<T>) => Promise<{ ok: true; value: T } | { ok: false; error: string }>` that: calls `fn`; on `ApiError.kind==="readOnly"` calls `useReadOnly().setReadOnly(true)` and returns `{ok:false, error:"read-only"}`; on other errors returns `{ok:false, error: detail}`; on success `{ok:true, value}`. Central place so every mutating surface routes 403 → read-only flip consistently.

- [ ] **Step 1: failing test** — `useMutation.test.ts` (renderHook within `<ReadOnlyProvider>`): a `fn` that rejects with `{status:403, kind:"readOnly"}` → `run` returns `{ok:false}` AND the provider's `readOnly` becomes true; a `fn` rejecting `{kind:"error", detail:"boom"}` → `{ok:false, error:"boom"}` and readOnly stays false; a resolving `fn` → `{ok:true, value}`.
- [ ] **Step 2–4:** fail → implement `useMutate` (uses `useReadOnly`; type-guards `ApiError`) → pass.
- [ ] **Step 5: Commit** — `feat(gui-fe2): useMutate — central 403→read-only flip + error surfacing` (+trailer).

---

### Task 2: Overview page

**Files:** Modify `frontend/src/sections/OverviewPage.tsx`; Test `frontend/src/sections/OverviewPage.test.tsx`.

**Interfaces:**
- Consumes: `useController`, `StatTiles`, `EquitySparkline`, `Controls`, `useMutate`, `<Panel>`, react-router `Link`.
- Produces: the at-a-glance Overview (spec §5): a KPI row (`StatTiles` fed from `snapshot.account`/`arbiter`, `dayPnl = equity - balance`, `openCount = positions.length`); an equity `EquitySparkline` (fed by a rolling buffer of `snapshot.account.equity` — move the buffer logic here or into a `useEquityBuffer` hook, capped ~120, deterministic x via a ref counter — NO Date.now in render); a **compact top-positions** summary (top 3 positions by |pnl|, each a row linking to `/positions`); a **recent-activity** strip (last 4 `events`, linking to `/activity`); and the global `Controls` (pause/resume/close-all/panic — read-only aware). Each block in a `<Panel>` with connection-derived status (loading before first snapshot; stale when `connectionStatus.stale`).

- [ ] **Step 1: failing test** — `OverviewPage.test.tsx` (render within `MemoryRouter` + `ReadOnlyProvider` + a `ControllerContext.Provider` seeded with a snapshot of 2 positions + a couple events; mock `api`): asserts the KPI tiles render (equity value), the top-positions summary shows a position symbol, the recent-activity strip shows an event topic, and (read-only) the Controls buttons are disabled.
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5: Commit** — `feat(gui-fe2): Overview page — KPIs + equity + top-positions + recent-activity + controls` (+trailer).

---

### Task 3: Positions page

**Files:** Modify `frontend/src/sections/PositionsPage.tsx`; Create `frontend/src/components/PositionsFilters.tsx` (small filter/sort bar); Test `frontend/src/sections/PositionsPage.test.tsx`.

**Interfaces:**
- Consumes: `useController`, `PositionsTable`, `useMutate`, `<Panel>`, shadcn Input/Select.
- Produces: the full Positions section: a filter bar (text filter by symbol; side filter BUY/SELL/all; sort by pnl/symbol/lots) above `PositionsTable`; the table shows `snapshot.positions` filtered/sorted; per-row close routes `api.postCommand({command:"close", ticket})` through `useMutate` (403→read-only), with a confirm; a **Close All** action (confirm) via `Controls` or a button. `<Panel>` status: loading before first snapshot, empty ("No open positions") when zero, stale marker when `connectionStatus.stale`. Read-only disables close/close-all. (Sticky header; virtualization is optional here — add only if trivial, else note as deferred since position counts are small.)

- [ ] **Step 1: failing test** — `PositionsPage.test.tsx`: seed a snapshot with 3 positions (2 EURUSD BUY, 1 XAUUSD SELL); filtering by "XAU" shows only the SELL row; the side filter "BUY" shows 2; empty positions → "No open positions"; per-row close (not read-only) calls `api.postCommand({command:"close", ticket})`; read-only disables the close button.
- [ ] **Step 2–4:** fail → implement (filter/sort in a `useMemo`; reuse `PositionsTable`) → pass.
- [ ] **Step 5: Commit** — `feat(gui-fe2): Positions page — filter/sort bar + table + close/close-all (read-only aware)` (+trailer).

---

### Task 4: Strategies page

**Files:** Modify `frontend/src/sections/StrategiesPage.tsx`; Test `frontend/src/sections/StrategiesPage.test.tsx`.

**Interfaces:**
- Consumes: `useController` (for `api`), `StrategiesTab` (reused — it already loads via `api.getRegistry`, renders status/state badges, enable/disable, typed-id promote), `useReadOnly`, `<Panel>`.
- Produces: the Strategies section = `StrategiesTab` wrapped in a `<Panel title="Strategies">`, with `readOnly` from `useReadOnly()`. StrategiesTab already handles the registry table + promote gate; this task WIRES it (feeds `api`, `readOnly`) and ensures its mutations route 403 → read-only (via `useMutate` inside StrategiesTab OR a small onResult-style callback — if StrategiesTab swallows 403 internally, add a `onReadOnly` prop and call `setReadOnly`; keep the change minimal). Verify research rows are visually distinct + promote requires the typed id (existing behavior).

- [ ] **Step 1: failing test** — `StrategiesPage.test.tsx`: with a mocked `api.getRegistry` returning one research strategy, the page renders it (id) inside a titled Panel; a `getRegistry` rejection → the Panel error state with Retry. (Promote/enable behavior is covered by the reused `StrategiesTab.test`; here assert the page-level wiring + Panel states.)
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5: Commit** — `feat(gui-fe2): Strategies page — registry table + promote wired with Panel states` (+trailer).

---

### Task 5: Activity page (virtualized + filter)

**Files:** Modify `frontend/src/sections/ActivityPage.tsx`; Test `frontend/src/sections/ActivityPage.test.tsx`.

**Interfaces:**
- Consumes: `useController` (`events`), `EventFeed` (reused — renders topic rows + violet IntentBlocked rule chips + aria-live), `@tanstack/react-virtual`, shadcn Select, `<Panel>`.
- Produces: the full Activity feed: a **type filter** (All / IntentBlocked / Executions / State changes / GUI actions) that filters `events` by `topic`; the filtered list rendered **virtualized** (`useVirtualizer`) so thousands of events stay smooth (constant DOM); reuse `EventFeed`'s row rendering (extract its row into a reusable `<EventRow event />` if needed, or render the rows via EventFeed with the virtualization wrapper). Empty → "No events yet"; the blocked-rule chips (opposition/ttl-dedup/cap) render violet. `aria-live="polite"` on the live region for new critical events; respect reduced-motion.

- [ ] **Step 1: failing test** — `ActivityPage.test.tsx` (seed ~5 events incl. an IntentBlocked with rule "opposition" + an Execution): the feed renders the IntentBlocked violet rule chip ("opposition"); the type filter set to "IntentBlocked" hides the Execution row; empty events → "No events yet". (Virtualization: assert the list renders the visible rows; jsdom has no layout so virtualizer may render a subset — assert at least the filtered rows are queryable, or set a large-enough container.)
- [ ] **Step 2–4:** fail → implement (filter in `useMemo`; virtualizer over the filtered array; reuse EventFeed row rendering) → pass.
- [ ] **Step 5: Commit** — `feat(gui-fe2): Activity page — type filter + virtualized event feed + blocked-rule chips` (+trailer).

---

### Task 6: Settings page (grouped + search)

**Files:** Modify `frontend/src/sections/SettingsPage.tsx`; Test `frontend/src/sections/SettingsPage.test.tsx`.

**Interfaces:**
- Consumes: `useController` (`api`), `SettingsTab` (reused — loads via `api.getSettings`, source/tier badges, edit → `patchSetting`, inline 422), `useReadOnly`, `<Panel>`.
- Produces: the Settings section: a **search** box filtering rows by key; rows **grouped by domain** (the dotted-key prefix: signal_grading / risk / trade_management / connection / arbiter / ops) with group headers; each row keeps `SettingsTab`'s source/tier badges + edit + inline-422 behavior; wrap in `<Panel>` (loading/error+retry on getSettings failure). If `SettingsTab` renders a flat list internally, either (a) add optional `groupByDomain`/`filter` props to it, or (b) build the grouped/searchable view in `SettingsPage` reusing SettingsTab's row renderer (extract `<SettingRow>` if needed). Keep the 422/tier/source logic in ONE place (don't reimplement). Read-only disables edits.

- [ ] **Step 1: failing test** — `SettingsPage.test.tsx` (mock `api.getSettings` returning rows across 2 domains incl. a restart-tier key): the search box filters rows by typed key; the domain group headers render; a restart-tier row shows the "restart" badge; a `patchSetting` 422 renders the detail inline (reuse SettingsTab behavior). Error: `getSettings` rejection → Panel error + Retry.
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5: Commit** — `feat(gui-fe2): Settings page — search + domain grouping over source/tier rows + inline 422` (+trailer).

---

### Task 7: ⌘K command actions + wire read-only-403 across sections

**Files:** Modify `frontend/src/components/shell/AppShell.tsx` (pass a real `actions` array to `CommandPalette`); Create `frontend/src/lib/commandActions.ts` (builds the `PaletteAction[]`); Test `frontend/src/lib/commandActions.test.ts`.

**Interfaces:**
- Consumes: `api`, `useReadOnly`, `useNavigate` (already), `PaletteAction`.
- Produces: `buildCommandActions({ api, paused, readOnly, mutate, confirm })` → `PaletteAction[]`: Pause/Resume (toggles by `paused`), Cancel pending, **Close All** (destructive, needs confirm), **Panic** (destructive, needs confirm). Each `run` routes through `mutate` (403→read-only); destructive ones open the SAME confirm flow as the panel buttons (a confirm callback the AppShell provides, or the palette closes and a confirm dialog opens). Each action's `disabled = readOnly`. AppShell builds these from `useController().api` + `snapshot.health.paused` + `useReadOnly()` and passes them to `<CommandPalette actions=...>`. The Navigate group already exists in the palette. Destructive confirm: simplest is to route Close-All/Panic through a shared confirm `AlertDialog` owned by AppShell (open on select), mirroring the Controls confirm-gate — NEVER a second unconfirmed path to the backend.

- [ ] **Step 1: failing test** — `commandActions.test.ts`: `buildCommandActions` with `readOnly:true` marks all mutating actions `disabled`; Pause action's `run` calls `api.postCommand({command:"pause"})` via the injected `mutate`; the Close-All/Panic actions are flagged `destructive`. (The confirm-dialog wiring is asserted in an AppShell test or the live-drive; the unit test pins the action list + disabled + destructive flags + that run routes through mutate.)
- [ ] **Step 2–4:** fail → implement (`commandActions.ts` pure builder; AppShell wires it + a confirm AlertDialog for destructive) → pass.
- [ ] **Step 5: Commit** — `feat(gui-fe2): ⌘K command actions (pause/cancel/close-all/panic, confirm-gated, read-only aware)` (+trailer).

---

### Task 8: Verification (build + full suite + live-drive + design-review)

- [ ] **Step 1:** Full frontend suite `cd frontend && npm test` (FOREGROUND, timeout 600000) — all green; report count. Re-run any load-flaky test isolated to confirm.
- [ ] **Step 2:** `npm run build` — clean; `frontend/dist` populated.
- [ ] **Step 3 (live-drive — MANDATORY):** run the demo server from the worktree (`TITAN_GUI_TOKEN=devtoken PYTHONPATH=<worktree> .venv/bin/python scripts/gui_demo_server.py`), drive every section with the Playwright headless-shell: Overview (KPIs/equity/top-positions/activity/controls), Positions (filter/sort/close), Strategies (promote dialog), Activity (feed + rule chips + filter), Settings (search/group/tier badges/422), ⌘K actions (pause + a destructive confirm), and a read-only pass (`TITAN_GUI_READONLY=1` → all mutations disabled + banner). Capture screenshots at desktop + phone. Zero console errors.
- [ ] **Step 4:** Design-review the screenshots (brand consistency: violet accent, Instrument Sans/JetBrains Mono, spacing/hierarchy, all Panel states). Fix Criticals.
- [ ] **Step 5 (no commit):** record results in the ledger; confirm no Python touched (`git diff main..HEAD -- '*.py'` empty).

---

## Self-Review

**Spec coverage (§5/§6):** Overview §5 → T2; Positions §5 (+filter/sort) → T3; Strategies §5 → T4; Activity §5 (+virtualization/filter) → T5; Settings §5 (+group/search) → T6; ⌘K real actions §4.3 → T7; read-only-403 flip → T1 (useMutate) applied across T2/T3/T5/T7; Panel state matrix §6.2 → every section task; responsive phone-glance §6.3 → verified in T8 (BottomTabs + read-only already from Plan 1); a11y §6.5 → aria-live in Activity (T5), disabled controls, focus (inherited). Virtualization §6.4 → T5 (Activity); Positions virtualization deferred (small counts, noted in T3).
**Placeholder scan:** each task reuses a named tested component + specifies the composition + a test; no TBDs. Where a reused component needs a small prop (StrategiesTab `onReadOnly`, SettingsTab grouping/search or an extracted row), the task names the exact minimal change and keeps the 422/tier/promote logic single-sourced.
**Type consistency:** `useController()` shape, `Api`, `ApiError`, `PaletteAction`, `ConnectionState`, `<Panel status>` union — all consumed as defined in Plan 1; `useMutate` (T1) consumed by T2/T3/T5/T7; `buildCommandActions` signature stable T7→AppShell.

---

## Market Context Addendum (2026-07-15, owner request)

Adds a **Market Sessions** widget (3 sessions + locality clock, intelligent/dynamic) and a **Dollar Bias** indicator. Placement: a **condensed, always-visible** version in the top **StatusBar** (every section) + **full** widgets on the Overview top strip. DXY data: **broker index symbol if available, else computed from the tracked USD pairs** (no external API — CSP/offline). Sessions are pure client-time (DST-correct via IANA zones); the locality clock is static-state (just local time).

### Task 9: Session engine (pure, DST-correct)

**Files:** Create `frontend/src/lib/sessions.ts`, `frontend/src/lib/sessions.test.ts`.

**Interfaces:**
- Produces:
  - `interface MarketSession { id: "sydney"|"tokyo"|"london"|"newyork"; label: string; zone: string; openLocalH: number; closeLocalH: number }` and a `SESSIONS` constant: Sydney (Australia/Sydney 07–16 local), Tokyo (Asia/Tokyo 09–18), London (Europe/London 08–17), New York (America/New_York 08–17). (Local trading hours per zone; DST handled by the zone.)
  - `zoneOffsetMinutes(zone: string, at: Date): number` — the UTC offset (minutes) for an IANA zone at instant `at`, via `Intl.DateTimeFormat` (handles DST). Pure/injectable `at`.
  - `sessionStates(nowUtc: Date): { sessions: Array<{ id; label; open: boolean; localTime: string; statusLabel: string; countdownMin: number; startUtcMin: number; endUtcMin: number }>; overlaps: Array<{ ids: [string,string]; active: boolean }>; activeIds: string[]; weekendClosed: boolean }` — for each session compute today's UTC open/close window (from local hours + `zoneOffsetMinutes`), whether `nowUtc` is inside it (open), the session's own local time string, a `statusLabel` ("Open · closes in 47m" / "Opens in 2h 14m"), and `countdownMin` to the next boundary. Overlaps = pairs of sessions open at the same time (flag London↔NewYork, Tokyo↔London). `weekendClosed` = FX closed (Fri ~22:00 UTC → Sun ~22:00 UTC).

- [ ] **Step 1: failing test** — `sessions.test.ts`: with a fixed `nowUtc` during the London↔NY overlap (e.g. 2026-07-15T14:00:00Z, a Wednesday), assert london+newyork are `open`, the overlap {ids:[london,newyork]} is `active`, `activeIds` includes both, and `weekendClosed` is false; with a Saturday `nowUtc`, `weekendClosed` true; with a `nowUtc` before London open, london `open:false` and its `statusLabel` starts "Opens in". Use injected `nowUtc` (no Date.now). Keep DST-tolerance in mind: assert on open/closed booleans + overlap, not exact minute strings that DST could shift.
- [ ] **Step 2–4:** fail → implement (use `Intl.DateTimeFormat(zone,{timeZoneName:...})` / the `formatToParts` offset trick for `zoneOffsetMinutes`) → pass.
- [ ] **Step 5: Commit** — `feat(gui-fe2): market-session engine (open/overlap/countdown, DST-correct)` (+trailer).

### Task 10: MarketSessions widget (full — Overview) + LocalityClock

**Files:** Create `frontend/src/components/market/MarketSessions.tsx`, `frontend/src/components/market/LocalityClock.tsx`, tests.

**Interfaces:**
- Consumes: `sessionStates` (T9), a ticking `nowUtc` (a `useNow()` hook: `setInterval` 1s, cleared on unmount; reduced-motion → still ticks but no animated sweep).
- Produces:
  - `<LocalityClock />` — your local time (large, JetBrains Mono), date, and timezone label (`Intl.DateTimeFormat().resolvedOptions().timeZone`). Static-state (no session logic).
  - `<MarketSessions />` — a 24h **timeline** (linear track) with the 3 session bands positioned by their UTC windows, **overlap zones** highlighted (accent for London↔NY), a live **now marker**; below/beside it, a digital clock + status chip per session (Open pulse / countdown) from `sessionStates`. Weekend-closed → a "Markets closed — opens Sun" state. Uses role tokens; profit-green for "Open", muted for closed, accent for overlaps.

- [ ] **Step 1: failing test** — `MarketSessions.test.tsx`: mock/inject a fixed now (pass `now` as a prop or mock `useNow`) during the London↔NY overlap → both show "Open" and the overlap band is present; a session before open shows "Opens in". `LocalityClock.test.tsx`: renders a time + the resolved timezone label.
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5: Commit** — `feat(gui-fe2): MarketSessions timeline widget + LocalityClock` (+trailer).

### Task 11: Dollar bias — backend field + DollarBias widget

**Files:** Modify `src/ops/web/state_view.py` (add `dollar` to `build_snapshot`), `src/ops/web/fake_controller.py` (synthesize) and `scripts/gui_demo_server.py` (moving demo values); Modify `frontend/src/lib/types.ts` (add `DollarBias`), Create `frontend/src/components/market/DollarBias.tsx`, tests (`tests/unit/test_gui_dollar.py` + `DollarBias.test.tsx`).

**Interfaces:**
- Backend `build_snapshot(controller).dollar` = `{ source: "index"|"computed"|"unavailable", value: float|null, bias: float, trend: float[], contributors: {symbol: float}[] }` where `bias` ∈ [-100,100] (USD strength). Sourcing: if `controller` exposes a DXY/USDX symbol price → `source:"index"`, `value`=index, `bias` from its recent delta; ELSE compute from the tracked USD pairs' latest mids (invert XXXUSD contributions, normalize/average recent % change) → `source:"computed"`; if no price data at all → `source:"unavailable"` (widget shows a degraded/empty state — NEVER crash). Read controller price data defensively (getattr guards); the LIVE price wiring is best-effort — if the controller attr isn't present yet, return `"unavailable"` (a follow-up wires the real source). Fake_controller + demo provide full synthetic `dollar` (a slowly-moving bias + trend + a few contributors).
- Frontend `<DollarBias data />` — a gauge (−100…+100, needle/arc) with the bias + direction arrow (green USD-strong / red USD-weak — but this is USD strength, not P&L; use a neutral/duo tone, NOT the reserved profit/loss unless it reads clearly), a short **trend sparkline** (Recharts, reuse EquitySparkline pattern), and the top contributors; `source` badge (LIVE index vs computed); `unavailable` → empty state.

- [ ] **Step 1: failing tests** — Python `tests/unit/test_gui_dollar.py`: `build_snapshot` returns a `dollar` block with the keys; a fake controller with no price data → `source:"unavailable"` (no crash). Frontend `DollarBias.test.tsx`: renders the bias value + source badge; `source:"unavailable"` → empty state.
- [ ] **Step 2–4:** fail → implement (Python: extend build_snapshot defensively + fake_controller + demo; TS: the widget) → pass. Run the Python GUI suite (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_gui_*.py'`) FOREGROUND — stays green (this is the ONE backend-touching task; keep it additive).
- [ ] **Step 5: Commit** — `feat(gui): dollar-bias snapshot field (index|computed|unavailable) + DollarBias widget` (+trailer).

### Task 12: Persistent market context in StatusBar + full on Overview

**Files:** Modify `frontend/src/components/shell/StatusBar.tsx` (condensed market context), `frontend/src/sections/OverviewPage.tsx` (mount full widgets + DollarBias); tests updated.

**Interfaces:**
- StatusBar gains a **condensed** market-context cluster (between the status chips and the account): the active session name(s) + a mini "next in Xm", and a compact dollar-bias pill (bias value + direction). Consumes `sessionStates(useNow())` + `snapshot.dollar`. Collapses/hides gracefully on narrow widths.
- OverviewPage mounts the **full** `<MarketSessions/>` + `<LocalityClock/>` + `<DollarBias data={snapshot.dollar}/>` in the top **Market Context strip** (above the KPIs).

- [ ] **Step 1: failing test** — StatusBar.test: with an injected/mocked overlap now + a `snapshot.dollar`, the condensed cluster shows an active session + the dollar bias. OverviewPage.test: the full MarketSessions + DollarBias render on the page.
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5: Commit** — `feat(gui-fe2): persistent market context in StatusBar + full sessions/dollar on Overview` (+trailer).

> Verification (Task 8) extends to cover the market widgets: live-drive shows the session timeline (with the current overlap), the locality clock, and the dollar-bias gauge updating; design-review the market strip.
