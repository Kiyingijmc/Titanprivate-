# Titan GUI Redesign — Plan 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Titan control GUI's foundation — a role-based design-token system, a hardened data layer (explicit connection-state machine + poll-only-when-disconnected fix), and the new app shell (left sidebar + top status bar + ⌘K command palette + client router + a shared `<Panel>` state wrapper) — yielding a navigable, on-brand cockpit with live connection status and stubbed section pages.

**Architecture:** Evolve the existing `frontend/` in place. KEEP the reviewed Phase-1b data layer (`types`, `api`, `format`) and the backend contract; MODIFY `useLiveState` to expose a derived `ConnectionStatus` and fix its poll stale-closure; ADD a token layer, a router, the shell components, and the `<Panel>` wrapper; REPLACE `App.tsx` with the new shell composition. Section bodies are stubs here (filled by Plan 2). Built against role tokens with placeholder values (evolved from the v1 dark cockpit) so the external brand board is a one-file swap.

**Tech Stack:** Vite 5, React 18, TypeScript 5 (strict, `noUnusedLocals`), Tailwind 3, shadcn/ui (Radix), Vitest + @testing-library/react + jsdom, lucide-react. NEW deps: `react-router-dom`, `cmdk`, `@tanstack/react-virtual` (bundled by Vite, CSP-safe).

**Spec:** `docs/superpowers/specs/2026-07-15-titan-gui-redesign-design.md`

## Global Constraints

- Work on `feat/control-gui-backend`. The user's concurrent session occupies the `main` working tree — do all work in the **isolated worktree** the controller set up; never touch `main`, never integrate. No git remote — never push. BRANCH GUARD every implementer: assert the worktree is on `feat/control-gui-backend` before committing.
- **No backend changes.** The API contract, auth, audit, read-only semantics are unchanged. The Python GUI suite must stay green (touch no `src/**` outside `src/ops/web/` — and this plan touches no Python at all).
- **Keep unchanged**: `frontend/src/lib/{types,api,format}.ts`, `ReadOnlyContext`, the served-from-`dist` mount, `fake_controller`/`devserver`/`gui_demo_server.py`. `useLiveState.ts` is modified ONLY to add `ConnectionStatus` + the poll fix (its WS/auth/reconnect behavior and return shape stay backward-compatible: still returns `{snapshot, events, connected}` plus a NEW `connectionStatus`).
- **Design tokens are ROLE-based** (spec §7). Ship placeholder values evolved from the current v1 dark cockpit (`frontend/src/index.css`). The brand board later replaces values in ONE file (`src/design/tokens.css`); no component changes. Never hardcode hex in components — reference role tokens via Tailwind classes / CSS vars.
- **Dark-mode only.** Lucide SVG icons — never emoji. Self-hosted fonts / relative asset base — no external CDN (CSP/offline).
- **Accessibility**: focus-visible rings on all interactive elements; keyboard nav; `prefers-reduced-motion`; ARIA where noted. Contrast is re-validated against brand surfaces when tokens land (not this plan).
- Tests: run ONLY the task's test file(s) via `cd frontend && npx vitest run <file>` — the env is EXTREMELY SLOW (a vitest run is 60–90s of startup overhead; plan for Bash timeout 600000, FOREGROUND, never background+Monitor). Do NOT run `npm install` unless a task's Step 0 says to. Build check via `npm run build` where noted (also slow).
- Stage ONLY each task's exact files (explicit `git add <paths>`, never `git add -A`). `node_modules`/`dist`/tsc-emitted artifacts stay gitignored.
- Commit messages end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

## File Structure

```
frontend/src/
  design/tokens.css            # NEW — role-based CSS custom properties (placeholder values)
  index.css                    # MODIFY — @import tokens.css; keep base/reset + reduced-motion
  lib/
    connection.ts              # NEW — deriveConnectionStatus() + ConnectionStatus type (pure)
    useLiveState.ts            # MODIFY — expose connectionStatus + connectedRef poll fix
  components/shell/
    Panel.tsx                  # NEW — <Panel status> state wrapper (loading/empty/error/populated/stale)
    Sidebar.tsx                # NEW — section nav rail, collapse, read-only badge, brand slot
    StatusBar.tsx              # NEW — connection pill, paused/throttle, account, ⌘K trigger
    CommandPalette.tsx         # NEW — cmdk ⌘K (nav + read-only-aware action stubs)
    AppShell.tsx               # NEW — composes Sidebar + StatusBar + <Outlet/> + CommandPalette
  routes/
    router.tsx                 # NEW — react-router routes -> AppShell + section stubs
  sections/                    # NEW — stub pages (filled in Plan 2)
    OverviewPage.tsx PositionsPage.tsx StrategiesPage.tsx ActivityPage.tsx SettingsPage.tsx
  brand/Logo.tsx               # NEW — mark + wordmark SVG slot (placeholder geometric mark)
  App.tsx                      # MODIFY — TokenGate -> ReadOnlyProvider -> RouterProvider
tailwind.config.ts             # MODIFY — theme extends the role tokens
```

---

### Task 0: Deps + design-token layer

**Files:** Create `frontend/src/design/tokens.css`, `frontend/src/brand/Logo.tsx`; Modify `frontend/src/index.css`, `frontend/tailwind.config.ts`, `frontend/package.json`.

**Interfaces:** Produces the role-token CSS vars + Tailwind theme keys every later task styles against; a `<Logo variant="full"|"mark" />` placeholder component (brand SVG slot).

- [ ] **Step 0: Install deps** — `cd frontend && npm install react-router-dom@^6 cmdk@^1 @tanstack/react-virtual@^3` (FOREGROUND, timeout 600000; on ETIMEDOUT retry `--fetch-retries=6 --fetch-timeout=600000`). If the registry is unreachable, STOP → BLOCKED.

- [ ] **Step 1: `frontend/src/design/tokens.css`** — role tokens as HSL, placeholder values evolved from v1 (spec §7). The brand board later replaces THIS file's values only:

```css
/* Titan design tokens — ROLE-based. Brand board replaces these values (only). */
:root {
  /* surfaces */
  --bg: 222 47% 9%;            /* app background (deeper than v1 #0F172A for more depth) */
  --surface-1: 222 24% 14%;    /* cards/panels */
  --surface-2: 222 26% 18%;    /* muted rows / inputs / table header */
  --elevated: 222 22% 21%;     /* popovers / command palette / dialogs */
  /* lines + text */
  --border: 215 22% 26%;
  --border-strong: 215 20% 34%;
  --text-primary: 210 40% 98%;
  --text-secondary: 215 18% 72%;
  --text-muted: 215 16% 55%;
  /* signature accent (placeholder: refined indigo — swap for brand) + states */
  --accent: 245 72% 63%;
  --accent-hover: 245 72% 68%;
  --accent-active: 245 72% 58%;
  --accent-subtle: 245 60% 22%;
  --focus-ring: 245 72% 63%;
  --on-accent: 0 0% 100%;
  /* reserved semantic — signature accent NEVER used for P&L */
  --profit: 142 71% 45%;
  --loss: 0 84% 60%;
  --warning: 38 92% 50%;
  --info: 199 92% 60%;
  --blocked: 255 92% 76%;
  /* radius / elevation / motion */
  --radius-lg: 10px; --radius-md: 8px; --radius-sm: 6px;
  --shadow-1: 0 1px 2px 0 hsl(222 47% 4% / 0.4);
  --shadow-2: 0 8px 24px -6px hsl(222 47% 4% / 0.5);
  --motion-fast: 150ms; --motion-base: 220ms; --ease: cubic-bezier(0.2, 0, 0, 1);
}
```

- [ ] **Step 2: `frontend/src/index.css`** — replace the v1 token block with `@import "./design/tokens.css";` (keep `@tailwind` layers, the base `body` styles, `.tabnum`, and the reduced-motion block). Body uses `hsl(var(--bg))` / `hsl(var(--text-primary))`, `font-sans`.

- [ ] **Step 3: `frontend/tailwind.config.ts`** — extend `theme.colors` to the role tokens (`background:"hsl(var(--bg))"`, `surface:{1,2}`, `elevated`, `border`, `border-strong`, `foreground:"hsl(var(--text-primary))"`, `muted-foreground:"hsl(var(--text-muted))"`, `secondary-foreground:"hsl(var(--text-secondary))"`, `accent` + `accent-hover/active/subtle`, `ring:"hsl(var(--focus-ring))"`, `profit/loss/warning/info/blocked`); `borderRadius` → the radius vars; keep `fontFamily.sans`/`mono` (brand families later). `boxShadow` → `--shadow-1/2`.

- [ ] **Step 4: `frontend/src/brand/Logo.tsx`** — placeholder mark + wordmark (brand SVG slot; a clean geometric "T"/axis mark in `currentColor` so it inherits accent/text; `variant: "full" | "mark"`; sizes via props). Real brand SVG drops in here later.

```tsx
export function Logo({ variant = "full", className }: { variant?: "full" | "mark"; className?: string }) {
  const mark = (
    <svg viewBox="0 0 24 24" aria-hidden className={className} fill="none" stroke="currentColor" strokeWidth={2}>
      {/* placeholder geometric mark — replaced by the brand board's SVG */}
      <path d="M4 5h16M12 5v14M7 19h10" strokeLinecap="round" />
    </svg>
  );
  if (variant === "mark") return mark;
  return (
    <span className={"inline-flex items-center gap-2 font-mono font-semibold tracking-tight " + (className ?? "")}>
      <span className="text-accent">{mark}</span> Titan
    </span>
  );
}
```

- [ ] **Step 5: Verify** — `cd frontend && npm run build` (FOREGROUND, timeout 600000) succeeds (tokens + config compile). No unit test (CSS-only + a trivial component).
- [ ] **Step 6: Commit** — `feat(gui-fe2): role-based design tokens + Tailwind theme + Logo slot + shell deps` (+trailer). Stage `frontend/src/design/tokens.css`, `frontend/src/index.css`, `frontend/tailwind.config.ts`, `frontend/src/brand/Logo.tsx`, `frontend/package.json`, `frontend/package-lock.json`.

---

### Task 1: Connection-state machine (pure)

**Files:** Create `frontend/src/lib/connection.ts`, `frontend/src/lib/connection.test.ts`.

**Interfaces:**
- Produces: `type ConnectionStatus = "connecting" | "live" | "reconnecting" | "degraded" | "offline"`;
  `interface ConnectionState { status: ConnectionStatus; stale: boolean }`;
  `deriveConnection(input: { wsConnected: boolean; everConnected: boolean; reconnecting: boolean; pollOk: boolean; lastHeartbeatAgeS: number | null; staleThresholdS?: number }): ConnectionState`.
- Consumes: nothing (pure).

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/connection.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { deriveConnection } from "./connection";

describe("deriveConnection", () => {
  it("connecting before first WS open", () => {
    expect(deriveConnection({ wsConnected: false, everConnected: false, reconnecting: false, pollOk: false, lastHeartbeatAgeS: null }).status).toBe("connecting");
  });
  it("live when WS connected", () => {
    expect(deriveConnection({ wsConnected: true, everConnected: true, reconnecting: false, pollOk: true, lastHeartbeatAgeS: 2 }).status).toBe("live");
  });
  it("reconnecting when WS dropped and backing off (no poll yet)", () => {
    expect(deriveConnection({ wsConnected: false, everConnected: true, reconnecting: true, pollOk: false, lastHeartbeatAgeS: 5 }).status).toBe("reconnecting");
  });
  it("degraded when WS down but polling returns snapshots", () => {
    expect(deriveConnection({ wsConnected: false, everConnected: true, reconnecting: true, pollOk: true, lastHeartbeatAgeS: 5 }).status).toBe("degraded");
  });
  it("offline when WS down and polling failing after having connected", () => {
    expect(deriveConnection({ wsConnected: false, everConnected: true, reconnecting: false, pollOk: false, lastHeartbeatAgeS: 5 }).status).toBe("offline");
  });
  it("stale is orthogonal — live but heartbeat old", () => {
    const s = deriveConnection({ wsConnected: true, everConnected: true, reconnecting: false, pollOk: true, lastHeartbeatAgeS: 120 });
    expect(s.status).toBe("live");
    expect(s.stale).toBe(true);
  });
  it("not stale within threshold", () => {
    expect(deriveConnection({ wsConnected: true, everConnected: true, reconnecting: false, pollOk: true, lastHeartbeatAgeS: 10 }).stale).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify it fails** — `cd frontend && npx vitest run src/lib/connection.test.ts`.
- [ ] **Step 3: Implement** — `frontend/src/lib/connection.ts`:
```ts
export type ConnectionStatus = "connecting" | "live" | "reconnecting" | "degraded" | "offline";
export interface ConnectionState { status: ConnectionStatus; stale: boolean; }

const DEFAULT_STALE_S = 60;

export function deriveConnection(input: {
  wsConnected: boolean; everConnected: boolean; reconnecting: boolean;
  pollOk: boolean; lastHeartbeatAgeS: number | null; staleThresholdS?: number;
}): ConnectionState {
  const stale =
    input.lastHeartbeatAgeS != null &&
    input.lastHeartbeatAgeS > (input.staleThresholdS ?? DEFAULT_STALE_S);
  let status: ConnectionStatus;
  if (input.wsConnected) status = "live";
  else if (!input.everConnected) status = "connecting";
  else if (input.pollOk) status = "degraded";     // WS down, snapshots still flowing
  else if (input.reconnecting) status = "reconnecting";
  else status = "offline";
  return { status, stale };
}
```

- [ ] **Step 4: Run to verify PASS** (7 tests).
- [ ] **Step 5: Commit** — `feat(gui-fe2): pure connection-state machine (connecting/live/reconnecting/degraded/offline + stale)` (+trailer).

---

### Task 2: Harden `useLiveState` (expose status + fix poll stale-closure)

**Files:** Modify `frontend/src/lib/useLiveState.ts`; Modify/extend `frontend/src/lib/useLiveState.test.ts`.

**Interfaces:**
- Consumes: `deriveConnection` (Task 1), existing types.
- Produces: `useLiveState(token, opts)` now returns `{ snapshot, events, connected, connectionStatus }` where `connectionStatus: ConnectionState`. Internals: a `connectedRef` mirrors `connected` so the poll interval runs ONLY while not connected (fixes the stale-closure); tracks `everConnected`, `reconnecting`, `pollOk`; derives `connectionStatus` via `deriveConnection` using `snapshot.health.last_heartbeat_age_s`. WS/auth/reconnect/event-cap behavior unchanged.

- [ ] **Step 1: Write the failing test** — append to `useLiveState.test.ts` (keep the existing 2 tests):
```ts
it("exposes connectionStatus live after WS open + state", async () => {
  const { result } = renderHook(() =>
    useLiveState("t", { WebSocketImpl: FakeWS as unknown as typeof WebSocket, pollFallback: false }));
  act(() => { FakeWS.last!.open(); });
  act(() => { FakeWS.last!.message({ type: "state", health: { last_heartbeat_age_s: 3 }, positions: [] }); });
  await waitFor(() => expect(result.current.connectionStatus.status).toBe("live"));
  expect(result.current.connectionStatus.stale).toBe(false);
});

it("poll runs only while disconnected (no poll when connected)", async () => {
  const fetchSpy = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ health: {}, positions: [] }) });
  vi.stubGlobal("fetch", fetchSpy);
  vi.useFakeTimers();
  try {
    renderHook(() => useLiveState("t", { WebSocketImpl: FakeWS as unknown as typeof WebSocket, base: "", pollFallback: true }));
    act(() => { FakeWS.last!.open(); });           // connected
    act(() => { vi.advanceTimersByTime(12000); }); // >2 poll intervals
    expect(fetchSpy).not.toHaveBeenCalled();       // connected -> no poll (stale-closure fixed)
  } finally { vi.useRealTimers(); vi.unstubAllGlobals(); }
});
```
> Add `import { vi } from "vitest"` if not present. The second test pins the fix: with the OLD frozen-`connected` closure, the poll WOULD fire; with the `connectedRef` fix it does not.

- [ ] **Step 2: Run to verify the new tests fail** — `cd frontend && npx vitest run src/lib/useLiveState.test.ts`.
- [ ] **Step 3: Implement** — modify `useLiveState.ts`:
  - Add refs: `const connectedRef = useRef(false)`, `const everConnectedRef = useRef(false)`, `const pollOkRef = useRef(false)`, `const reconnectingRef = useRef(false)`.
  - In `ws.onopen`: set `connectedRef.current = true`, `everConnectedRef.current = true`, `reconnectingRef.current = false`; keep `retry.current = 0`.
  - In `ws.onclose`: `connectedRef.current = false`, `reconnectingRef.current = true`, `setConnected(false)`, schedule reconnect.
  - Poll interval body: replace `if (connected) return;` with `if (connectedRef.current) return;`; on a successful fetch set `pollOkRef.current = true` + `setSnapshot(...)`; on failure `pollOkRef.current = false`.
  - Add state `const [connectionStatus, setConnectionStatus] = useState<ConnectionState>({ status: "connecting", stale: false })`.
  - Recompute status whenever inputs change: after seeding snapshot / on open / on close / on poll result, call a local `refreshStatus()` that reads the refs + `snapshot?.health?.last_heartbeat_age_s ?? null` and `setConnectionStatus(deriveConnection({...}))`. Simplest: a small `useEffect` on `[connected, snapshot]` plus explicit calls in onopen/onclose/poll. Keep it correct: derive from refs + latest snapshot.
  - Return `{ snapshot, events, connected, connectionStatus }`.

- [ ] **Step 4: Run to verify PASS** (existing 2 + new 2 = 4).
- [ ] **Step 5: Commit** — `fix(gui-fe2): useLiveState exposes connectionStatus + polls only while disconnected (stale-closure fix)` (+trailer).

---

### Task 3: `<Panel>` state wrapper

**Files:** Create `frontend/src/components/shell/Panel.tsx`, `frontend/src/components/shell/Panel.test.tsx`.

**Interfaces:**
- Produces: `<Panel status title? actions? onRetry? emptyMessage? children />` where
  `status: "loading" | "empty" | "error" | "populated" | "stale"`. `loading` → skeleton; `empty` →
  `emptyMessage`; `error` → message + a **Retry** button calling `onRetry`; `populated` → `children`;
  `stale` → `children` + a subtle "data may be delayed" marker. Uses role tokens + Card styling.

- [ ] **Step 1: Write the failing test** — `Panel.test.tsx`: `error` renders a Retry button that calls `onRetry`; `empty` renders the message; `loading` renders a skeleton (assert a `data-testid="skeleton"`); `stale` renders children + a `data-testid="stale-marker"`; `populated` renders children only.
```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Panel } from "./Panel";

describe("Panel", () => {
  it("error shows Retry that fires onRetry", async () => {
    const onRetry = vi.fn();
    render(<Panel status="error" onRetry={onRetry}>x</Panel>);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalled();
  });
  it("empty shows message; loading shows skeleton; stale marks children", () => {
    const { rerender } = render(<Panel status="empty" emptyMessage="No positions">x</Panel>);
    expect(screen.getByText("No positions")).toBeInTheDocument();
    rerender(<Panel status="loading">x</Panel>);
    expect(screen.getByTestId("skeleton")).toBeInTheDocument();
    rerender(<Panel status="stale"><span>rows</span></Panel>);
    expect(screen.getByText("rows")).toBeInTheDocument();
    expect(screen.getByTestId("stale-marker")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2–4:** fail → implement (a Card with an optional header [title + actions]; a body that switches on `status`; skeleton = a few pulsing `bg-surface-2` bars with `data-testid="skeleton"`; stale marker = a small amber `data-testid="stale-marker"` chip; respects reduced-motion) → PASS.
- [ ] **Step 5: Commit** — `feat(gui-fe2): <Panel> state wrapper (loading/empty/error/populated/stale)` (+trailer).

---

### Task 4: Sidebar

**Files:** Create `frontend/src/components/shell/Sidebar.tsx`, `frontend/src/components/shell/Sidebar.test.tsx`.

**Interfaces:**
- Consumes: `Logo` (Task 0), `useReadOnly`, react-router `NavLink`, lucide icons.
- Produces: `<Sidebar collapsed onToggleCollapse />`. Renders the brand (full/mark by `collapsed`), section `NavLink`s (Overview `/overview`, Positions `/positions`, Strategies `/strategies`, Activity `/activity`, Settings `/settings`) with icon+label and an active indicator; **disabled** Research/Journal items (with a "Phase 2" title); a collapse toggle; a read-only badge in the footer when `useReadOnly().readOnly`. Icon-only when `collapsed`. Full keyboard nav + focus-visible.

- [ ] **Step 1: Write the failing test** — `Sidebar.test.tsx` (wrap in `<MemoryRouter>` + `<ReadOnlyProvider>`): renders the 5 enabled nav links; Research/Journal are present but disabled (assert `aria-disabled` or `disabled`); the read-only badge appears only when the provider is read-only; the collapse toggle calls `onToggleCollapse`.
- [ ] **Step 2–4:** fail → implement → PASS.
- [ ] **Step 5: Commit** — `feat(gui-fe2): sidebar nav (sections, collapse, read-only badge, brand slot)` (+trailer).

---

### Task 5: Status bar

**Files:** Create `frontend/src/components/shell/StatusBar.tsx`, `frontend/src/components/shell/StatusBar.test.tsx`.

**Interfaces:**
- Consumes: `ConnectionState` (Task 1), `Snapshot` (`health`, `account`, `arbiter`), `money` (format), lucide icons.
- Produces: `<StatusBar connection snapshot onOpenPalette />`. A connection pill reflecting `connection.status` (Live=accent/ok, Reconnecting=warning+spinner, Degraded=warning, Offline=loss) + a **Stale** marker when `connection.stale`; a Paused indicator when `snapshot.health.paused`; a throttle indicator (with mult) when `snapshot.arbiter.throttle.enabled`; account balance/equity (tabular); a ⌘K button calling `onOpenPalette`. Every status = color + icon + text (never color-alone).

- [ ] **Step 1: Write the failing test** — `StatusBar.test.tsx`: `status:"degraded"` renders "Degraded"/polling text; `connection.stale` renders a "Stale" marker; `health.paused` renders "Paused"; `throttle.enabled` shows the mult; the ⌘K button calls `onOpenPalette`. (Pass a minimal snapshot fixture.)
- [ ] **Step 2–4:** fail → implement → PASS.
- [ ] **Step 5: Commit** — `feat(gui-fe2): top status bar (connection pill/stale/paused/throttle/account + ⌘K)` (+trailer).

---

### Task 6: Command palette (⌘K)

**Files:** Create `frontend/src/components/shell/CommandPalette.tsx`, `frontend/src/components/shell/CommandPalette.test.tsx`.

**Interfaces:**
- Consumes: `cmdk`, react-router `useNavigate`, `useReadOnly`.
- Produces: `<CommandPalette open onOpenChange actions />` where `actions` is a list of
  `{ id, label, run, destructive?, disabled? }`. Renders a cmdk dialog: a **Navigate** group (jump to each
  section via `useNavigate`) + an **Actions** group from `actions`. Read-only or `disabled` actions are
  shown disabled with a reason and cannot run. Selecting an item runs it and closes. Keyboard-operable;
  ARIA combobox (cmdk provides). NOTE: real command wiring (pause/close-all/panic/promote) is provided by
  Plan 2's sections/handlers; this task delivers the palette shell + the Navigate group + an `actions` prop
  contract, tested with injected fake actions.

- [ ] **Step 1: Write the failing test** — `CommandPalette.test.tsx` (in `<MemoryRouter>` + `<ReadOnlyProvider>`): with `open`, typing filters; selecting a Navigate item calls navigate (assert via a spy route or a location probe); a provided action's `run` fires on select; a `disabled` action does not run and is marked disabled.
- [ ] **Step 2–4:** fail → implement → PASS.
- [ ] **Step 5: Commit** — `feat(gui-fe2): ⌘K command palette shell (navigate group + read-only-aware action contract)` (+trailer).

---

### Task 7: Router + section stubs + AppShell + App wiring

**Files:** Create `frontend/src/routes/router.tsx`, `frontend/src/components/shell/AppShell.tsx`, `frontend/src/sections/{Overview,Positions,Strategies,Activity,Settings}Page.tsx`; Modify `frontend/src/App.tsx`; Test `frontend/src/App.test.tsx` (replace the v1 test).

**Interfaces:**
- Consumes: everything above.
- Produces:
  - Section stubs: each a default-export page rendering a `<Panel status="empty" title=...>` placeholder ("Overview — coming in Plan 2") so the shell is fully navigable. (Plan 2 replaces these bodies.)
  - `router.tsx`: a `createHashRouter` (or `createBrowserRouter` — hash avoids server-rewrite needs; the SPA fallback covers browser history too) with `AppShell` as the layout route and the 5 sections as children; index → `/overview`; unknown → `/overview`.
  - `AppShell.tsx`: composes `<Sidebar>` + `<StatusBar>` + `<main><Outlet/></main>` + `<CommandPalette>`; owns sidebar-collapsed state (persisted to `localStorage`), palette open state (⌘K keydown + the StatusBar trigger), and receives `connection`/`snapshot` from App via context or props. On route change, moves focus to `<main>`.
  - `App.tsx`: `TokenGate` → `ReadOnlyProvider` → build `api` + `useLiveState(token)` → provide `snapshot`/`events`/`connectionStatus`/`api` via a small `ControllerContext` → `RouterProvider(router)`. On any `ApiError.kind==="readOnly"`, flip `ReadOnlyContext`. Show a full-screen "Connecting…" only in `connecting` before the first snapshot.

- [ ] **Step 1: Write the failing test** — `App.test.tsx`: mock `useLiveState` to return a seeded snapshot + `connectionStatus:{status:"live",stale:false}`; render `<App/>`; enter the token (TokenGate); assert the shell renders (sidebar sections + the status bar "Live" pill) and the Overview stub is shown; clicking the Positions nav shows the Positions stub. Pressing ⌘K opens the palette (assert the palette dialog appears).
- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Implement** the router, AppShell, stubs, App wiring (+ a tiny `ControllerContext` exposing `{snapshot, events, connectionStatus, api}`).
- [ ] **Step 4: Run to verify PASS.**
- [ ] **Step 5: Build check** — `cd frontend && npm run build` (FOREGROUND, timeout 600000) succeeds.
- [ ] **Step 6: Commit** — `feat(gui-fe2): router + AppShell + section stubs + App wiring (navigable new shell)` (+trailer).

---

### Task 8: Foundation verification (build + live-drive + full FE suite)

- [ ] **Step 1:** Full frontend test run: `cd frontend && npm test` (FOREGROUND, timeout 600000) — ALL green (new foundation tests + the retained data-layer tests). Report the count.
- [ ] **Step 2:** `cd frontend && npm run build` — clean; `frontend/dist/index.html` present.
- [ ] **Step 3 (live-drive — MANDATORY, it caught the WS bug last time):** run the demo server
  (`TITAN_GUI_TOKEN=devtoken .venv/bin/python scripts/gui_demo_server.py`) and drive the real UI with the
  Playwright headless-shell (see `scripts`/scratch drive from Phase 1b): load `:8770`, enter the token,
  confirm the new **sidebar + status bar** render, the **connection pill** shows Live, ⌘K opens the
  palette, and each section nav routes to its stub. Toggle `TITAN_GUI_READONLY=1` → read-only badge shows.
  Capture screenshots at desktop + a tablet + a phone viewport (verify the sidebar → rail → bottom-tab
  responsive collapse). If no browser is available, record deferred (rely on the Vitest suite).
- [ ] **Step 4:** Design-review pass on the screenshots (spacing/hierarchy/contrast/AI-slop). Record findings; fix Criticals.
- [ ] **Step 5 (no commit):** record results in the SDD ledger. Confirm the Python GUI suite still green
  (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_gui_*.py'`) — foundation touches no Python,
  so this is a sanity check.

---

## Self-Review

**Spec coverage (§ of `2026-07-15-titan-gui-redesign-design.md`):** design-token contract §7 → T0; connection-state machine §6.1 → T1 + T2 (poll fix); `<Panel>` state matrix §6.2 → T3; sidebar §4.1 → T4; status bar §4.2 → T5; ⌘K palette §4.3 (shell + contract; full action wiring is Plan 2) → T6; router/deep-linking §4.4 + AppShell §4 + App wiring → T7; responsive collapse §6.3 exercised in the live-drive → T8; keep-vs-rebuild §3 (data layer kept, `useLiveState` modified backward-compatibly, backend untouched) → constraints + T2. Sections' bodies (§5) and real command/mutation wiring, virtualization (§6.4), and full a11y/contrast on brand surfaces are **Plan 2** (stated in T6/§ non-goals) — not gaps.
**Placeholder scan:** tokens are deliberately placeholder VALUES behind fixed ROLE names (§7 strategy), not TBDs; every task has concrete code or a concrete build-to spec + test. The shell-component tasks (T3–T6) specify exact props + tests rather than full JSX (same proven style as the Phase-1b plan) — behavior is pinned by tests, appearance by the token system.
**Type consistency:** `ConnectionStatus`/`ConnectionState`/`deriveConnection` (T1) consumed unchanged by `useLiveState` (T2), `StatusBar` (T5), `AppShell`/`App` (T7); `useLiveState` return `{snapshot,events,connected,connectionStatus}` stable across T2/T5/T7; `<Panel status>` union stable T3→sections; `actions` shape stable T6→Plan 2; `Logo variant` stable T0→T4.
