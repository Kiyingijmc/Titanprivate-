# Maximizable Panels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Equity and Economic Calendar panels expand to 75% of the viewport via a maximize button, with the equity chart filling the larger box instead of staying a 140px strip.

**Architecture:** `OverviewPage` owns one state value (`maximized: "equity" | "news" | null`). Two new presentational components — `MaximizeButton` and `MaximizedDialog` — are shared by both panels. The equity panel's body is extracted into a reusable `EquityPanelBody` rendered either collapsed (in the `Panel`) or filling (in the dialog), never both at once.

**Tech Stack:** React 18 + TypeScript, Vite, Tailwind, shadcn/ui over `@radix-ui/react-dialog` (already installed), Recharts, Vitest + Testing Library.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-03-maximizable-panels-design.md`. Read it before starting.
- Working directory for every command is `frontend/`. Node is at `/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin` — put it on `PATH` first: `export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"`.
- Run a single test file with `npx vitest run <path>`. Run everything with `npm test`. Type-check/build with `npm run build` (`tsc -b && vite build`).
- **Single-instance invariant (spec §6):** while a panel is maximized, its collapsed body must NOT render `equity-sparkline`, `range-selector`, or `news-panel`. Testing Library's `getByTestId`/`findByTestId` throw on multiple matches, so a duplicate breaks existing tests in `OverviewPage.test.tsx` that are unrelated to this feature.
- **Do NOT assert on Tailwind class strings for sizing (`w-[75vw]`), and do NOT assert on animation easing.** jsdom computes no layout, so such tests pass whether or not the behaviour is correct. Ask of every guard: *what mutation makes this red?*
- Sizing target: `h-[85vh] w-[95vw] md:h-[75vh] md:w-[75vw]`, with `max-w-none` to defeat `DialogContent`'s stock `max-w-lg`.
- The bot may be running from this working tree. These are frontend-only changes; do not restart anything.
- Commit after every task.

---

### Task 1: Maximize primitives (button + dialog)

**Files:**
- Create: `frontend/src/components/shell/MaximizeButton.tsx`
- Create: `frontend/src/components/shell/MaximizedDialog.tsx`
- Test: `frontend/src/components/shell/MaximizedDialog.test.tsx`

**Interfaces:**
- Consumes: `@/components/ui/button` (`Button`, variants `ghost`/`sm`), `@/components/ui/dialog` (`Dialog`, `DialogContent`, `DialogTitle`), `@/lib/utils` (`cn`, which uses `twMerge`).
- Produces:
  - `MaximizeButton({ title: string; onClick: () => void }): JSX.Element` — renders a button with `aria-label={`Maximize ${title}`}`. **No `data-testid`** on purpose: two of these coexist on the Overview page (Equity and Calendar), so a shared testid would itself violate the single-match rule. Query by role + accessible name.
  - `MaximizedDialog({ open, onOpenChange, title, children, className? })` — `open: boolean`, `onOpenChange: (open: boolean) => void`, `title: string`, `children: React.ReactNode`, `className?: string`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/shell/MaximizedDialog.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MaximizedDialog } from "./MaximizedDialog";
import { MaximizeButton } from "./MaximizeButton";

describe("MaximizedDialog", () => {
  it("renders nothing while closed", () => {
    render(
      <MaximizedDialog open={false} onOpenChange={() => {}} title="Equity">
        <p>chart goes here</p>
      </MaximizedDialog>
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("chart goes here")).not.toBeInTheDocument();
  });

  it("exposes an accessible name from its title and renders children when open", () => {
    render(
      <MaximizedDialog open onOpenChange={() => {}} title="Equity">
        <p>chart goes here</p>
      </MaximizedDialog>
    );
    expect(screen.getByRole("dialog", { name: "Equity" })).toBeInTheDocument();
    expect(screen.getByText("chart goes here")).toBeInTheDocument();
  });

  it("asks to close on Escape", async () => {
    const onOpenChange = vi.fn();
    render(
      <MaximizedDialog open onOpenChange={onOpenChange} title="Equity">
        <p>chart goes here</p>
      </MaximizedDialog>
    );
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("MaximizeButton", () => {
  it("is named for the panel it maximizes and calls back on click", async () => {
    const onClick = vi.fn();
    render(<MaximizeButton title="Equity" onClick={onClick} />);
    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"
cd frontend && npx vitest run src/components/shell/MaximizedDialog.test.tsx
```

Expected: FAIL — cannot resolve `./MaximizedDialog` / `./MaximizeButton`.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/shell/MaximizeButton.tsx`:

```tsx
import { Maximize2 } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Opens a panel's maximized (75%) view.
 *
 * Presentational only — the parent owns the open/closed state, which is what
 * makes "only one panel maximized at a time" structural rather than a rule to
 * enforce. Carries NO data-testid: two of these coexist on the Overview page,
 * and a shared testid would break the single-match queries the suite relies on.
 */
export function MaximizeButton({ title, onClick }: { title: string; onClick: () => void }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={onClick}
      aria-label={`Maximize ${title}`}
    >
      <Maximize2 className="size-4" aria-hidden />
    </Button>
  );
}
```

Create `frontend/src/components/shell/MaximizedDialog.tsx`:

```tsx
import * as React from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/**
 * A panel's maximized view: 75% of the viewport from `md` up, near-full below
 * it (75% of a phone screen is unusable).
 *
 * `max-w-none` is REQUIRED. The stock DialogContent carries `max-w-lg`, which
 * silently caps the dialog at 32rem no matter which width class is applied.
 * `flex` likewise overrides DialogContent's stock `grid` — `cn` runs
 * tailwind-merge, so the later display utility wins.
 *
 * The body is `flex-1 min-h-0` so children can FILL it. Without `min-h-0` a
 * flex child refuses to shrink below its content height, and the chart
 * overflows the dialog instead of fitting inside it.
 *
 * Escape, click-outside, focus trap, focus restoration and body scroll lock all
 * come from Radix. Open/close motion comes from the `[data-titan-dialog]`
 * keyframes already in index.css, so reduced-motion is handled globally.
 */
export function MaximizedDialog({
  open,
  onOpenChange,
  title,
  children,
  className,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "flex max-w-none flex-col gap-3",
          "h-[85vh] w-[95vw] md:h-[75vh] md:w-[75vw]",
          className
        )}
      >
        <DialogTitle>{title}</DialogTitle>
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/shell/MaximizedDialog.test.tsx
```

Expected: PASS — 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/shell/MaximizeButton.tsx \
        frontend/src/components/shell/MaximizedDialog.tsx \
        frontend/src/components/shell/MaximizedDialog.test.tsx
git commit -m "feat(gui): maximize button + 75% dialog primitives"
```

---

### Task 2: `Panel` accepts `onMaximize`

**Files:**
- Modify: `frontend/src/components/shell/Panel.tsx:10-19` (props), `:57-64` (header)
- Test: `frontend/src/components/shell/Panel.test.tsx` (append)

**Interfaces:**
- Consumes: `MaximizeButton` from Task 1.
- Produces: `PanelProps` gains `onMaximize?: () => void`. When present, `Panel` renders a `MaximizeButton` after any `actions`. Panels that omit it are visually unchanged.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/shell/Panel.test.tsx`:

```tsx
describe("Panel maximize affordance", () => {
  it("renders no maximize control unless onMaximize is provided", () => {
    render(<Panel status="populated" title="Equity">body</Panel>);
    expect(screen.queryByRole("button", { name: /maximize/i })).not.toBeInTheDocument();
  });

  it("renders a maximize control named for the panel and calls back", async () => {
    const onMaximize = vi.fn();
    render(
      <Panel status="populated" title="Equity" onMaximize={onMaximize}>
        body
      </Panel>
    );
    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));
    expect(onMaximize).toHaveBeenCalledTimes(1);
  });
});
```

Make sure the file's imports include `vi` from `vitest` and `userEvent` from `@testing-library/user-event`; add them if absent:

```tsx
import { describe, it, expect, vi } from "vitest";
import userEvent from "@testing-library/user-event";
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/shell/Panel.test.tsx
```

Expected: FAIL — the second test finds no button named "Maximize Equity".

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/components/shell/Panel.tsx`, add the import:

```tsx
import { MaximizeButton } from "./MaximizeButton";
```

Add to `PanelProps`:

```tsx
  /** When provided, the header shows a maximize control that calls this. */
  onMaximize?: () => void;
```

Add `onMaximize` to the destructured parameters, then replace the header block:

```tsx
      {(title || actions || onMaximize) && (
        <CardHeader className="flex-row items-center justify-between space-y-0">
          {title && <CardTitle className="text-foreground">{title}</CardTitle>}
          {(actions || onMaximize) && (
            <div className="flex items-center gap-2">
              {actions}
              {onMaximize && (
                // `title` is a ReactNode; only a string can name the control for
                // assistive tech, so fall back when a caller passes an element.
                <MaximizeButton
                  title={typeof title === "string" ? title : "panel"}
                  onClick={onMaximize}
                />
              )}
            </div>
          )}
        </CardHeader>
      )}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/shell/Panel.test.tsx
```

Expected: PASS — including the pre-existing Panel tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/shell/Panel.tsx frontend/src/components/shell/Panel.test.tsx
git commit -m "feat(gui): Panel renders an optional maximize control"
```

---

### Task 3: `EquitySparkline` becomes size-driven

**Files:**
- Modify: `frontend/src/components/EquitySparkline.tsx:50-63` (props + dispatch), `:154-162` (`SeriesChart` props)
- Test: `frontend/src/components/EquitySparkline.test.tsx` (append)

**Interfaces:**
- Produces: `EquitySparkline`'s `height` prop widens from `number` to `number | string`, default still `140`. Passing `"100%"` makes it fill a sized parent. `SeriesChart`'s internal `height` widens identically.

Why this is needed: without it, a maximized chart renders as a 140px strip inside a 75vh box.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/EquitySparkline.test.tsx`:

```tsx
describe("EquitySparkline sizing", () => {
  const points = [
    { t: 0, equity: 10000 },
    { t: 1, equity: 10050 },
  ];

  it("defaults to the compact 140px strip", () => {
    render(<EquitySparkline points={points} />);
    expect(screen.getByTestId("equity-sparkline")).toHaveStyle({ height: "140px" });
  });

  it("accepts a percentage height so it can fill a maximized panel", () => {
    render(<EquitySparkline points={points} height="100%" />);
    expect(screen.getByTestId("equity-sparkline")).toHaveStyle({ height: "100%" });
  });
});
```

This is not a tautology: dropping the `height` prop from the wrapper's `style`, or narrowing the type back to `number`, makes it red.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx
```

Expected: FAIL — TypeScript rejects `height="100%"` (type `string` not assignable to `number`).

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/components/EquitySparkline.tsx`, change the exported signature:

```tsx
export function EquitySparkline({
  points,
  series,
  width = "100%",
  height = 140,
}: {
  points: BufferPoint[];
  series?: EquitySeries;
  width?: number | string;
  height?: number | string;
}) {
```

And `SeriesChart`'s signature:

```tsx
function SeriesChart({
  series,
  width,
  height,
}: {
  series: EquitySeries;
  width: number | string;
  height: number | string;
}) {
```

No other change: every existing use is `style={{ width: "100%", height }}` or `<ResponsiveContainer height={height}>`, both of which already accept strings.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/EquitySparkline.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EquitySparkline.tsx frontend/src/components/EquitySparkline.test.tsx
git commit -m "feat(gui): EquitySparkline accepts a string height so it can fill"
```

---

### Task 4: Extract `EquityPanelBody` and wire the equity maximize

**Files:**
- Create: `frontend/src/components/EquityPanelBody.tsx`
- Modify: `frontend/src/sections/OverviewPage.tsx` (imports, new state, equity `Panel` block at `:277-314`)
- Test: `frontend/src/sections/OverviewPage.test.tsx` (append)

**Interfaces:**
- Consumes: `MaximizedDialog` (Task 1), `Panel.onMaximize` (Task 2), `EquitySparkline` string height (Task 3).
- Produces: `EquityPanelBody(props: EquityPanelBodyProps)` where

```ts
interface EquityPanelBodyProps {
  points: BufferPoint[];
  series?: EquitySeries;
  range: string;
  onRangeChange: (range: string) => void;
  firstSampleTs: number | null;
  error: ApiError | null;
  loading: boolean;
  hasFetchedData: boolean;   // equity.data !== null — drives the error wording and the dim
  now: number;               // SERVER-clock epoch SECONDS, from serverNow()
  fill?: boolean;            // fill the parent instead of the 140px strip
}
```

`hasFetchedData` is separate from `series` on purpose: the existing wording keys off `equity.data` ("could not be **refreshed**" vs "could not be **loaded**"), and `series` here is the live-tailed derivative. Collapsing the two would change an operator-facing message that a prior review specifically asked for.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/sections/OverviewPage.test.tsx`:

```tsx
describe("equity maximize", () => {
  it("keeps exactly one chart and one range selector when maximized", async () => {
    renderOverview();

    await screen.findByTestId("range-selector");
    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));

    expect(await screen.findByRole("dialog", { name: "Equity" })).toBeInTheDocument();
    // The collapsed body must go quiet: duplicates break single-match queries
    // used all over this file, and would announce twice to assistive tech.
    expect(screen.getAllByTestId("equity-sparkline")).toHaveLength(1);
    expect(screen.getAllByTestId("range-selector")).toHaveLength(1);
  });

  it("still switches range from inside the maximized view", async () => {
    const api = fakeApi();
    render(
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider
            value={{ snapshot: makeSnapshot(), events, connectionStatus: { status: "live", stale: false }, api }}
          >
            <OverviewPage />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );

    await screen.findByTestId("range-selector");
    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));

    const selector = await screen.findByTestId("range-selector");
    const fourHour = within(selector).getByRole("radio", { name: "4h" });
    await waitFor(() => expect(fourHour).not.toBeDisabled());
    await userEvent.click(fourHour);

    await waitFor(() => expect(api.getEquity).toHaveBeenCalledWith("4h"));
  });

  it("surfaces a fetch failure inside the maximized view, not only in the card", async () => {
    const api = fakeApi();
    (api.getEquity as any).mockRejectedValue({ status: 503, kind: "error", detail: "bridge down" });
    render(
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider
            value={{ snapshot: makeSnapshot(), events, connectionStatus: { status: "live", stale: false }, api }}
          >
            <OverviewPage />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );

    await screen.findByTestId("equity-fetch-error");
    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));

    const dialog = await screen.findByRole("dialog", { name: "Equity" });
    expect(within(dialog).getByTestId("equity-fetch-error")).toBeInTheDocument();
    expect(screen.getAllByTestId("equity-fetch-error")).toHaveLength(1);
  });

  it("closes on Escape and returns focus to the maximize button", async () => {
    renderOverview();
    await screen.findByTestId("range-selector");

    const button = screen.getByRole("button", { name: "Maximize Equity" });
    await userEvent.click(button);
    await screen.findByRole("dialog", { name: "Equity" });

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(button).toHaveFocus());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/sections/OverviewPage.test.tsx
```

Expected: FAIL — no button named "Maximize Equity".

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/EquityPanelBody.tsx`:

```tsx
import { AlertTriangle } from "lucide-react";
import { EquitySparkline, type BufferPoint } from "@/components/EquitySparkline";
import { RangeSelector } from "@/components/RangeSelector";
import { cn } from "@/lib/utils";
import type { ApiError } from "@/lib/api";
import type { EquitySeries } from "@/lib/types";

export interface EquityPanelBodyProps {
  points: BufferPoint[];
  series?: EquitySeries;
  range: string;
  onRangeChange: (range: string) => void;
  firstSampleTs: number | null;
  error: ApiError | null;
  loading: boolean;
  /** `equity.data !== null`. Drives the error wording and the dim, exactly as
   *  before the extraction — NOT the same thing as `series`, which is the
   *  live-tailed derivative. */
  hasFetchedData: boolean;
  /** SERVER-clock epoch SECONDS (serverNow()), never a raw browser clock. */
  now: number;
  /** Fill the parent instead of rendering the 140px strip. */
  fill?: boolean;
}

/**
 * The Equity panel's body: range selector, fetch-error badge, and the chart.
 *
 * Extracted so the collapsed card and the maximized dialog render the SAME
 * component and only one of them is ever mounted (spec §6). The error badge
 * travels with it deliberately: a dead /api/equity must stay visible at 75%,
 * not just in the small card.
 */
export function EquityPanelBody({
  points,
  series,
  range,
  onRangeChange,
  firstSampleTs,
  error,
  loading,
  hasFetchedData,
  now,
  fill = false,
}: EquityPanelBodyProps) {
  return (
    <div className={cn("flex flex-col", fill && "min-h-0 flex-1")}>
      <div className="mb-3 flex justify-end">
        <RangeSelector
          value={range}
          onChange={onRangeChange}
          firstSampleTs={firstSampleTs}
          loadError={error !== null}
          now={now}
        />
      </div>

      {error && (
        <div
          data-testid="equity-fetch-error"
          role="status"
          className="mb-2 flex items-start gap-1.5 rounded-md border border-warning/40 bg-warning/10 px-2 py-1 text-xs text-warning"
        >
          <AlertTriangle className="mt-px size-3 shrink-0" />
          <span>
            {hasFetchedData
              ? "Equity history could not be refreshed — the curve below is not current."
              : "Equity history could not be loaded."}{" "}
            {error.detail}
          </span>
        </div>
      )}

      <div
        className={cn(
          "transition-opacity duration-[var(--motion-fast)]",
          fill && "min-h-0 flex-1",
          // Dim on a failed refresh too, not only while loading: the `finally`
          // in useEquitySeries clears `loading` on the failure path, so a dim
          // keyed on loading alone snaps back to full confidence the instant
          // the fetch dies.
          (loading || error !== null) && hasFetchedData && "opacity-60",
        )}
      >
        <EquitySparkline
          points={points}
          series={series}
          height={fill ? "100%" : undefined}
        />
      </div>
    </div>
  );
}
```

In `frontend/src/sections/OverviewPage.tsx`, add imports:

```tsx
import { EquityPanelBody } from "@/components/EquityPanelBody";
import { MaximizedDialog } from "@/components/shell/MaximizedDialog";
```

`AlertTriangle`, `RangeSelector` and `cn` may become unused there once the body moves out — remove any import the build reports as unused (`npm run build` fails on unused locals if `noUnusedLocals` is on; if it isn't, remove them anyway). Keep `enabledRangeNames`/`lookupRangeSeconds` — the `[`/`]` shortcut still uses them.

Add the state next to the other `useState` calls:

```tsx
  // ONE value, not a boolean per panel: this makes "only one panel maximized at
  // a time" structural instead of a rule to enforce.
  const [maximized, setMaximized] = useState<null | "equity" | "news">(null);
```

Build the shared props once, above the `return`:

```tsx
  const equityBodyProps = {
    points: equityPoints,
    series: equitySeriesForChart ?? undefined,
    range,
    onRangeChange: setRange,
    firstSampleTs,
    error: equity.error,
    loading: equity.loading,
    hasFetchedData: equity.data !== null,
    now: serverNow(),
  };
```

Replace the whole equity `Panel` block (currently `:277-314`) with:

```tsx
        <Panel status={equityStatus} title="Equity" onMaximize={() => setMaximized("equity")}>
          {/* Reserve the collapsed height so closing the dialog doesn't jump.
              Range row (~36px) + its mb-3 (12px) + the 140px chart. */}
          <div className="min-h-[188px]">
            {maximized === "equity" ? null : <EquityPanelBody {...equityBodyProps} />}
          </div>
        </Panel>
```

Add the dialog just before the closing `</div>` of the page's outermost `<div className="grid gap-4">`:

```tsx
      <MaximizedDialog
        open={maximized === "equity"}
        onOpenChange={(open) => setMaximized(open ? "equity" : null)}
        title="Equity"
      >
        <EquityPanelBody {...equityBodyProps} fill />
      </MaximizedDialog>
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/sections/OverviewPage.test.tsx
```

Expected: PASS — the four new tests plus every pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/EquityPanelBody.tsx \
        frontend/src/sections/OverviewPage.tsx \
        frontend/src/sections/OverviewPage.test.tsx
git commit -m "feat(gui): maximize the Equity panel to 75%"
```

---

### Task 5: Wire the Economic Calendar maximize

**Files:**
- Modify: `frontend/src/components/market/NewsPanel.tsx:8` (props), `:151-169` (`Header`)
- Modify: `frontend/src/sections/OverviewPage.tsx` (strip cell + second dialog)
- Test: `frontend/src/components/market/NewsPanel.test.tsx` (append), `frontend/src/sections/OverviewPage.test.tsx` (append)

**Interfaces:**
- Consumes: `MaximizeButton` (Task 1), `MaximizedDialog` (Task 1), the `maximized` state (Task 4).
- Produces: `NewsPanel` gains `onMaximize?: () => void`, rendered in its existing `Header` beside the status badge. `Header` gains a matching optional `onMaximize`.

Note (spec §2): this shows the **same content in a bigger box**. Week-ahead, impact levels and filters are sub-project C. That is expected, not a defect.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/market/NewsPanel.test.tsx`:

```tsx
describe("NewsPanel maximize affordance", () => {
  it("renders no maximize control unless onMaximize is provided", () => {
    render(<NewsPanel data={OK} />);
    expect(screen.queryByRole("button", { name: /maximize/i })).not.toBeInTheDocument();
  });

  it("renders a maximize control and calls back", async () => {
    const onMaximize = vi.fn();
    render(<NewsPanel data={OK} onMaximize={onMaximize} />);
    await userEvent.click(screen.getByRole("button", { name: "Maximize Economic Calendar" }));
    expect(onMaximize).toHaveBeenCalledTimes(1);
  });

  it("offers maximize even in the unavailable state", async () => {
    const onMaximize = vi.fn();
    render(<NewsPanel onMaximize={onMaximize} />);
    await userEvent.click(screen.getByRole("button", { name: "Maximize Economic Calendar" }));
    expect(onMaximize).toHaveBeenCalledTimes(1);
  });
});
```

Add `vi` to the vitest import and `import userEvent from "@testing-library/user-event";` at the top of that file if absent.

Append to `frontend/src/sections/OverviewPage.test.tsx`:

```tsx
describe("news maximize", () => {
  it("keeps exactly one news panel when maximized", async () => {
    renderOverview({ snapshot: makeSnapshot({ news: { status: "ok", cache_age_min: 5, next: null, blocked_symbols: {} } }) });

    await userEvent.click(screen.getByRole("button", { name: "Maximize Economic Calendar" }));

    expect(await screen.findByRole("dialog", { name: "Economic Calendar" })).toBeInTheDocument();
    expect(screen.getAllByTestId("news-panel")).toHaveLength(1);
  });

  // Only one dialog can exist because `maximized` is a single value, so this
  // guards the structure rather than an interaction: with a modal open, the
  // other panel's button is not reachable to click in the first place.
  it("never renders more than one dialog", async () => {
    renderOverview({ snapshot: makeSnapshot({ news: { status: "ok", cache_age_min: 5, next: null, blocked_symbols: {} } }) });
    await screen.findByTestId("range-selector");

    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));
    expect(await screen.findByRole("dialog", { name: "Equity" })).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/market/NewsPanel.test.tsx src/sections/OverviewPage.test.tsx
```

Expected: FAIL — no button named "Maximize Economic Calendar".

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/components/market/NewsPanel.tsx`, add the import:

```tsx
import { MaximizeButton } from "@/components/shell/MaximizeButton";
```

Change the component signature and both `Header` usages:

```tsx
export function NewsPanel({
  data,
  className,
  onMaximize,
}: {
  data?: NewsBlock;
  className?: string;
  onMaximize?: () => void;
}) {
```

The unavailable-state branch becomes `<Header status={data?.status} onMaximize={onMaximize} />`, and the populated branch `<Header status={data.status} cacheAgeMin={data.cache_age_min} onMaximize={onMaximize} />`.

Replace `Header` with:

```tsx
function Header({
  status,
  cacheAgeMin,
  onMaximize,
}: {
  status?: NewsBlock["status"];
  cacheAgeMin?: number | null;
  onMaximize?: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <h3 className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        <Calendar className="size-3.5" aria-hidden />
        Economic Calendar
      </h3>
      <div className="flex items-center gap-1.5">
        {status === "degraded" ? (
          <span className="rounded-full border border-warning/40 bg-warning/15 px-2 py-0.5 text-xs font-medium text-warning">
            degraded
          </span>
        ) : status === "ok" && cacheAgeMin != null ? (
          <span className="rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs font-medium text-muted-foreground">
            {cacheAgeMin}m old
          </span>
        ) : null}
        {onMaximize && <MaximizeButton title="Economic Calendar" onClick={onMaximize} />}
      </div>
    </div>
  );
}
```

In `frontend/src/sections/OverviewPage.tsx`, replace the `NewsPanel` cell in the market-context strip:

```tsx
        {maximized === "news" ? (
          // Placeholder keeps the grid cell occupied; the live instance lives in
          // the dialog (spec §6). No data-testid — that must stay single-match.
          <div className="rounded-lg border border-border bg-surface-1 p-4" aria-hidden />
        ) : (
          <NewsPanel data={snapshot?.news} onMaximize={() => setMaximized("news")} />
        )}
```

And add the second dialog beside the equity one:

```tsx
      <MaximizedDialog
        open={maximized === "news"}
        onOpenChange={(open) => setMaximized(open ? "news" : null)}
        title="Economic Calendar"
      >
        <div className="min-h-0 flex-1 overflow-y-auto">
          <NewsPanel data={snapshot?.news} />
        </div>
      </MaximizedDialog>
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/market/NewsPanel.test.tsx src/sections/OverviewPage.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Full suite, type-check, and commit**

```bash
cd frontend && npm test && npm run build
```

Expected: all test files pass and the build completes. If `App.test.tsx > gates on token`, `Controls`, or `StrategiesTab` fail with "Test timed out in 5000ms", check `uptime` — those three are load-sensitive (that one takes ~3900ms of a 5000ms budget on an idle box). Re-run them in isolation before believing the failure:

```bash
npx vitest run src/App.test.tsx src/components/Controls.test.tsx src/components/StrategiesTab.test.tsx
```

```bash
git add frontend/src/components/market/NewsPanel.tsx \
        frontend/src/components/market/NewsPanel.test.tsx \
        frontend/src/sections/OverviewPage.tsx \
        frontend/src/sections/OverviewPage.test.tsx
git commit -m "feat(gui): maximize the Economic Calendar panel to 75%"
```

---

## Manual verification (not unit-testable)

jsdom computes no layout, so the 75% sizing and the open/close motion cannot be asserted in Vitest. After Task 5, verify in a real browser:

1. `npm run build` from `frontend/`, then hard-refresh the GUI at `http://127.0.0.1:8770` (Ctrl+Shift+R — asset names are content-hashed and the stale path falls through to `index.html`).
2. Maximize Equity: the dialog occupies roughly three-quarters of the window, and the chart **fills** it rather than sitting as a strip at the top.
3. Switch ranges inside the dialog; the curve reloads.
4. Escape closes it; the page behind does not jump.
5. Narrow the window below `md`: the dialog goes near-full-screen instead of 75%.
6. Maximize the Economic Calendar: same box, same content as the card (expected until sub-project C).
