# Titan Control GUI — Redesign (v2) Design Spec

**Date:** 2026-07-15
**Status:** APPROVED (brainstorm 2026-07-15) — ready for implementation plan.
**Branch:** `feat/control-gui-backend` (continues the GUI workstream; no `main` integration).
**Supersedes (frontend only):** `docs/superpowers/specs/2026-07-14-control-gui-frontend-design-system.md`
(v1 dark-cockpit tokens) — the Phase-1b SPA it produced is the *baseline this redesign evolves*.
**Companion:** `docs/branding/titan-brand-prompt.md` — the brand identity is generated externally
(claude.ai design tool); its returned tokens/SVGs fill the placeholder token slots in §7.

---

## 1. Goal & positioning

Rebuild the Titan control GUI's **presentation layer** into a professional, robust, credibility-grade
operator cockpit with a **fresh design language** — a "modern premium fintech" identity (the craft and
restraint of Linear / Stripe / Arc / Vercel, applied to trading). The audience is serious (investors,
collaborators, prop firms); the interface must read as a tool a professional quant desk would run.

**This is a presentation rebuild, not a rewrite.** The Phase-1a backend and the Phase-1b *data layer*
are reviewed, tested, and correct — they stay. The redesign replaces the app shell, the section
layouts, and every component, built against a new design-token contract the brand fills.

### Non-goals (explicit scope guards)
- **No backend changes.** The API contract (`/api/state`, `/api/events`, `/api/history`, `/api/command`,
  `/api/settings`, `/api/registry`, `/ws`), auth, audit, and read-only semantics are unchanged.
- **No user-arrangeable panels** (no drag/resize/dock, no saved layouts). Layouts are curated + responsive.
- **No full phone control.** Phone is a read-only *glance*; full mutation control is desktop/tablet.
- **No Phase-2 section content.** Research and Journal appear in the nav but are disabled placeholders.
- **No brand invention here.** Colors/wordmark/type come from the external brand board; this spec defines
  the *token roles* they fill, and ships placeholder values (evolved from v1) so the build can proceed.

---

## 2. Established decisions (from the brainstorm)

| Dimension | Decision |
|---|---|
| Ambition | Credibility showcase (investors / collaborators / prop firms) |
| Redesign depth | Rethink the design language (fresh), not a polish pass |
| Brand | Keep **Titan**, refined; modern premium fintech; dark-first |
| Robustness | All four: complete UI states · responsive · real-data resilience · operator speed + a11y |
| Shell | **Left sidebar + slim top status bar**; curated responsive layouts |
| Sections | Overview · Positions · Strategies · Activity · Settings (+ Research/Journal placeholders) |
| Responsive | Desktop-first · tablet-graceful · phone-glance (read-only) |
| Engineering | **Evolve in place** — keep data layer + contract, rebuild presentation |

---

## 3. Architecture — keep vs rebuild

**Keep unchanged (reviewed/tested — do not touch behavior):**
- The entire Phase-1a backend (`src/ops/web/**`, controller wiring, `websockets` dep + guard).
- The data layer: `frontend/src/lib/types.ts`, `api.ts` (typed client, 401/429/403/422 → `ApiError`),
  `useLiveState.ts` (WS first-frame token auth / reconnect / poll fallback), `format.ts`.
- The read-only contract (client learns read-only reactively from a 403 `ApiError`).
- `ReadOnlyContext`, the served-from-`frontend/dist` static mount, the `fake_controller`/`devserver`
  (+ `scripts/gui_demo_server.py`), Vite / Vitest / Tailwind / shadcn(Radix) toolchain.

**Rebuild (new design system):**
- `App.tsx` → a new **AppShell** (sidebar + top status bar + command palette + client router).
- Every presentation component; new section pages; a shared `<Panel>` state wrapper; a virtualized feed.
- The Tailwind/CSS token layer → the role-based token contract (§7).

**Fix while rebuilding (known defects):**
- `useLiveState` poll **stale-closure**: the poll's `if (connected) return` reads a frozen `connected`
  (effect deps `[token]`), so it polls every 5s even while the WS is healthy. Fix with a `connectedRef`
  mirroring `connected`, so polling runs *only* while disconnected. Add a regression test.
- Harden the connection-state model into an explicit machine (§6.1).

**New dependencies (minimal, all bundled by Vite — CSP/offline-safe, no external hosts):**
- **Client router**: `react-router-dom` (hash or memory history — no server rewrites needed; the
  Phase-1a SPA fallback already serves `index.html` for any client path). Enables deep-linkable sections
  (a11y + shareable state). *(Alternative — a ~30-line hash router — is a plan-time call; default to
  react-router-dom for maturity.)*
- **Virtualization**: `@tanstack/react-virtual` (windowed Activity feed + large Positions table).
- **Command palette**: `cmdk` (⌘K).

---

## 4. App shell

### 4.1 Left sidebar
- Titan **mark + wordmark** (brand SVG) at top; collapses to the **mark only** in the icon-rail state.
- **Section nav** (icon + label): Overview · Positions · Strategies · Activity · Settings.
  Research · Journal are present but **disabled** (tooltip: "Phase 2").
- Active-section indicator (accent bar/fill); hover + focus-visible states; full keyboard nav.
- A **read-only badge** in the sidebar footer when the app is in read-only mode.
- Collapsible to an icon rail (persisted in `localStorage`); on tablet it defaults to the rail; on phone
  it becomes a **bottom tab bar** exposing only the glance sections (Overview · Positions · Activity).

### 4.2 Top status bar (persistent, all sections — never scrolls away)
The always-on system truth, left→right:
- **Connection pill** — reflects the §6.1 machine: `Live` (accent/ok) · `Reconnecting…` (warning, spinner)
  · `Degraded` (warning — "polling") · `Offline` (loss). A separate **Stale** marker when the heartbeat
  age exceeds threshold even while connected.
- **Paused** indicator when the system is manually paused; **drawdown-throttle** indicator (with the
  current multiplier) when engaged.
- **Account** — balance / equity (tabular).
- **⌘K** command-palette trigger.

### 4.3 Command palette (⌘K) — operator speed backbone
- Navigate to any section; run controls (Pause/Resume, Close-All → confirm, Panic → confirm, Cancel);
  toggle/enable/disable a strategy; jump to a setting. Mutations respect read-only (disabled + reason)
  and reuse the same confirm-gate + typed-id-promote flows as the panels (never a second code path to
  the backend). Fuzzy search, keyboard-only operable, ARIA combobox semantics.

### 4.4 Router & deep-linking
Routes: `/overview` (default) · `/positions` · `/strategies` · `/activity` · `/settings`. Unknown →
Overview. On route change, focus moves to the main content region (screen-reader friendly). The token
gate wraps the router (no route is reachable without a token in memory).

---

## 5. Sections (information architecture)

- **Overview** — at-a-glance only. Health/connection summary, KPI tiles (balance, equity, day-PnL,
  open positions, arbiter approved/blocked), the equity chart, a **compact top-positions** summary
  (N largest by exposure/PnL, links to Positions), and a **recent-activity** strip (last few events,
  links to Activity). No heavy tables here.
- **Positions** — the full positions table + management: per-row close (confirm) and bulk close-all
  (confirm); sortable columns; filter by symbol/side/strategy; sticky header; virtualized when large.
  Side = BUY/SELL semantic chip; PnL colored by sign with icon (never color-alone).
- **Strategies** — the registry table; enable/disable; **typed-id promote** dialog (mirrors the
  server-side gate); status/state badges (live/research/active); research rows visually distinct.
- **Activity** — the full event feed, **virtualized**, filterable by type (IntentBlocked rules
  [opposition/ttl-dedup/cap], executions, state changes, GUI actions); blocked-rule chips; auto-scroll
  with pause-on-hover; `aria-live` for new critical events; respects reduced-motion.
- **Settings** — grouped by domain (grading · risk · trade-management · connection · arbiter · ops)
  with search; each row shows **source** (default/override) + **tier** (live/restart) badges; edit →
  `patchSetting`; inline **422** validation under the row; success/restart-required feedback.
- **Research / Journal** — nav entries, disabled (Phase 2: run-card browser + journal explorer).

---

## 6. Robustness architecture

### 6.1 Connection-state model (single source of truth)
A derived `ConnectionStatus` machine in the data layer, surfaced in the status bar and consumed by
every panel:

```
connecting ──▶ live ──▶ reconnecting ──▶ degraded ──▶ offline
                 ▲            │              │            │
                 └──── WS reopens ◀──────────┴──── poll recovers snapshot
```
- `live`: WS open, receiving. `reconnecting`: WS dropped, backoff in progress, last-good retained.
- `degraded`: WS not recovering but `GET /api/state` polling still returns snapshots (data flows,
  slower; the event feed is paused — no event stream over polling). `offline`: both failing.
- Orthogonal **`stale`**: `snapshot.health.last_heartbeat_age_s` over threshold (bridge/EA silent) even
  while `live` — a marker on health + affected data, not a connection state.
- **Panels keep last-good data** in `reconnecting`/`degraded` (never blank); only `offline` shows a hard
  error+retry. The `useLiveState` hook exposes this status; the poll runs only when not `live`
  (fixes the stale-closure).

### 6.2 Per-panel state matrix (a shared `<Panel>` wrapper enforces it)
Every panel implements the same set — no panel can ship blank or broken:

| State | Treatment |
|---|---|
| `loading` | Skeleton matching the panel's shape (no spinner-only, no layout shift) |
| `empty` | Purposeful message + optional action ("No open positions", "No events yet") |
| `error` | Message + **Retry**; never a blank frame or a raw exception |
| `populated` | The data |
| `stale/degraded` | Last-good data + a subtle marker/banner (data may be delayed) |

Enumerated per panel: Overview tiles/chart/summaries, Positions, Strategies, Activity, Settings.

### 6.3 Responsive strategy
Breakpoints (Tailwind): **desktop cockpit ≥1280**, **tablet 768–1279**, **phone-glance <768**.
- Sidebar → icon rail (tablet) → bottom tab bar (phone).
- Multi-column grids → stacked; the equity chart keeps aspect via container queries.
- Tables → horizontal-scroll containers on tablet; **card rows** on phone.
- **Phone = read-only glance**: only Overview · Positions · Activity; all mutating controls hidden
  (not merely disabled) with a "control from desktop" note. **Body never scrolls horizontally** — wide
  content scrolls inside its own `overflow-x:auto` container.

### 6.4 Real-data resilience
- **Activity feed virtualized** (`@tanstack/react-virtual`) — thousands of events, constant DOM, smooth
  scroll; new-event insertion without scroll jump when the user has scrolled up.
- **Positions table** — sticky header; virtualization above a row threshold.
- All numbers **tabular + locale-formatted + big-number-safe**; every field null/undefined-guarded
  (never renders `undefined`/`NaN`); reserved space (no CLS); the equity buffer bounded (~120 points).

### 6.5 Operator speed + accessibility
- **⌘K** palette (§4.3); keyboard shortcuts for common actions with a discoverable **?** cheatsheet.
- Focus management: dialogs trap + restore focus; focus-visible rings everywhere; tab order = visual order.
- ARIA: `aria-live="polite"` for the feed + connection-status changes; labeled icon buttons; table
  semantics with `aria-sort`; combobox semantics for ⌘K.
- `prefers-reduced-motion` respected (freeze auto-scroll + chart/entrance animation).
- **Contrast validated WCAG-AA** on the *brand's actual* surfaces (re-run the check when brand tokens land).

---

## 7. Design-token contract (roles the brand fills)

The redesign is built against **role tokens**, never raw hex — so dropping in the brand board is a
one-file swap. Ship **placeholder values** (evolved from the v1 dark cockpit) until the brand returns.

- **Color roles**: `bg`, `surface-1`, `surface-2`, `elevated`; `border`, `border-strong`; `text-primary`,
  `text-secondary`, `text-muted`; `accent` (+ `accent-hover`, `accent-active`, `accent-subtle`);
  `focus-ring`; and reserved semantic `profit`, `loss`, `warning`, `info`, `blocked`.
  *(Brand supplies the hexes; role names are fixed. Semantic profit/loss stay reserved — the signature
  accent is never used for P&L.)*
- **Typography**: `font-sans` (UI) + `font-mono` (data/tabular figures); a type scale (12/14/16/18/24/32)
  and weight roles. Brand supplies families — **self-hosted woff2**, no font CDN (CSP/offline).
- **Spacing / radius / elevation / motion**: 8px spacing scale; radius scale; elevation (shadow) scale;
  motion tokens (durations 150–300ms, easings) — all reduced-motion aware.
- **Logo slots**: mark + wordmark SVG for the sidebar (full + rail), the top bar, the token gate, and
  the favicon.

**Placeholder → brand swap:** a single `tokens.css` (+ Tailwind theme referencing the CSS vars) holds
all values. When the brand board returns, replace the values (and drop in the SVG/woff2 assets); no
component changes needed. Re-run the WCAG-AA contrast check against the new surfaces.

---

## 8. Testing & verification
- **Component/hook tests (Vitest + jsdom)** per rebuilt unit, following the Phase-1b pattern: the
  `useLiveState` connection-state machine + poll-only-when-disconnected fix (regression test); the
  `<Panel>` state matrix; read-only disables every mutating surface; confirm-gate + typed-id promote;
  Settings 422 inline; command-palette actions route through the same handlers; virtualized feed renders.
- **Backend non-regression**: the Python GUI suite stays green (the redesign touches no backend).
- **Live-drive** (as in Phase 1b): build → serve via the devserver/demo server → drive the real UI
  (Playwright headless-shell) across sections + breakpoints + connection states; **design-review** pass
  on screenshots. The live-drive is mandatory — it caught the production WS bug last time.
- **Accessibility**: contrast on brand surfaces; keyboard-only walkthrough; reduced-motion.

## 9. Success criteria
- Every section renders under all five panel states + all connection states without blanking or CLS.
- Sidebar/status-bar/⌘K shell works desktop→tablet→phone per §6.3; phone is a clean read-only glance.
- Read-only, confirm-gate, and typed-id promote enforced on every mutating surface (incl. ⌘K).
- Backend + data-layer behavior unchanged; Python GUI suite green; frontend test suite green; live-drive
  + design-review PASS.
- Brand tokens are a one-file swap; contract holds with placeholder values today and brand values later.

## 10. Dependencies & sequencing
- **Brand-agnostic build can start now** against placeholder tokens (this spec). The external brand board
  is a *parallel* track; its return is a token/asset swap (§7), not a blocker for structural work.
- Implementation follows the SDD loop (fresh subagent per task → task review → final whole-branch review),
  same discipline as Phase 1a/1b. Plan: `docs/superpowers/plans/2026-07-15-titan-gui-redesign-*.md`.
