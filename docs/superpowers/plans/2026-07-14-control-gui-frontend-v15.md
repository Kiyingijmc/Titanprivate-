# Titan Control GUI — Frontend (React SPA) Implementation Plan, v15 (Phase 1b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dark-mode operator cockpit SPA (Vite + React + TypeScript + Tailwind + shadcn/ui + Recharts) that consumes the Phase 1a control API — live cockpit (health/positions/PnL/event-feed), controls with confirm dialogs, Strategies tab (typed-id promote), Settings tab (source/tier badges, live vs restart), read-only mode — built to `frontend/dist/` and served same-origin by the Phase 1a FastAPI server.

**Architecture:** Single SPA under `frontend/`. A pure data layer (typed API client + a `useLiveState` WebSocket hook with first-frame token auth, reconnect backoff, and a `GET /api/state` polling fallback) feeds three tab views (Cockpit / Strategies / Settings; Research + Journal scaffolded, empty until Phase 2). Every mutating control is gated by a read-only context and (for destructive/promote actions) a confirm dialog that mirrors the backend confirm-gate. The built `dist/` is mounted as static files by the Phase 1a server (SPA fallback to `index.html`); a fake-controller dev mode lets the whole thing be driven with MT5 offline.

**Tech Stack:** Vite 5, React 18, TypeScript 5, Tailwind 3, shadcn/ui (Radix), Recharts 2, lucide-react, Vitest + @testing-library/react + jsdom (unit/component tests). Backend serving via `fastapi.staticfiles.StaticFiles` (added to the existing `src/ops/web/server.py`).

**Design system (CITE THIS — implementers MUST match its tokens; do not invent colors/fonts):**
`docs/superpowers/specs/2026-07-14-control-gui-frontend-design-system.md`. Backend API contract + auth:
`docs/superpowers/specs/2026-07-14-control-gui-phase1-v15-design.md` (§"API contract").

**Design skills (MANDATORY — invoke before the work they gate):**
- `ui-ux-pro-max` — the design system above was produced with it; every component task must match those tokens/patterns.
- `dataviz` — REQUIRED reading before ANY chart code (Task 5, equity sparkline). The chart specs in the design-system doc §5 come from it: single-series line/area, no legend, `--primary` line, recessive grid, hover crosshair+tooltip, reduced-motion, tabular figures.
- `design-review` (gstack) — run as the final visual QA pass in Task 9 IF a browser is available; otherwise record as deferred.

## Global Constraints

- Work continues on the EXISTING branch **`feat/control-gui-backend`** (Phase 1a). No merge to `main`; no git remote — never push. BRANCH GUARD every implementer: a concurrent user session shares the working tree; assert `git branch --show-current` == `feat/control-gui-backend` before editing and before committing, and `git checkout` back if it drifted.
- **Stage ONLY your task's exact files** (explicit `git add <paths>`, never `git add -A`/`.`). NEVER stage the concurrent user's files: `mql5_bridge/Experts/Titan_Gateway.mq5`, `data/specs.json`, `scripts/check_bridge.py`, `tests/unit/test_check_bridge_ip.py`, `src/data/lake.py`, `tests/unit/test_lake.py`, or anything outside `frontend/**` + (Task 8 only) `src/ops/web/server.py` + `tests/unit/test_gui_server_static.py`.
- **FROZEN, never modify:** `scripts/capture_parity_golden.py`, `tests/backtest/fixtures/*`, `tests/unit/test_signal_parity.py`. Frontend work touches none of these.
- **The Phase 1a backend is DONE and must not regress.** Task 8 only ADDS a static mount + optional fake-controller dev mode to `server.py`; it must not change any existing route, the audit invariant, or auth. The Python suite (`.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`) must stay green (60 GUI tests + parity). Frontend tests run via `npm test` inside `frontend/`.
- **Self-contained / CSP-friendly:** the SPA is served same-origin; API base is RELATIVE (`/api`, `/ws`). NO external hosts — self-host fonts (woff2 in `frontend/src/assets/fonts/`), no font/script CDN, no remote images. Recharts/lucide are npm deps bundled by Vite.
- **Dark-mode only** (operator cockpit). Tokens from the design-system doc §2. Fira Sans (body) + Fira Code (headings/mono/tabular numbers). Lucide SVG icons only — never emoji.
- **Read-only mode:** when the app is in read-only mode, ALL mutating controls (command buttons, enable/disable/promote, settings edits) are disabled + greyed with a visible banner; reads stay live.
- Node: use the system `npm`/`node` (Vite 5 needs Node ≥18). All npm commands run from `frontend/`.
- Commit messages end with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

## File Structure

```
frontend/
  package.json, vite.config.ts, tsconfig.json, tailwind.config.ts, postcss.config.js,
  index.html, .gitignore, vitest.setup.ts
  src/
    main.tsx, App.tsx, index.css
    lib/
      types.ts          # API DTOs (Snapshot, Position, FeedEvent, SettingRow, RegistryRow, ...)
      api.ts            # typed REST client (bearer auth, 401/429/403 mapping)
      format.ts         # pure formatters (money, pnl sign+color, age, side)
      useLiveState.ts   # WS hook: first-frame token auth, reconnect, GET /api/state fallback
    components/ui/      # shadcn primitives (button, card, dialog, table, badge, input, ...)
    components/
      TokenGate.tsx     # enter-token screen; stores token in memory
      ReadOnlyBanner.tsx
      HealthStrip.tsx
      StatTiles.tsx
      EquitySparkline.tsx
      PositionsTable.tsx
      Controls.tsx
      EventFeed.tsx
      StrategiesTab.tsx
      SettingsTab.tsx
    context/ReadOnlyContext.tsx
    assets/fonts/*.woff2
  dist/                 # build output (gitignored)
```

Backend (Task 8): modify `src/ops/web/server.py` (+ `tests/unit/test_gui_server_static.py`).

---

### Task 0: Scaffold + toolchain + design tokens

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/tailwind.config.ts`, `frontend/postcss.config.js`, `frontend/index.html`, `frontend/.gitignore`, `frontend/vitest.setup.ts`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/index.css`, `frontend/src/lib/utils.ts`
- Test: `frontend/src/lib/format.test.ts` (proves the toolchain runs a test) — but format.ts lands in Task 1; for Task 0 the smoke test is a trivial `frontend/src/smoke.test.ts`.

**Interfaces:**
- Produces: a buildable Vite app (`npm run build` → `frontend/dist/`), a passing `npm test` (Vitest + jsdom), Tailwind wired to the design-system tokens (CSS vars + `tailwind.config` theme extension), self-hosted Fira fonts, and `cn()` in `lib/utils.ts` (shadcn's classname helper).

- [ ] **Step 1: Scaffold + deps.** In `frontend/`, create `package.json`:

```json
{
  "name": "titan-control-gui",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.1",
    "lucide-react": "^0.454.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "recharts": "^2.13.0",
    "tailwind-merge": "^2.5.4"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.11",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "autoprefixer": "^10.4.20",
    "jsdom": "^25.0.1",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.14",
    "typescript": "^5.6.3",
    "vite": "^5.4.10",
    "vitest": "^2.1.4"
  }
}
```

Run: `cd frontend && npm install` (FOREGROUND). If the registry is unreachable, STOP and report BLOCKED (offline env) — do not fabricate a lockfile.

- [ ] **Step 2: Config files.**

`frontend/vite.config.ts`:
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  base: "./",                       // relative asset URLs — served same-origin from FastAPI
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: { outDir: "dist", emptyOutDir: true },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
  },
});
```

`frontend/vitest.setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";
```

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020", "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"], "module": "ESNext",
    "skipLibCheck": true, "moduleResolution": "bundler",
    "resolveJsonModule": true, "isolatedModules": true, "noEmit": true,
    "jsx": "react-jsx", "strict": true, "noUnusedLocals": true,
    "noUnusedParameters": true, "noFallthroughCasesInSwitch": true,
    "baseUrl": ".", "paths": { "@/*": ["src/*"] }
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`frontend/tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "composite": true, "skipLibCheck": true, "module": "ESNext",
    "moduleResolution": "bundler", "allowSyntheticDefaultImports": true, "noEmit": true
  },
  "include": ["vite.config.ts"]
}
```

`frontend/postcss.config.js`:
```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

- [ ] **Step 3: Tailwind theme = the design-system tokens.** `frontend/tailwind.config.ts` (colors reference CSS vars defined in index.css so shadcn's `bg-background`/`text-foreground` conventions work):

```ts
import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        // semantic (design-system §2) — always paired with an icon+label in UI
        profit: "hsl(var(--profit))",
        loss: "hsl(var(--loss))",
        warning: "hsl(var(--warning))",
        info: "hsl(var(--info))",
        blocked: "hsl(var(--blocked))",
        destructive: { DEFAULT: "hsl(var(--loss))", foreground: "#ffffff" },
      },
      borderRadius: { lg: "8px", md: "6px", sm: "4px" },
      fontFamily: {
        sans: ["'Fira Sans'", "system-ui", "sans-serif"],
        mono: ["'Fira Code'", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
```

- [ ] **Step 4: `frontend/src/index.css`** — token values (design-system §2, as HSL), self-hosted fonts, base:

```css
/* Self-host Fira fonts (woff2 placed in src/assets/fonts/; @font-face them — NO CDN).
   If woff2 files are not yet vendored, this @font-face is inert and the stack falls
   back to system-ui/monospace; Task 0 accepts that fallback (fonts vendored best-effort). */
@font-face { font-family: "Fira Sans"; src: local("Fira Sans"); font-display: swap; }
@font-face { font-family: "Fira Code"; src: local("Fira Code"); font-display: swap; }

@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  /* design-system §2 — dark cockpit, expressed as HSL for the hsl(var(--x)) convention */
  --background: 222 47% 11%;        /* #0F172A */
  --foreground: 210 40% 98%;        /* #F8FAFC */
  --card: 222 24% 17%;              /* #222735 */
  --card-foreground: 210 40% 98%;
  --muted: 222 30% 21%;             /* #272F42 */
  --muted-foreground: 215 20% 65%;  /* #94A3B8 */
  --border: 215 25% 27%;            /* #334155 */
  --input: 215 25% 27%;
  --ring: 214 77% 56%;              /* #3987E5 */
  --primary: 214 77% 56%;           /* #3987E5 */
  --primary-foreground: 0 0% 100%;
  --profit: 142 71% 45%;            /* #22C55E */
  --loss: 0 84% 60%;                /* #EF4444 */
  --warning: 38 92% 50%;            /* #F59E0B */
  --info: 199 92% 60%;              /* #38BDF8 */
  --blocked: 255 92% 76%;           /* #A78BFA */
}

html { color-scheme: dark; }
body {
  margin: 0;
  background: hsl(var(--background));
  color: hsl(var(--foreground));
  font-family: "Fira Sans", system-ui, sans-serif;
  font-size: 16px;
  line-height: 1.5;
}
.tabnum { font-variant-numeric: tabular-nums; }   /* numbers in columns */
@media (prefers-reduced-motion: reduce) {
  * { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
}
```

- [ ] **Step 5: `frontend/index.html`, `main.tsx`, `App.tsx`, `lib/utils.ts`, `.gitignore`.**

`frontend/index.html`:
```html
<!doctype html>
<html lang="en" class="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Titan Control</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/main.tsx`:
```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>
);
```

`frontend/src/App.tsx` (placeholder for Task 0; replaced in Task 3):
```tsx
export default function App() {
  return <div className="p-6 font-mono text-foreground">Titan Control — booting…</div>;
}
```

`frontend/src/lib/utils.ts`:
```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: ClassValue[]) { return twMerge(clsx(inputs)); }
```

`frontend/.gitignore`:
```
node_modules
dist
*.local
```

- [ ] **Step 6: Smoke test.** `frontend/src/smoke.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { cn } from "./lib/utils";
describe("toolchain", () => {
  it("merges classes", () => { expect(cn("p-2", "p-4")).toBe("p-4"); });
});
```

- [ ] **Step 7: Verify** — `cd frontend && npm test` → 1 passing; `npm run build` → `dist/index.html` exists. Both FOREGROUND.
- [ ] **Step 8: Commit** — `feat(gui-fe): scaffold Vite+React+TS+Tailwind+Vitest with cockpit design tokens` (+trailer). Stage `frontend/**` only (respecting `frontend/.gitignore`, so `node_modules`/`dist` are excluded).

---

### Task 1: Types + formatters (pure)

**Files:**
- Create: `frontend/src/lib/types.ts`, `frontend/src/lib/format.ts`
- Test: `frontend/src/lib/format.test.ts`

**Interfaces:**
- Produces:
  - `types.ts`: `Health`, `Account`, `Position`, `ArbiterBlock`, `RegistryRow`, `Snapshot`, `FeedEvent`, `SettingRow`, `HistoryRow`, `CommandResult`, `SettingsPatchResult` — mirroring the Phase 1a API contract (§"API contract" of the backend spec) and the snapshot shape from `state_view.build_snapshot` (health/account/positions/arbiter/registry) and `settings.describe()` (`{key,value,source,tier}`).
  - `format.ts`: `money(n)`, `signedPnl(n) -> {text, tone: "profit"|"loss"|"flat"}`, `ageLabel(seconds)`, `sideLabel(side)`.

- [ ] **Step 1: Write the failing test** — `frontend/src/lib/format.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { money, signedPnl, ageLabel } from "./format";

describe("format", () => {
  it("money is fixed-2 with thousands", () => {
    expect(money(10250)).toBe("10,250.00");
    expect(money(-3.5)).toBe("-3.50");
  });
  it("signedPnl tags tone by sign", () => {
    expect(signedPnl(12.5)).toEqual({ text: "+12.50", tone: "profit" });
    expect(signedPnl(-4)).toEqual({ text: "-4.00", tone: "loss" });
    expect(signedPnl(0)).toEqual({ text: "0.00", tone: "flat" });
  });
  it("ageLabel is human", () => {
    expect(ageLabel(2)).toBe("2s");
    expect(ageLabel(125)).toBe("2m 5s");
  });
});
```

- [ ] **Step 2: Run to verify it fails** — `cd frontend && npx vitest run src/lib/format.test.ts` → module not found.

- [ ] **Step 3: Implement** — `frontend/src/lib/types.ts`:
```ts
export interface Health { bridge_connected: boolean; last_heartbeat_age_s: number; paused: boolean; last_error: string | null; }
export interface Account { balance: number; equity: number; }
export interface Position {
  ticket: number; symbol: string; side: "BUY" | "SELL"; lots: number;
  entry: number; sl: number; tp: number; pnl: number; grade: string; strategy: string;
}
export interface ArbiterBlock {
  stats: { submitted: number; approved: number; blocked_by: Record<string, number> };
  throttle: { enabled: boolean; current_mult: number };
}
export interface RegistryRow {
  id: string; version: string; status: string; state: string; tf?: string; priority?: number; family?: string;
}
export interface Snapshot {
  health: Health; account: Account; positions: Position[]; arbiter: ArbiterBlock; registry: RegistryRow[];
}
export interface FeedEvent { topic: string; ts: number; [k: string]: unknown; }
export interface SettingRow { key: string; value: unknown; source: "default" | "override"; tier: "live" | "restart"; }
export interface HistoryRow { [k: string]: unknown; }
export interface CommandResult { status: string; result?: unknown; detail?: string; command?: string; }
export interface SettingsPatchResult { applied?: string; restart_required?: boolean; value?: unknown; detail?: string; }
```

`frontend/src/lib/format.ts`:
```ts
export function money(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function signedPnl(n: number): { text: string; tone: "profit" | "loss" | "flat" } {
  const tone = n > 0 ? "profit" : n < 0 ? "loss" : "flat";
  const sign = n > 0 ? "+" : "";                         // negatives already carry "-"
  return { text: `${sign}${money(n)}`, tone };
}

export function ageLabel(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${s % 60}s`;
}

export function sideLabel(side: "BUY" | "SELL"): "BUY" | "SELL" { return side; }
```

- [ ] **Step 4: Run to verify PASS** (3 tests).
- [ ] **Step 5: Commit** — `feat(gui-fe): API DTO types + pure formatters (money/pnl-tone/age)` (+trailer).

---

### Task 2: API client + `useLiveState` WS hook (the data layer)

**Files:**
- Create: `frontend/src/lib/api.ts`, `frontend/src/lib/useLiveState.ts`
- Test: `frontend/src/lib/api.test.ts`, `frontend/src/lib/useLiveState.test.ts`

**Interfaces:**
- Consumes: `types.ts` (Task 1).
- Produces:
  - `api.ts`: `createApi(getToken: () => string)` → `{ getState, getEvents, getHistory, getSettings, getRegistry, postCommand, patchSetting, registryAction }`. Every call sends `Authorization: Bearer <token>`; maps HTTP status → a typed `ApiError { status, detail }` (401 unauthorized, 429 throttled, 403 readOnly, 422 validation).
  - `useLiveState(token, opts?)`: React hook returning `{ snapshot, events, connected, readOnly }`. Opens `/ws`, sends the token as the FIRST text frame, seeds from `{type:"state"}`, appends `{type:"event"}` to a bounded feed (≤200). On close/error: exponential backoff reconnect; while disconnected, poll `GET /api/state` on an interval. Detects read-only by probing a HEAD/None — actually read-only is surfaced by a 403 on the first mutation; expose `readOnly` as false initially and let callers set it (see note). WebSocket + fetch are injected via `opts` for tests.

- [ ] **Step 1: Write the failing tests** — `frontend/src/lib/api.test.ts`:
```ts
import { describe, it, expect, vi } from "vitest";
import { createApi, ApiError } from "./api";

function fakeFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300, status,
    json: async () => body, text: async () => JSON.stringify(body),
  });
}

describe("api client", () => {
  it("sends bearer token and returns json", async () => {
    const f = fakeFetch(200, { health: {}, positions: [] });
    const api = createApi(() => "tok", { fetchImpl: f as unknown as typeof fetch });
    const snap = await api.getState();
    expect(snap).toHaveProperty("positions");
    const [, init] = f.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });

  it("maps 401/429/403/422 to typed ApiError", async () => {
    for (const [status, kind] of [[401, "unauthorized"], [429, "throttled"], [403, "readOnly"], [422, "validation"]] as const) {
      const api = createApi(() => "tok", { fetchImpl: fakeFetch(status, { detail: "x" }) as unknown as typeof fetch });
      await expect(api.getState()).rejects.toMatchObject({ status, kind } satisfies Partial<ApiError>);
    }
  });

  it("postCommand posts json body", async () => {
    const f = fakeFetch(200, { status: "ok", result: "PAUSED" });
    const api = createApi(() => "tok", { fetchImpl: f as unknown as typeof fetch });
    const r = await api.postCommand({ command: "pause" });
    expect(r.result).toBe("PAUSED");
    const [url, init] = f.mock.calls[0];
    expect(String(url)).toContain("/api/command");
    expect(init.method).toBe("POST");
  });
});
```

`frontend/src/lib/useLiveState.test.ts`:
```ts
import { describe, it, expect, vi } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useLiveState } from "./useLiveState";

class FakeWS {
  static last: FakeWS | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];
  readyState = 0;
  constructor(public url: string) { FakeWS.last = this; }
  send(d: string) { this.sent.push(d); }
  close() { this.readyState = 3; this.onclose?.(); }
  open() { this.readyState = 1; this.onopen?.(); }
  message(obj: unknown) { this.onmessage?.({ data: JSON.stringify(obj) }); }
}

describe("useLiveState", () => {
  it("sends token as first frame, seeds snapshot, appends events", async () => {
    const { result } = renderHook(() =>
      useLiveState("sekret", { WebSocketImpl: FakeWS as unknown as typeof WebSocket, pollFallback: false }));
    act(() => { FakeWS.last!.open(); });
    expect(FakeWS.last!.sent[0]).toBe("sekret");         // FIRST frame is the token
    act(() => { FakeWS.last!.message({ type: "state", health: { paused: false }, positions: [] }); });
    await waitFor(() => expect(result.current.snapshot).not.toBeNull());
    expect(result.current.connected).toBe(true);
    act(() => { FakeWS.last!.message({ type: "event", topic: "IntentBlocked", ts: 1, rule: "opposition" }); });
    await waitFor(() => expect(result.current.events.at(-1)?.topic).toBe("IntentBlocked"));
  });

  it("caps the event buffer at 200", async () => {
    const { result } = renderHook(() =>
      useLiveState("t", { WebSocketImpl: FakeWS as unknown as typeof WebSocket, pollFallback: false, maxEvents: 3 }));
    act(() => { FakeWS.last!.open(); });
    act(() => { for (let i = 0; i < 5; i++) FakeWS.last!.message({ type: "event", topic: "T", ts: i }); });
    await waitFor(() => expect(result.current.events.length).toBe(3));
    expect(result.current.events[0].ts).toBe(2);         // oldest dropped
  });
});
```

- [ ] **Step 2: Run to verify they fail** — module not found.

- [ ] **Step 3: Implement** — `frontend/src/lib/api.ts`:
```ts
import type { Snapshot, FeedEvent, SettingRow, RegistryRow, CommandResult, SettingsPatchResult, HistoryRow } from "./types";

export interface ApiError { status: number; kind: "unauthorized" | "throttled" | "readOnly" | "validation" | "error"; detail: string; }
function kindFor(status: number): ApiError["kind"] {
  return status === 401 ? "unauthorized" : status === 429 ? "throttled"
    : status === 403 ? "readOnly" : status === 422 ? "validation" : "error";
}

interface Opts { fetchImpl?: typeof fetch; base?: string; }

export function createApi(getToken: () => string, opts: Opts = {}) {
  const f = opts.fetchImpl ?? fetch;
  const base = opts.base ?? "";
  async function req<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await f(`${base}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}`, ...(init?.headers ?? {}) },
    });
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json())?.detail ?? detail; } catch { /* ignore */ }
      const err: ApiError = { status: res.status, kind: kindFor(res.status), detail };
      throw err;
    }
    return (await res.json()) as T;
  }
  return {
    getState: () => req<Snapshot>("/api/state"),
    getEvents: (limit = 200) => req<{ events: FeedEvent[] }>(`/api/events?limit=${limit}`).then(r => r.events),
    getHistory: (limit = 50) => req<{ history: HistoryRow[] }>(`/api/history?limit=${limit}`).then(r => r.history),
    getSettings: () => req<{ settings: SettingRow[] }>("/api/settings").then(r => r.settings),
    getRegistry: () => req<{ registry: RegistryRow[] }>("/api/registry").then(r => r.registry),
    postCommand: (body: Record<string, unknown>) => req<CommandResult>("/api/command", { method: "POST", body: JSON.stringify(body) }),
    patchSetting: (key: string, value: unknown) => req<SettingsPatchResult>("/api/settings", { method: "PATCH", body: JSON.stringify({ key, value }) }),
    registryAction: (sid: string, action: string, body: Record<string, unknown> = {}) =>
      req<CommandResult>(`/api/registry/${encodeURIComponent(sid)}/${action}`, { method: "POST", body: JSON.stringify(body) }),
  };
}
export type Api = ReturnType<typeof createApi>;
```

`frontend/src/lib/useLiveState.ts`:
```ts
import { useEffect, useRef, useState } from "react";
import type { Snapshot, FeedEvent } from "./types";

interface Opts {
  WebSocketImpl?: typeof WebSocket;
  pollFallback?: boolean;      // default true; poll GET /api/state while disconnected
  maxEvents?: number;          // default 200
  base?: string;               // default "" (same-origin)
}

export function useLiveState(token: string | null, opts: Opts = {}) {
  const WS = opts.WebSocketImpl ?? (typeof WebSocket !== "undefined" ? WebSocket : undefined);
  const maxEvents = opts.maxEvents ?? 200;
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [events, setEvents] = useState<FeedEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const retry = useRef(0);
  const stopped = useRef(false);

  useEffect(() => {
    if (!token || !WS) return;
    stopped.current = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const proto = typeof location !== "undefined" && location.protocol === "https:" ? "wss" : "ws";
      const host = typeof location !== "undefined" ? location.host : "localhost";
      ws = new WS(`${opts.base ?? `${proto}://${host}`}/ws`);
      ws.onopen = () => { ws!.send(token); retry.current = 0; };   // FIRST frame = token
      ws.onmessage = (e: MessageEvent) => {
        const msg = JSON.parse(e.data);
        if (msg.type === "state") { const { type, ...snap } = msg; setSnapshot(snap as Snapshot); setConnected(true); }
        else if (msg.type === "event") { const { type, ...ev } = msg; setEvents(prev => [...prev, ev as FeedEvent].slice(-maxEvents)); }
      };
      ws.onclose = () => { setConnected(false); scheduleReconnect(); };
      ws.onerror = () => { try { ws?.close(); } catch { /* ignore */ } };
    };
    const scheduleReconnect = () => {
      if (stopped.current) return;
      const delay = Math.min(1000 * 2 ** retry.current, 15000);
      retry.current += 1;
      reconnectTimer = setTimeout(connect, delay);
    };
    connect();

    // polling fallback while disconnected (same-origin GET /api/state)
    let poll: ReturnType<typeof setInterval> | undefined;
    if (opts.pollFallback !== false && typeof fetch !== "undefined") {
      poll = setInterval(async () => {
        if (connected) return;
        try {
          const r = await fetch(`${opts.base ?? ""}/api/state`, { headers: { Authorization: `Bearer ${token}` } });
          if (r.ok) setSnapshot(await r.json());
        } catch { /* ignore */ }
      }, 5000);
    }

    return () => {
      stopped.current = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (poll) clearInterval(poll);
      try { ws?.close(); } catch { /* ignore */ }
    };
  }, [token]);   // eslint-disable-line react-hooks/exhaustive-deps

  return { snapshot, events, connected };
}
```

> Note on read-only: read-only is detected reactively — the first mutating call returns `ApiError.kind === "readOnly"` (403). The app surfaces read-only from that error (Task 3's ReadOnlyContext), not from the WS hook. The hook stays read-only-agnostic.

- [ ] **Step 4: Run to verify PASS** (api 3 + hook 2).
- [ ] **Step 5: Commit** — `feat(gui-fe): typed API client + useLiveState WS hook (first-frame auth, reconnect, poll fallback)` (+trailer).

---

### Task 3: App shell — shadcn primitives, token gate, tabs, read-only context

**Files:**
- Create: `frontend/src/components/ui/{button,card,badge,input,dialog,table,tabs,alert-dialog}.tsx` (shadcn primitives), `frontend/src/context/ReadOnlyContext.tsx`, `frontend/src/components/TokenGate.tsx`, `frontend/src/components/ReadOnlyBanner.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/components/TokenGate.test.tsx`, `frontend/src/context/ReadOnlyContext.test.tsx`

**Interfaces:**
- Consumes: `useLiveState` (Task 2), `cn` (Task 0).
- Produces:
  - shadcn primitives (standard shadcn/ui source — Button with `variant`/`size`, Card, Badge with `variant`, Input, Dialog, AlertDialog, Table, Tabs). Use the canonical shadcn implementations (Radix-based); they consume the Tailwind tokens from Task 0.
  - `ReadOnlyContext` = `{ readOnly: boolean, setReadOnly(v): void }` via `useReadOnly()`.
  - `TokenGate`: renders a token-entry form when no token is set; on submit stores the token in memory (React state) and renders children. Token never touches the URL or localStorage-by-default.
  - `App`: TokenGate → tab layout (Cockpit / Strategies / Settings, + disabled Research/Journal tabs) with the ReadOnlyBanner shown when `readOnly`.

- [ ] **Step 1: Write the failing tests** — `frontend/src/context/ReadOnlyContext.test.tsx`:
```tsx
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReadOnlyProvider, useReadOnly } from "./ReadOnlyContext";

function Probe() {
  const { readOnly, setReadOnly } = useReadOnly();
  return <button onClick={() => setReadOnly(true)}>{readOnly ? "RO" : "RW"}</button>;
}
describe("ReadOnlyContext", () => {
  it("defaults RW and flips to RO", () => {
    render(<ReadOnlyProvider><Probe /></ReadOnlyProvider>);
    expect(screen.getByRole("button").textContent).toBe("RW");
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button").textContent).toBe("RO");
  });
});
```

`frontend/src/components/TokenGate.test.tsx`:
```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TokenGate } from "./TokenGate";

describe("TokenGate", () => {
  it("gates children until a token is entered", async () => {
    render(<TokenGate>{(token) => <div>token:{token}</div>}</TokenGate>);
    expect(screen.queryByText(/token:/)).toBeNull();
    await userEvent.type(screen.getByLabelText(/token/i), "sekret");
    await userEvent.click(screen.getByRole("button", { name: /connect/i }));
    expect(screen.getByText("token:sekret")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** Generate the shadcn primitives from the canonical shadcn/ui source (Button, Card, Badge, Input, Dialog, AlertDialog, Table, Tabs) — do NOT hand-roll novel variants; use the standard component code (Radix + cva) so they inherit the Task-0 tokens. Then:

`frontend/src/context/ReadOnlyContext.tsx`:
```tsx
import { createContext, useContext, useState, type ReactNode } from "react";
const Ctx = createContext<{ readOnly: boolean; setReadOnly: (v: boolean) => void } | null>(null);
export function ReadOnlyProvider({ children }: { children: ReactNode }) {
  const [readOnly, setReadOnly] = useState(false);
  return <Ctx.Provider value={{ readOnly, setReadOnly }}>{children}</Ctx.Provider>;
}
export function useReadOnly() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useReadOnly outside provider");
  return v;
}
```

`frontend/src/components/TokenGate.tsx`:
```tsx
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";

export function TokenGate({ children }: { children: (token: string) => ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  if (token) return <>{children(token)}</>;
  return (
    <div className="min-h-dvh grid place-items-center">
      <Card className="p-6 w-80 space-y-4">
        <h1 className="font-mono text-lg">Titan Control</h1>
        <label className="block text-sm text-muted-foreground" htmlFor="token">Access token</label>
        <Input id="token" type="password" value={draft} onChange={(e) => setDraft(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter" && draft) setToken(draft); }} />
        <Button className="w-full" disabled={!draft} onClick={() => setToken(draft)}>Connect</Button>
      </Card>
    </div>
  );
}
```

`frontend/src/components/ReadOnlyBanner.tsx`:
```tsx
import { Lock } from "lucide-react";
export function ReadOnlyBanner() {
  return (
    <div className="flex items-center gap-2 bg-warning/15 text-warning border border-warning/30 rounded-md px-3 py-1.5 text-sm">
      <Lock className="size-4" aria-hidden /> Read-only mode — controls disabled
    </div>
  );
}
```

`frontend/src/App.tsx` — TokenGate → ReadOnlyProvider → Tabs (Cockpit/Strategies/Settings + disabled Research/Journal), banner when readOnly, driven by `useLiveState(token)`. (Panels are placeholders here; Tasks 4–7 fill them. Show the ReadOnlyBanner when `useReadOnly().readOnly`.) Wire `useLiveState(token)` and pass `snapshot`/`events` down.

- [ ] **Step 4: Run to verify PASS.**
- [ ] **Step 5: Build check** — `npm run build` succeeds (catches shadcn import/type errors).
- [ ] **Step 6: Commit** — `feat(gui-fe): app shell — shadcn primitives, token gate, tabs, read-only context` (+trailer).

---

### Task 4: Cockpit — HealthStrip + StatTiles

**Files:**
- Create: `frontend/src/components/HealthStrip.tsx`, `frontend/src/components/StatTiles.tsx`
- Test: `frontend/src/components/HealthStrip.test.tsx`, `frontend/src/components/StatTiles.test.tsx`

**Interfaces:**
- Consumes: `Snapshot`, `format.ts`, shadcn Badge/Card.
- Produces: `<HealthStrip health snapshotArbiter />` (status pills: bridge connected/stale, heartbeat age, paused, throttle-active w/ multiplier) and `<StatTiles account arbiter />` (hero-number tiles: balance, equity, open positions, arbiter approved/blocked; day-PnL tile colored by sign WITH arrow icon). Every status uses color + Lucide icon + text (design-system §5, color-not-alone).

- [ ] **Step 1: Write the failing tests** — `HealthStrip.test.tsx`: renders "stale" when `bridge_connected=false`, shows throttle multiplier when `throttle.enabled`, shows "Paused" when `health.paused`. `StatTiles.test.tsx`: equity renders formatted; a negative day-PnL tile has the loss tone class + a down-arrow icon (assert by `data-tone="loss"` attribute you set on the tile).

```tsx
// HealthStrip.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { HealthStrip } from "./HealthStrip";
const arb = { stats: { submitted: 0, approved: 0, blocked_by: {} }, throttle: { enabled: true, current_mult: 0.5 } };
describe("HealthStrip", () => {
  it("shows stale + paused + throttle mult", () => {
    render(<HealthStrip health={{ bridge_connected: false, last_heartbeat_age_s: 120, paused: true, last_error: null }} arbiter={arb} />);
    expect(screen.getByText(/stale/i)).toBeInTheDocument();
    expect(screen.getByText(/paused/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.5/)).toBeInTheDocument();
  });
});
```

```tsx
// StatTiles.test.tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatTiles } from "./StatTiles";
const arb = { stats: { submitted: 4, approved: 3, blocked_by: { opposition: 1 } }, throttle: { enabled: false, current_mult: 1 } };
describe("StatTiles", () => {
  it("renders equity and a signed day-pnl tile with tone", () => {
    render(<StatTiles account={{ balance: 10000, equity: 9500 }} arbiter={arb} dayPnl={-500} openCount={2} />);
    expect(screen.getByText("9,500.00")).toBeInTheDocument();
    expect(screen.getByTestId("tile-daypnl").getAttribute("data-tone")).toBe("loss");
  });
});
```

- [ ] **Step 2–4:** fail → implement (pills = dot+icon+label; tiles = Card with label + big `font-mono tabnum` number; day-PnL uses `signedPnl().tone` → text color `text-profit`/`text-loss` + `ArrowUp`/`ArrowDown`/`Minus` lucide icon, and `data-tone` for the test) → pass. Match design-system §2/§6.
- [ ] **Step 5: Commit** — `feat(gui-fe): cockpit health strip + KPI stat tiles (status color+icon+label)` (+trailer).

---

### Task 5: Cockpit — EquitySparkline (Recharts) + PositionsTable

**Files:**
- Create: `frontend/src/components/EquitySparkline.tsx`, `frontend/src/components/PositionsTable.tsx`
- Test: `frontend/src/components/EquitySparkline.test.tsx`, `frontend/src/components/PositionsTable.test.tsx`

**REQUIRED before this task:** read the `dataviz` skill. The chart specs (single-series line, `--primary` stroke, no legend, recessive grid, hover crosshair+tooltip, area fill ~15%, reduced-motion, tabular figures, empty/loading states) come from it and from design-system §5. Do not add a second axis; do not color the line by profit/loss.

**Interfaces:**
- Consumes: `Position`, `format.ts`, shadcn Table, Recharts (`LineChart`/`Line`/`XAxis`/`YAxis`/`Tooltip`/`ResponsiveContainer`).
- Produces: `<EquitySparkline points={{t:number, equity:number}[]} />` (single-series line; "No data yet" empty state; `isAnimationActive={false}` to respect reduced-motion by default). `<PositionsTable positions onClose(ticket) readOnly />` — columns ticket/symbol/side(BUY=profit chip, SELL=loss chip)/lots/entry/sl/tp/pnl(signed tone)/grade/strategy; per-row Close button that calls `onClose(ticket)` and is disabled when `readOnly`.

- [ ] **Step 1: Write the failing tests** — `PositionsTable.test.tsx`: renders a BUY row with a green side chip + a signed pnl; the Close button is disabled when `readOnly`; clicking it (when not read-only) calls `onClose(ticket)`. `EquitySparkline.test.tsx`: renders the "No data yet" empty state for `points=[]`, and renders an svg path when given points (Recharts renders in jsdom; assert the container has role or a testid rather than pixel geometry).

```tsx
// PositionsTable.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PositionsTable } from "./PositionsTable";
const pos = [{ ticket: 123, symbol: "EURUSD", side: "BUY" as const, lots: 0.1, entry: 1.1, sl: 1.09, tp: 1.12, pnl: 12.5, grade: "A+", strategy: "silver_bullet" }];
describe("PositionsTable", () => {
  it("close disabled in read-only, fires callback otherwise", async () => {
    const onClose = vi.fn();
    const { rerender } = render(<PositionsTable positions={pos} onClose={onClose} readOnly />);
    expect(screen.getByRole("button", { name: /close/i })).toBeDisabled();
    rerender(<PositionsTable positions={pos} onClose={onClose} readOnly={false} />);
    await userEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalledWith(123);
  });
});
```

- [ ] **Step 2–4:** fail → implement (EquitySparkline: `ResponsiveContainer`>`LineChart` with a single `<Line stroke="hsl(var(--primary))" dot={false} strokeWidth={2} isAnimationActive={false}>`, muted `CartesianGrid`/axes, `<Tooltip>`; empty-state guard. PositionsTable: shadcn Table, `tabnum` numbers, side chip via Badge, pnl via `signedPnl`, Close button disabled on `readOnly`) → pass.
- [ ] **Step 5: Commit** — `feat(gui-fe): equity sparkline (dataviz single-series) + positions table` (+trailer).

---

### Task 6: Cockpit — Controls (confirm dialogs) + EventFeed (rule chips)

**Files:**
- Create: `frontend/src/components/Controls.tsx`, `frontend/src/components/EventFeed.tsx`
- Test: `frontend/src/components/Controls.test.tsx`, `frontend/src/components/EventFeed.test.tsx`

**Interfaces:**
- Consumes: `Api` (Task 2), `FeedEvent`, `useReadOnly`, shadcn Button/AlertDialog/Badge.
- Produces:
  - `<Controls api paused readOnly onResult />`: pause/resume, close-all, panic, cancel buttons. `closeall` and `panic` are destructive (red) and open an `AlertDialog` requiring explicit confirm; on confirm they POST `{command, confirm:true}`. All buttons disabled when `readOnly`. Surfaces `ApiError.kind==="readOnly"` by calling `onResult({readOnly:true})` (App flips ReadOnlyContext).
  - `<EventFeed events />`: append list; `IntentBlocked` rows render the `rule` as a **violet chip** (`opposition`/`ttl-dedup`/`cap`) + detail; newest-last with auto-scroll that pauses on hover and respects reduced-motion; `aria-live="polite"`.

- [ ] **Step 1: Write the failing tests** — `Controls.test.tsx`: clicking "Panic" does NOT immediately call the api (opens dialog); confirming in the dialog calls `api.postCommand({command:"panic", confirm:true})`; all buttons disabled when `readOnly`. `EventFeed.test.tsx`: an `IntentBlocked` event with `rule:"opposition"` renders a chip containing "opposition".

```tsx
// Controls.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Controls } from "./Controls";
function api() { return { postCommand: vi.fn().mockResolvedValue({ status: "ok" }) } as any; }
describe("Controls", () => {
  it("panic requires dialog confirm before calling api", async () => {
    const a = api();
    render(<Controls api={a} paused={false} readOnly={false} onResult={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /panic/i }));
    expect(a.postCommand).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(a.postCommand).toHaveBeenCalledWith({ command: "panic", confirm: true });
  });
  it("disables everything in read-only", () => {
    render(<Controls api={api()} paused={false} readOnly onResult={() => {}} />);
    screen.getAllByRole("button").forEach(b => expect(b).toBeDisabled());
  });
});
```

- [ ] **Step 2–4:** fail → implement → pass. (Non-destructive pause/resume/cancel call the api directly; destructive open AlertDialog. Catch `ApiError`; if `kind==="readOnly"` call `onResult({readOnly:true})`.)
- [ ] **Step 5: Commit** — `feat(gui-fe): controls with confirm dialogs + event feed with blocked-rule chips` (+trailer).

---

### Task 7: Strategies tab + Settings tab

**Files:**
- Create: `frontend/src/components/StrategiesTab.tsx`, `frontend/src/components/SettingsTab.tsx`
- Test: `frontend/src/components/StrategiesTab.test.tsx`, `frontend/src/components/SettingsTab.test.tsx`

**Interfaces:**
- Consumes: `Api`, `RegistryRow`, `SettingRow`, `useReadOnly`, shadcn Table/Badge/Dialog/Input/Button.
- Produces:
  - `<StrategiesTab api readOnly />`: registry table (status badges: live=info, research=warning, active/ACTIVE=profit); enable/disable buttons; **Promote** opens a Dialog requiring the operator to TYPE the strategy id — the confirm button is disabled until the typed text === the row id, then POSTs `registryAction(id, "promote", {confirm:id})` (mirrors backend typed-id gate). All mutations disabled when `readOnly`. research rows visually distinct (warning left border).
  - `<SettingsTab api readOnly />`: rows from `getSettings()` with a **source badge** (default/override) and **tier badge** (live=profit, restart=warning "restart-required"). Editing a value + Save calls `patchSetting(key, value)`; on `ApiError.kind==="validation"` (422) show the detail inline under the row; on success show applied/restart_required. Mutations disabled when `readOnly`.

- [ ] **Step 1: Write the failing tests** — `StrategiesTab.test.tsx`: the Promote dialog's confirm button is disabled until the exact id is typed, then calls `registryAction(id,"promote",{confirm:id})`. `SettingsTab.test.tsx`: a 422 from `patchSetting` renders the error detail inline; a restart-tier row shows a "restart" badge.

```tsx
// StrategiesTab.test.tsx (core assertion)
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrategiesTab } from "./StrategiesTab";
function api(rows: any[]) {
  return { getRegistry: vi.fn().mockResolvedValue(rows),
           registryAction: vi.fn().mockResolvedValue({ status: "ok" }) } as any;
}
describe("StrategiesTab promote", () => {
  it("requires typed id before confirming promote", async () => {
    const a = api([{ id: "gyroscope", version: "0.1", status: "research", state: "LOADED" }]);
    render(<StrategiesTab api={a} readOnly={false} />);
    await userEvent.click(await screen.findByRole("button", { name: /promote/i }));
    const confirm = screen.getByRole("button", { name: /confirm promote/i });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/type the strategy id/i), "gyroscope");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    expect(a.registryAction).toHaveBeenCalledWith("gyroscope", "promote", { confirm: "gyroscope" });
  });
});
```

- [ ] **Step 2–4:** fail → implement → pass. (Load rows in `useEffect`; render tables; wire dialogs; map 422 → inline error.)
- [ ] **Step 5: Build check** — `npm run build`.
- [ ] **Step 6: Commit** — `feat(gui-fe): strategies tab (typed-id promote) + settings tab (source/tier badges, inline 422)` (+trailer).

---

### Task 8: Serve the SPA from the Phase 1a server + fake-controller dev mode

**Files:**
- Modify: `src/ops/web/server.py` (ADD a static mount + an optional fake-controller factory; change NO existing route/auth/audit)
- Test: `tests/unit/test_gui_server_static.py`

**Interfaces:**
- Consumes: the existing `create_app` (Phase 1a).
- Produces:
  - In `create_app`: if `frontend/dist/` exists, mount it so `GET /` and unknown non-`/api`/`/ws` paths serve the SPA (`index.html` fallback for client-side routing); `/api/*` and `/ws` are unaffected. Use `StaticFiles(directory=..., html=True)` mounted at `/` AFTER the API routes are registered (API routes take precedence), OR a catch-all route that returns `index.html` for non-API paths. Missing `dist/` → no mount (backend still runs headless — must not raise).
  - A module-level `build_fake_controller()` in a NEW `src/ops/web/fake_controller.py` (imported lazily) providing a minimal in-memory controller (the same fake shape the Phase 1a unit tests use: health/account/positions/arbiter/registry, `_publish`, `apply_runtime_setting`, the six command methods, enable/disable) so the server can be driven with MT5 offline via `python -m src.ops.web.devserver` (a tiny NEW `devserver.py` that calls `web_server.start(build_fake_controller(), SettingsStore(...), BusBridge())` and serves the built SPA). devserver is dev-only, not imported by the live controller.

- [ ] **Step 1: Write the failing test** — `tests/unit/test_gui_server_static.py` (stdlib unittest + TestClient): when `frontend/dist/index.html` exists, `GET /` returns 200 text/html and `GET /api/state` still requires auth (401 without token); when `dist/` is absent, `create_app` still builds and `/api/state` works. Use a temp dir + monkeypatch of the dist path, or point the mount at a fixture dir.

```python
# tests/unit/test_gui_server_static.py (shape)
import unittest, os, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from src.ops.web import auth
from src.ops.web.server import create_app
from src.ops.web.settings import SettingsStore
from src.ops.web.bus_bridge import BusBridge
# ... reuse the FakeController from test_gui_server (copy the minimal shape) ...

class TestStaticMount(unittest.TestCase):
    def test_spa_served_and_api_still_guarded(self):
        os.environ["TITAN_GUI_TOKEN"] = "sekret"; auth.THROTTLE.reset()
        with tempfile.TemporaryDirectory() as d:
            dist = Path(d) / "dist"; dist.mkdir()
            (dist / "index.html").write_text("<!doctype html><title>Titan</title>")
            app = create_app(ctrl, store, bridge, dist_dir=dist)   # new optional kwarg
            client = TestClient(app)
            self.assertEqual(client.get("/").status_code, 200)
            self.assertIn("text/html", client.get("/").headers["content-type"])
            self.assertEqual(client.get("/api/state").status_code, 401)   # api still guarded
```

- [ ] **Step 2: Run to verify it fails.**
- [ ] **Step 3: Implement** — add a `dist_dir: Path | None = None` kwarg to `create_app` (default: auto-detect `<repo>/frontend/dist`); after all API routes + the WS route are registered, if the dir exists mount the SPA (catch-all GET returning `index.html` for non-`/api`/`/ws` paths, or `app.mount("/", StaticFiles(directory=dist_dir, html=True))` last). Guard so a missing dir is a no-op. Add `src/ops/web/fake_controller.py` + `src/ops/web/devserver.py`. Do NOT touch existing routes/auth/audit.
- [ ] **Step 4: Run to verify PASS**, then run the WHOLE Python GUI suite `.venv/bin/python -m unittest discover -s tests/unit -p 'test_gui_*.py'` FOREGROUND — all still green (no Phase 1a regression).
- [ ] **Step 5: Commit** — `feat(gui): serve React SPA from control server (static mount + SPA fallback) + fake-controller dev mode` (+trailer). Stage `src/ops/web/server.py`, `src/ops/web/fake_controller.py`, `src/ops/web/devserver.py`, `tests/unit/test_gui_server_static.py` only.

---

### Task 9: Build + wire App + live verification (+ design-review)

**Files:**
- Modify: `frontend/src/App.tsx` (wire Tasks 4–7 panels into the tabs, pass `api`/`snapshot`/`events`, flip ReadOnlyContext on a 403), any small glue.
- Test: `frontend/src/App.test.tsx` (renders Cockpit with a seeded snapshot via a mocked hook).

- [ ] **Step 1: Wire App** — Cockpit tab = HealthStrip + StatTiles + EquitySparkline + PositionsTable + Controls + EventFeed; Strategies tab = StrategiesTab; Settings tab = SettingsTab. Build the `api` with `createApi(() => token)`. On any `ApiError.kind==="readOnly"` from a mutation, call `setReadOnly(true)`. Derive `dayPnl`/equity points from the snapshot (equity points may be a short in-memory rolling buffer of `account.equity` sampled on snapshot change — a simple `useState` array capped at ~120).
- [ ] **Step 2: App test** — mock `useLiveState` to return a seeded snapshot; assert the Cockpit renders positions + health. Run `npm test` (whole suite) FOREGROUND — all green.
- [ ] **Step 3: Build** — `cd frontend && npm run build` → `frontend/dist/` populated (FOREGROUND).
- [ ] **Step 4: Live drive (MT5 offline)** — start the dev server against the fake controller and the built SPA:
  `TITAN_GUI_TOKEN=devtoken .venv/bin/python -m src.ops.web.devserver` (serves the built `frontend/dist` on :8770). Then drive the real UI:
  - Use the `/run` or `browse` skill (headless browser) to load `http://127.0.0.1:8770`, enter the token, and verify: token gate works; Cockpit shows the fake positions + health strip; a command button opens its confirm dialog; the Strategies promote dialog requires the typed id; the Settings tab shows source/tier badges and a 422 renders inline; toggling `TITAN_GUI_READONLY=1` greys the mutating controls. Capture screenshots.
  - If no browser is available in this environment, record this step as **deferred** (note it in the report + ledger) and rely on the Vitest component tests + the Python static-mount test as the automated proof.
- [ ] **Step 5: `design-review` (gstack)** — if a browser is available, run the `design-review` skill against the running UI for a visual QA pass (spacing, hierarchy, contrast, AI-slop, slow interactions) and fix what it finds. If no browser, record as **deferred**.
- [ ] **Step 6: Commit** — `feat(gui-fe): wire cockpit/strategies/settings into App + build; live-drive vs fake controller` (+trailer). Commit the built `frontend/dist`? NO — `dist/` is gitignored (built artifact); the build is reproduced by `npm run build`. Stage `frontend/src/**` changes only.
- [ ] **Step 7: Full verification tally** (no commit): `cd frontend && npm test` (all component/hook tests green) + `npm run build` (clean) + the Python suite `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'` (60 GUI + static-mount + parity green; the pre-existing Plan-06 research-ordering flake is not this feature's). Record results in the ledger.

---

## Self-Review

**Spec coverage (backend spec §Frontend + design-system doc):** health strip w/ throttle indicator → T4; positions+PnL → T5; event feed w/ blocked-rule chips → T6; controls w/ confirm dialogs → T6; Strategies tab w/ typed-id promote → T7; Settings tab w/ source/tier badges + inline 422 → T7; read-only greys mutations → T3 (context) + enforced in T5/T6/T7; WS hook first-frame auth + reconnect + GET /api/state fallback → T2; equity/PnL sparkline + stat tiles (dataviz) → T4/T5; served from frontend/dist same-origin → T8; Research/Journal scaffolded empty → T3. Design skills: ui-ux-pro-max → design-system doc cited throughout; dataviz → gated before T5; design-review → T9 (or deferred).
**Placeholder scan:** load-bearing pieces (tokens, types, api client, WS hook, token gate, read-only context, controls confirm logic, promote typed-id logic, settings 422 mapping, server static mount) have complete code; shadcn primitives use canonical shadcn source (named explicitly, not invented); panel JSX for T4–T7 is specified by exact props/behavior + tests rather than full JSX to keep the plan readable — implementers build to the tests + design-system tokens. This is intentional: the tests pin behavior, the design-system doc pins appearance.
**Type consistency:** `Snapshot`/`Position`/`FeedEvent`/`SettingRow`/`RegistryRow` (T1) are consumed unchanged by T2 (api return types) and T4–T7 (props); `Api` = `ReturnType<typeof createApi>` (T2) is the prop type in T6/T7; `useReadOnly()` (T3) used in T5/T6/T7; `createApi(getToken)` signature stable across T2/T9.
