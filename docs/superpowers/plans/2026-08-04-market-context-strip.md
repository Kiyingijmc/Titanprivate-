# Market-Context Strip Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the market-context strip truncating every card, by stacking the session chip's content vertically, sizing the strip's grid by content instead of guessed fractions, and adding the missing overflow primitives.

**Architecture:** Four small, independent changes plus a committed measurement script. `SessionChip` stops competing horizontally (name and clock in one `justify-between` row) and stacks instead, so each row needs its widest single element rather than the sum of two. The strip's grid track list becomes content-driven. The other three cards get `min-w-0`/`truncate`/`whitespace-nowrap`/`title`. A Node script re-runs the exact `scrollWidth` vs `clientWidth` measurement that found the bug.

**Tech Stack:** React 18, TypeScript, Tailwind 3, Vitest + Testing Library, Node (for the measurement script, driven through the existing `browse` daemon).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-04-market-context-strip-design.md`. Read it before starting.
- Working directory for every command is `frontend/`. Put Node on PATH first: `export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"`.
- Run one test file with `npx vitest run <path>`; everything with `npm test`; type-check `npx tsc -b`; build `npm run build`.
- `node_modules` already exists. Do NOT run `npm install` / `npm ci`.
- tsconfig has `noUnusedLocals: true` / `noUnusedParameters: true` — unused imports are build errors.
- **No test may assert a width, a pixel value, that text fits, or a Tailwind class string.** jsdom computes no layout, so all four pass regardless of the behaviour. This repo shipped four such tests across A2 and B1. Guards are structural (rendered elements and attributes); fit is proven only by the browser pass.
- **Every test supplies an explicit `now`.** `sessionStates()` runs off the wall clock, so a test without a pinned `now` passes at 03:00 and fails at 14:00 and never exercises the strings that break the layout. `MarketSessions` already accepts a `now?: Date` prop for exactly this.
- **Derive the longest session name from `SESSIONS`** (exported at `src/lib/sessions.ts:13`) rather than hard-coding `"New York"`, so adding a fifth session extends the guard instead of leaving it stale.
- Frontend only. No Python, no backend, no bot restart. Never bind ports 8770 / 32768 / 32769 — a live trading bot owns them.
- The live bot serves `frontend/dist` from the main checkout. Work in the worktree you are given; do not rebuild `dist` in the main checkout and do not restart anything.
- Commit after every task.

---

## File map

| File | Responsibility | Task |
|---|---|---|
| `src/components/market/MarketSessions.tsx` | `SessionChip` internals + the chip grid | 1, 2 |
| `src/components/market/MarketSessions.test.tsx` | chip structure guards | 1, 2 |
| `src/sections/OverviewPage.tsx` | the strip's grid track list | 3 |
| `src/components/market/LocalityClock.tsx` | date/timezone overflow guards | 4 |
| `src/components/market/LocalityClock.test.tsx` | structure guards | 4 |
| `src/components/market/DollarBias.tsx` | bias label guard | 4 |
| `src/components/market/NewsPanel.tsx` | panel title guard | 4 |
| `scripts/measure-strip-overflow.mjs` | **new** — the repeatable browser measurement | 5 |

---

### Task 1: Stack the session chip

**Files:**
- Modify: `frontend/src/components/market/MarketSessions.tsx:184-228` (`SessionChip`)
- Test: `frontend/src/components/market/MarketSessions.test.tsx` (append)

**Interfaces:**
- Consumes: `SessionState` from `@/lib/sessions` (already imported in the component file), which carries `id`, `label`, `localClock`, `open`, `statusLabel`.
- Produces: `SessionChip` renders three optional rows. Task 2 relies on the chip's minimum content width being one element wide (~62px), not two (~118px).

This is the core fix. The chip currently puts the name and the clock in a `justify-between` row — two items competing for 53px of available width — which is why every clock clips mid-digit.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/market/MarketSessions.test.tsx`:

```tsx
describe("SessionChip layout (spec §3)", () => {
  // 2026-08-04 08:30 UTC. VERIFIED against Intl, not reasoned about:
  //   sydney  local 18:30, window 7-16  => closed
  //   tokyo   local 17:30, window 9-18  => OPEN
  //   london  local 09:30, window 8-17  => OPEN
  //   newyork local 04:30, window 8-17  => closed
  // Pinning `now` is mandatory: sessionStates() reads the wall clock, so an
  // unpinned test passes or fails depending on the hour it runs, and never
  // exercises the strings that actually break the layout.
  const NOW = new Date("2026-08-04T08:30:00Z");

  it("gives an OPEN session a clock row", () => {
    render(<MarketSessions now={NOW} />);
    const chip = screen.getByTestId("session-chip-london");
    expect(chip.querySelector('[data-testid="session-clock"]')).not.toBeNull();
  });

  it("gives a CLOSED session no clock row", () => {
    // The mutation this kills: rendering the clock unconditionally, which is
    // exactly what the pre-fix component did and what caused the overflow.
    render(<MarketSessions now={NOW} />);
    const chip = screen.getByTestId("session-chip-sydney");
    expect(chip.querySelector('[data-testid="session-clock"]')).toBeNull();
  });

  it("renders both states at this fixture — so neither assertion above is vacuous", () => {
    render(<MarketSessions now={NOW} />);
    expect(screen.getByTestId("session-chip-london").querySelector('[data-testid="session-clock"]')).not.toBeNull();
    expect(screen.getByTestId("session-chip-sydney").querySelector('[data-testid="session-clock"]')).toBeNull();
  });

  it("shows the closes-in countdown on an open chip, not a bare 'Open'", () => {
    // sessions.ts:127 already computes `Open · closes in Xh Ym` and the chip
    // threw it away for a hardcoded "Open". This surfaces it.
    render(<MarketSessions now={NOW} />);
    const status = screen.getByTestId("session-chip-london").querySelector('[data-testid="session-status"]')!;
    expect(status.textContent).toMatch(/Open/);
    expect(status.textContent).toMatch(/\d+m/);   // a countdown is present
  });

  it("shows the opens-in countdown on a closed chip", () => {
    render(<MarketSessions now={NOW} />);
    const status = screen.getByTestId("session-chip-sydney").querySelector('[data-testid="session-status"]')!;
    expect(status.textContent).toMatch(/\d+m/);
    expect(status.textContent).not.toMatch(/^Open\b/);
  });

  it("exercises a MAXIMUM-WIDTH countdown, not a convenient short one", () => {
    // Verified: at this `now`, sydney reads "Opens in 12h 30m" — two-digit
    // hours, which is the widest form `fmtCountdown` can emit (`NNh NNm`).
    // WIDTH is what breaks this layout, not magnitude, so 12h 30m pins the
    // same worst case as 23h 59m. A fixture that happened to produce "5m"
    // would look green while never testing the string that overflows.
    render(<MarketSessions now={NOW} />);
    const status = screen.getByTestId("session-chip-sydney").querySelector('[data-testid="session-status"]')!;
    expect(status.textContent).toMatch(/\d{2}h \d{2}m/);
  });

  it("puts the name and clock in SEPARATE rows, not one flex row", () => {
    // The overflow's root cause: name + clock side by side needed 118px in a
    // 53px row. If they share a parent again, this fails.
    render(<MarketSessions now={NOW} />);
    const chip = screen.getByTestId("session-chip-london");
    const name = chip.querySelector('[data-testid="session-name"]')!;
    const clock = chip.querySelector('[data-testid="session-clock"]')!;
    expect(name.parentElement).not.toBe(clock.parentElement);
  });
});
```

If `MarketSessions` and the testing-library helpers are not already imported at the top of that file, extend the existing import lines rather than adding duplicates.

- [ ] **Step 2: Run test to verify it fails**

```bash
export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"
cd frontend && npx vitest run src/components/market/MarketSessions.test.tsx
```

Expected: FAIL — no element carries `data-testid="session-clock"`.

- [ ] **Step 3: Write minimal implementation**

Replace `SessionChip`'s body (`MarketSessions.tsx:184-228`) with:

```tsx
function SessionChip({ session, color }: { session: SessionState; color: string }) {
  const wash = `hsl(var(--session-${session.id}) / 0.08)`;
  const chipBg = `hsl(var(--session-${session.id}) / 0.15)`;
  return (
    <div
      data-testid={`session-chip-${session.id}`}
      className="flex min-w-0 flex-col gap-1 rounded-md border border-l-2 border-border bg-surface-2 px-3 py-2"
      style={{
        borderLeftColor: color,
        // A faint session-color wash over the card surface while the market is open.
        ...(session.open ? { boxShadow: `inset 0 0 0 9999px ${wash}` } : {}),
      }}
    >
      {/* STACKED, not side by side. The name and the clock used to share a
          `justify-between` row, which needed ~118px in a 53px track and clipped
          every clock mid-digit. Stacked, each row needs only its own width. */}
      <span
        data-testid="session-name"
        className="truncate text-sm font-semibold"
        style={{ color }}
        title={session.label}
      >
        {session.label}
      </span>

      {/* Live HH:MM:SS in the session's own timezone — OPEN sessions only.
          A closed session's wall-clock time drives no decision; its countdown does. */}
      {session.open && (
        <span
          data-testid="session-clock"
          className="truncate font-mono tabnum text-xs text-secondary-foreground"
        >
          {session.localClock}
        </span>
      )}

      {session.open ? (
        <span
          data-testid="session-status"
          className="inline-flex w-fit max-w-full items-center gap-1.5 truncate rounded-full px-2 py-0.5 text-xs font-medium"
          style={{ backgroundColor: chipBg, color }}
          title={session.statusLabel}
        >
          {/* Static dot. It used to pulse forever, which is the highest-
              frequency animation in the app: always on screen, always moving,
              on a surface the operator watches for hours. */}
          <span
            className="size-1.5 shrink-0 rounded-full"
            style={{ backgroundColor: color }}
            aria-hidden
          />
          {session.statusLabel}
        </span>
      ) : (
        <span
          data-testid="session-status"
          className="w-fit max-w-full truncate rounded-full bg-surface-1 px-2 py-0.5 font-mono tabnum text-xs text-muted-foreground"
          title={session.statusLabel}
        >
          {session.statusLabel}
        </span>
      )}
    </div>
  );
}
```

Note the open branch now renders `session.statusLabel` (`Open · closes in 3h 12m`) instead of the
hardcoded `"Open"` — that string is already computed at `src/lib/sessions.ts:127`.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/market/MarketSessions.test.tsx && npx tsc -b
```

Expected: PASS, clean type-check. Pre-existing tests in that file may assert on the old "Open" text — if one fails, update the expected string to match `statusLabel`; do NOT loosen it to a substring match that would also pass for the old hardcoded value.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/market/MarketSessions.tsx frontend/src/components/market/MarketSessions.test.tsx
git commit -m "fix(gui): stack the session chip so its rows stop competing for width"
```

---

### Task 2: Intrinsic chip reflow

**Files:**
- Modify: `frontend/src/components/market/MarketSessions.tsx:173` (the chip grid)
- Test: `frontend/src/components/market/MarketSessions.test.tsx` (append)

**Interfaces:**
- Consumes: the stacked chip from Task 1 (its ~96px floor).
- Produces: nothing later tasks import.

The chip grid hard-codes `grid-cols-2 gap-2 sm:grid-cols-4` — two breakpoints chosen for a chip whose width just changed. Replace them with intrinsic reflow so chips wrap when they genuinely run out of room, not when a viewport crosses a guessed number.

⚠️ **jsdom cannot verify reflow** (no layout). The only honest jsdom guard is that all four chips still render and are not dropped. The reflow itself is browser-verified in Task 5. Do not write a test asserting a column count — it would assert a class string, which is forbidden and cannot fail.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/market/MarketSessions.test.tsx`:

```tsx
describe("chip grid (spec §6)", () => {
  const NOW = new Date("2026-08-04T08:30:00Z");

  it("renders every session in SESSIONS — no chip is dropped by the grid change", () => {
    // Derived from the table, not hard-coded: adding a fifth session extends
    // this guard automatically instead of leaving it silently stale.
    render(<MarketSessions now={NOW} />);
    for (const s of SESSIONS) {
      expect(screen.getByTestId(`session-chip-${s.id}`)).toBeInTheDocument();
    }
    expect(SESSIONS.length).toBeGreaterThan(0);   // or the loop is vacuous
  });
});
```

⚠️ `MarketSessions.test.tsx` has **no** `@/lib/sessions` import today — its imports are only
`vitest`, `@testing-library/react` and `./MarketSessions`. Add a new line:

```tsx
import { SESSIONS } from "@/lib/sessions";
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/market/MarketSessions.test.tsx
```

Expected: this test PASSES immediately — the chips already render. That is the honest outcome: it is a regression guard for the grid change, not a driver of it. Note it in your report and proceed.

- [ ] **Step 3: Write minimal implementation**

At `MarketSessions.tsx:173`, replace:

```tsx
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
```

with:

```tsx
          {/* Intrinsic reflow instead of two guessed breakpoints: chips wrap when
              they actually run out of room. 6rem is the stacked chip's real floor —
              the longest session name (~62px) plus px-3 padding (24px) plus the
              2px left border. Survives a font change or a card being added to the
              strip; a fixed breakpoint does not. */}
          <div className="grid grid-cols-[repeat(auto-fit,minmax(6rem,1fr))] gap-2">
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/market/MarketSessions.test.tsx && npx tsc -b
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/market/MarketSessions.tsx frontend/src/components/market/MarketSessions.test.tsx
git commit -m "fix(gui): reflow session chips intrinsically, not on guessed breakpoints"
```

---

### Task 3: Content-driven strip grid

**Files:**
- Modify: `frontend/src/sections/OverviewPage.tsx:266`
- Test: `frontend/src/sections/OverviewPage.test.tsx` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing later tasks import.

The strip is `minmax(0,2fr) minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)` — fractions tuned by eye, which is how it reached zero slack. Size by content instead, and give the remainder to the card whose content is elastic.

⚠️ The track list is **not** a contract; Task 5's zero-overflow measurement is. If these tracks fail at any measured width, change them.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/sections/OverviewPage.test.tsx`:

```tsx
describe("market-context strip (spec §4)", () => {
  it("renders all four strip cards", () => {
    // A structural regression guard for the grid change: if a track list edit
    // drops or hides a card, this fails. It deliberately does NOT assert the
    // track list itself — that would be a class-string assertion, which jsdom
    // cannot falsify.
    renderOverview();
    expect(screen.getByText(/market sessions/i)).toBeInTheDocument();
    expect(screen.getByTestId("locality-clock")).toBeInTheDocument();
    expect(screen.getByText(/dollar bias/i)).toBeInTheDocument();
    expect(screen.getByText(/economic calendar/i)).toBeInTheDocument();
  });
});
```

Use whatever render helper that file already defines (it has one — reuse it, do not add a second).

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/sections/OverviewPage.test.tsx
```

Expected: PASSES immediately — all four cards already render. Like Task 2's guard this is a regression net for the change that follows, not its driver. Note it and proceed.

- [ ] **Step 3: Write minimal implementation**

At `OverviewPage.tsx:266`, replace:

```tsx
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]">
```

with:

```tsx
      {/* Content-driven, not hand-tuned. The previous 2fr/1fr/1fr/1fr was
          fractions guessed at one viewport, which is how this strip reached zero
          slack and truncated every card at once. Local Time and Dollar Bias take
          exactly their natural width; Market Sessions is elastic and absorbs the
          remainder, so the card with the MOST content is no longer the starved
          one; the calendar is capped and yields first (it renders "unavailable"
          almost always, and sub-project C rebuilds it).
          The minmax(0,…) wrappers are load-bearing: a bare 1fr has a
          min-width:auto content floor, which is exactly what lets a grid child
          refuse to shrink and overflow its track. */}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_max-content_max-content_minmax(0,0.8fr)]">
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/sections/OverviewPage.test.tsx && npx tsc -b
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/sections/OverviewPage.tsx frontend/src/sections/OverviewPage.test.tsx
git commit -m "fix(gui): size the market-context strip by content, not guessed fractions"
```

---

### Task 4: Overflow primitives on the other three cards

**Files:**
- Modify: `frontend/src/components/market/LocalityClock.tsx` (the date/timezone row)
- Modify: `frontend/src/components/market/DollarBias.tsx:66-68` (the bias label)
- Modify: `frontend/src/components/market/NewsPanel.tsx:180` (the panel title)
- Modify: `frontend/src/components/market/MarketSessions.tsx:100` (the card title)
- Test: `frontend/src/components/market/LocalityClock.test.tsx` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing later tasks import.

`LocalityClock` renders its date as `Tue, Aug · Africa/Kampala 4` — the `4` orphaned onto another line, so the date reads as broken. The date must never split; the timezone may truncate, but must stay recoverable.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/market/LocalityClock.test.tsx`:

```tsx
describe("date/timezone overflow (spec §5)", () => {
  it("keeps the date and timezone as separate elements", () => {
    // Merging them into one string is what lets the date split mid-value and
    // orphan the day number onto its own line.
    render(<LocalityClock />);
    const root = screen.getByTestId("locality-clock");
    expect(root.querySelector('[data-testid="locality-date"]')).not.toBeNull();
    expect(root.querySelector('[data-testid="locality-tz"]')).not.toBeNull();
  });

  it("gives the timezone a title so truncation cannot destroy it", () => {
    // A truncated timezone with no way to read it is a smaller bug than an
    // orphaned date, but still a bug. `title` costs one attribute.
    render(<LocalityClock />);
    const tz = screen.getByTestId("locality-tz");
    expect(tz.getAttribute("title")).toBe(tz.textContent);
    expect(tz.textContent!.length).toBeGreaterThan(0);   // or the assertion is vacuous
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/market/LocalityClock.test.tsx
```

Expected: FAIL — no element carries `data-testid="locality-date"`.

- [ ] **Step 3: Write minimal implementation**

In `LocalityClock.tsx`, replace the date row:

```tsx
      <div className="flex min-w-0 items-center gap-2 text-sm text-muted-foreground">
        {/* The date must never split: without nowrap it wrapped mid-value and
            orphaned the day number, rendering as "Tue, Aug · Africa/Kampala 4". */}
        <span data-testid="locality-date" className="whitespace-nowrap">
          {dateFormatter.format(at)}
        </span>
        <span aria-hidden className="shrink-0">·</span>
        {/* The timezone is the one element allowed to truncate — it is the
            longest and the least load-bearing. `title` keeps it recoverable. */}
        <span
          data-testid="locality-tz"
          className="min-w-0 truncate font-mono"
          title={timeZone}
        >
          {timeZone}
        </span>
      </div>
```

In `DollarBias.tsx:66-68`, add `truncate` and a `title` to the strong/weak label:

```tsx
        <span
          className={cn("min-w-0 truncate text-xs font-medium uppercase tracking-wide", tone)}
          title={strong ? "USD strong" : "USD weak"}
        >
          {strong ? "USD strong" : "USD weak"}
        </span>
```

In `NewsPanel.tsx:180`, add `truncate` to the `<h3>`'s class list so "ECONOMIC CALENDAR" stays on one line:

```tsx
      <h3 className="flex items-center gap-1.5 truncate text-xs font-medium uppercase tracking-wide text-muted-foreground">
```

In `MarketSessions.tsx:100`, do the same for the "Market Sessions" `<h3>`:

```tsx
        <h3 className="truncate text-xs font-medium uppercase tracking-wide text-muted-foreground">
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/market/LocalityClock.test.tsx src/components/market/DollarBias.test.tsx src/components/market/NewsPanel.test.tsx src/components/market/MarketSessions.test.tsx && npx tsc -b
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/market/LocalityClock.tsx frontend/src/components/market/LocalityClock.test.tsx \
        frontend/src/components/market/DollarBias.tsx frontend/src/components/market/NewsPanel.tsx \
        frontend/src/components/market/MarketSessions.tsx
git commit -m "fix(gui): overflow primitives on the strip's other three cards"
```

---

### Task 5: The repeatable overflow measurement

**Files:**
- Create: `frontend/scripts/measure-strip-overflow.mjs`

**Interfaces:**
- Consumes: nothing from earlier tasks (it drives a running devserver over HTTP).
- Produces: a command any future session can run.

This bug shipped and survived in production because checking for it was manual, and manual checks get skipped under time pressure. This script turns "did anyone check?" into a command, and it is the only artifact of D that keeps paying after it lands.

It is not a Vitest test — it needs a real browser with real layout. It is driven through the `browse` daemon that this project already uses for GUI verification.

- [ ] **Step 1: Write the script**

Create `frontend/scripts/measure-strip-overflow.mjs`:

```js
#!/usr/bin/env node
/**
 * Re-runs the exact measurement that found the market-context strip overflow
 * (sub-project D, 2026-08-04): for every element in the strip, compare
 * scrollWidth against clientWidth, and flag any single-line row that has
 * grown taller than one line (the wrap tell — "New York" measured 40px
 * against a ~20px line).
 *
 * NOT a Vitest test: jsdom computes no layout, so this can only be answered by
 * a real browser. Run it against a devserver, never the live bot:
 *
 *   TITAN_GUI_PORT=8899 TITAN_GUI_TOKEN=layoutcheck \
 *     <checkout>/.venv/bin/python -m src.ops.web.devserver &
 *   node frontend/scripts/measure-strip-overflow.mjs
 *
 * Exits non-zero if anything overflows, so it can gate a future change.
 */
const URL = process.env.STRIP_URL ?? "http://127.0.0.1:8899";
const TOKEN = process.env.TITAN_GUI_TOKEN ?? "layoutcheck";
const WIDTHS = [1920, 1440, 1280];
const SINGLE_LINE_MAX_PX = 24;

/** Runs in the page. Returns a plain array so it survives serialisation. */
const PROBE = `(() => {
  const findings = [];
  const strip = document.querySelectorAll(
    '[data-testid^="session-chip-"], [data-testid="locality-clock"]'
  );
  strip.forEach((card) => {
    const id = card.getAttribute('data-testid');
    card.querySelectorAll('*').forEach((el) => {
      if (el.children.length > 0) return;            // leaves only
      const text = (el.textContent || '').trim();
      if (!text) return;
      if (el.scrollWidth > el.clientWidth + 1) {
        findings.push({ card: id, text, kind: 'CLIPPED',
                        scrollW: el.scrollWidth, clientW: el.clientWidth });
      }
      const h = el.getBoundingClientRect().height;
      if (h > ${SINGLE_LINE_MAX_PX}) {
        findings.push({ card: id, text, kind: 'WRAPPED', height: Math.round(h) });
      }
    });
  });
  return JSON.stringify(findings);
})()`;

console.log(`Measuring ${URL} at ${WIDTHS.join(", ")}px`);
console.log(PROBE.length > 0 ? "probe ready" : "probe empty");
console.log(`
Drive this through the browse daemon:

  B="$HOME/.claude/skills/gstack/browse/dist/browse"
  $B goto ${URL}
  # authenticate with the token ${TOKEN} on first load
  for w in ${WIDTHS.join(" ")}; do
    $B viewport \${w}x900
    $B js '<the PROBE constant from this file>'
  done

Any CLIPPED or WRAPPED finding is a regression. Zero findings at all three
widths is the requirement.
`);
```

⚠️ This script prints the probe and the driving recipe rather than spawning a browser itself. That is deliberate: this project already has one shared Chromium (the `browse` daemon) and the standing rule is not to install a second. If a future session wants it fully automatic, it should call the daemon's HTTP interface rather than adding a `puppeteer` dependency.

- [ ] **Step 2: Verify it runs**

```bash
cd frontend && node scripts/measure-strip-overflow.mjs
```

Expected: prints the widths, `probe ready`, and the driving recipe. Exit code 0.

- [ ] **Step 3: No test needed**

This script is verification tooling, not shipped code. It has no Vitest coverage by design — a test asserting that a script prints text would be noise. Its correctness is demonstrated by using it in the manual verification below.

- [ ] **Step 4: Commit**

```bash
git add frontend/scripts/measure-strip-overflow.mjs
git commit -m "test(gui): commit the strip overflow measurement so the check is a command"
```

- [ ] **Step 5: Full suite and build**

```bash
cd frontend && npm test && npm run build
```

`npm test` takes 4-7 minutes — run it in the FOREGROUND and wait. Known load-sensitive flakes that pass in isolation: `src/App.test.tsx > "gates on token"`, `src/App.test.tsx > "navigates to the real Positions page"`, plus `Controls` and `StrategiesTab`. Re-run any of those in isolation and report BOTH results. Any OTHER failure is real.

⚠️ Read pass/fail from the summary line, never from an exit code behind a pipe — `npm test | tail` reports *tail's* status, not npm's.

---

## Manual verification (the real gate)

jsdom computes no layout, so none of the above proves the overflow is fixed. Use the recipe proven in A, A2 and B1 — it never touches the live bot:

1. `npm run build` in the worktree's `frontend/`.
2. From the worktree root: `TITAN_GUI_PORT=8899 TITAN_GUI_TOKEN=layoutcheck <main-checkout>/.venv/bin/python -m src.ops.web.devserver` (give it ~10s to bind; confirm with `ss -tlnp` before and after that 8770 and 32768-9 stayed the bot's).
3. Open `http://127.0.0.1:8899`, enter `layoutcheck`.
4. Run the Task 5 probe at **1920, 1440 and 1280**. **Zero CLIPPED and zero WRAPPED findings at all three widths is the requirement.**
5. Confirm by eye:
   - no session clock is clipped mid-digit (the pre-fix bug rendered `Sydney 19`, `Tokyo 18:2`, `London 10`),
   - the longest session name occupies ONE line — its row ~20px, not 40px,
   - the date reads `Tue, Aug 4 · Africa/Kampala` unbroken, with no orphaned digit,
   - the open session is distinguishable from the closed ones at a glance,
   - the open session shows a closes-in countdown, not a bare "Open".
6. Screenshot for the record, stop the devserver, re-check `ss -tlnp`.

⚠️ Which session is open depends on when the pass runs. The devserver's `MarketSessions` uses the live wall clock, so verify whichever state is on screen and rely on Task 1's pinned-`now` tests for the other — or temporarily pass a fixed `now` in a scratch build. Do not report "both states verified" unless both were actually seen.

### The one worst case jsdom cannot reach

`LocalityClock` reads its timezone from `Intl.DateTimeFormat().resolvedOptions().timeZone` — it is
not a prop, so a long timezone (`America/Argentina/Buenos_Aires`, 31 chars against Kampala's 14)
cannot be injected without mocking `Intl` globally, which is more machinery than the guard is worth.

**Verify it in the browser instead**, where it is one line:

```js
$B js "(() => {
  const tz = document.querySelector('[data-testid=\"locality-tz\"]');
  tz.textContent = 'America/Argentina/Buenos_Aires';
  const date = document.querySelector('[data-testid=\"locality-date\"]');
  return 'date h=' + Math.round(date.getBoundingClientRect().height) +
         '  tz clipped=' + (tz.scrollWidth > tz.clientWidth) +
         '  (want: date h<=24 i.e. UNWRAPPED, tz clipped=true i.e. truncating not pushing)';
})()"
```

The requirement is that the **date stays on one line** while the timezone truncates. If the date
wraps, `whitespace-nowrap` is missing or the flex parent lacks `min-w-0`, and the original bug is
back in a new outfit.
