# Titan Control GUI — motion foundation + hardening

Branch `feat/gui-motion`, off `main` (`ab2ad69`).

Base note: the task described `frontend/` as it exists on **main**, not on
`feat/gui-redesign`. Main is ahead — it carries `AccentToggle` (the two-accent
theming the brief relies on) and the redesign branch does not. All work is on
main's tree.

## Phase 0 — premise checks

All three blocking premises **confirmed** against the live tree before any edit.

| # | Premise | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | `--motion-fast`, `--motion-base`, `--ease` declared at `tokens.css:34`, referenced nowhere else | **Confirmed** | `grep -rn -- '--motion-fast\|--motion-base\|--ease' src/ *.ts *.json` returns exactly one hit: the declaration itself |
| 2 | `plugins: []`, `tailwindcss-animate` not installed | **Confirmed** | `tailwind.config.ts:56`; absent from `package.json`, `package-lock.json`, and `node_modules/` |
| 3 | Therefore every `animate-in` / `fade-in-0` / `zoom-in-95` / `slide-in-from-*` in `dialog.tsx` and `alert-dialog.tsx` compiles to nothing → dialogs had **no animation at all** | **Confirmed** | Follows from 2; classes present at `dialog.tsx:19,36` and `alert-dialog.tsx:18,35` |

Every `file:line` in the Phase 2 table was also confirmed before being edited.

## Disagreements with the brief

Stated explicitly, as asked.

### 1. Sidebar collapse — rejected the proposed fix, kept the finding

The brief says replace `transition-[width]` with "a transform-based collapse".
The diagnosis is right; that remedy does not work here. The `<aside>` is
**in flow** (`AppShell.tsx:113-117`, `flex h-dvh` → `hidden md:flex` → `Sidebar`),
so its width *is* the width of `<main>`. A translated element keeps its layout
box, so `main` would never reclaim the space — the sidebar would slide away and
leave a 240px hole.

There is no way to animate this that does not animate layout. So the choice is
"animate layout every frame on a live trading view" or "don't animate". I removed
the transition: the collapse now snaps. It is a deliberate, low-frequency action
where the operator is looking at the result, and an instant result is never slow.

### 2. Toast exit — enter only, deliberately

The brief asks for enter *and* exit. The toast is conditionally rendered
(`{actionError && …}`), so React unmounts it the instant the state clears; a real
exit would mean keeping a failed command's toast mounted after its own error
state was cleared, purely to animate it. The enter is the half that carries the
purpose (a failure must not be indistinguishable from a repaint). Exit is instant
and documented as such in `index.css`.

### 3. `@starting-style` cannot drive the dialogs

The brief offered `@starting-style` as the no-dependency path. It gives an enter
and no exit: Radix defers unmount only while a real CSS **animation** runs (it
waits on `animationend`). The zero-dependency path is therefore hand-rolled
`@keyframes`, which is what was built after the owner chose that option.
`@starting-style` *is* used for the toast, where the enter is all that is wanted.

## Phase 3 — premises that turned out to be stale

| Item | Finding |
| --- | --- |
| 1 Hz clock re-rendering tables/charts | **Not a defect.** `useNow` is called inside three leaf components (`StatusBar.tsx:55`, `MarketSessions.tsx:54`, `LocalityClock.tsx:23`), never in a common ancestor. A `useState` tick re-renders only that component's own subtree, so the positions table and Recharts equity chart are already isolated. No memoization needed; adding it would be cargo cult. |
| `PositionsTable` uses `@tanstack/react-virtual` | **Stale premise.** The dependency is real but it is used by `ActivityPage.tsx:41` (the event feed), not by the positions table. Virtualizing the positions table is not worth building: the account trades 12 pairs, so the row count is tens, and a virtualizer on a short table costs measurement work and breaks native find-in-page for no gain. |
| Accent leaking into P&L | **Already clean.** One mapping, `pnlToneClass` (`lib/format.ts:26`), returns `text-profit` / `text-loss` / `text-muted-foreground`, bound to `--profit` / `--loss`. No path from `--accent` to a P&L figure. |
| `aria-live` on connection state | **Already present.** `StatusBar.tsx:129` is `role="status" aria-live="polite"`. The tick countdown is deliberately excluded, with a comment saying why (`StatusBar.tsx:50`) — a settled decision, left alone. |
| `focus-visible` coverage | No gaps found: every component file containing a `<button>` also carries `focus-visible` ring classes. |
| Positions table keyboard navigation | **Already satisfied.** The only interactive element per row is a real `<button>` (`PositionsTable.tsx:61-76`) with `aria-label="Close position {ticket}"`, a `focus-visible` ring, and disabled handling. Native tab order already reaches every action, and the accessible name already says *which* position. A roving-tabindex grid would add arrow-key semantics to a table with no selection model and one action per row — more code, no capability. |

## Changes made

| Before | After | Why |
| --- | --- | --- |
| `--motion-fast/base`, `--ease` declared, referenced nowhere | Bound via `transitionTimingFunction` / `transitionDuration`, incl. `DEFAULT` | Without the `DEFAULT` override every bare `transition-*` silently used Tailwind's 150ms / `cubic-bezier(.4,0,.2,1)` and the tokens governed nothing |
| One `--ease: cubic-bezier(0.2,0,0,1)` | `--ease-out` `cubic-bezier(0.23,1,0.32,1)`, `--ease-in-out` `cubic-bezier(0.77,0,0.175,1)`, `--ease` plain | Enter/exit/press, on-screen movement and hover are three different jobs; CSS's built-ins are too weak to read as intentional |
| `animation-duration: 0.001ms !important` only | `+ animation-iteration-count: 1 !important`, `+ scroll-behavior: auto` | `animate-pulse`/`animate-spin` looped **forever** at 0.001ms — a strobe, worse than the motion being suppressed |
| `data-[state=open]:animate-in zoom-in-95 …` (compiled to nothing) | `@keyframes titan-dialog-in/out` on `[data-titan-dialog][data-state]` | Both modals had no animation at all. Keyframes not `@starting-style`: Radix defers unmount on `animationend`, a transition gives enter with no exit |
| Dialog enter unspecified | `scale(0.95)` + `opacity: 0`, centre origin, enter 220ms / exit 150ms | Nothing appears out of nothing; exit faster than enter — the operator has already decided; modals are not trigger-anchored |
| `button`: `transition-colors`, no `:active` | `active:scale-[0.97]`, `transform` named in `transition-property` | Panic, close-all and confirm gave zero press feedback. A scale outside `transition-property` snaps |
| `Sidebar`: `transition-[width]` | no transition | `width` is layout: it relayouts the equity chart + positions table every frame. Transform can't replace it here (see disagreement 1) |
| `StatTiles`: `transition-all duration-200` | `transition-[border-color,box-shadow] duration-fast` | `transition-all` animates properties you never intended, incl. layout ones added later by a `className` override |
| `StatTiles`: `hover:-translate-y-0.5` | removed | Frequency rule — the KPI row is scanned constantly; a springy tile reads as noise on a dense trading board |
| `tabs`: `transition-all` | `transition-[color,background-color,box-shadow]` | Same |
| `hover:` utilities ungated | `future: { hoverOnlyWhenSupported: true }` | On touch a tap fires `:hover` and the element stays stuck. `:active` is deliberately *not* gated — a tap should press |
| Failure toast appears instantly | rises `translate(-50%,100%)` → `0` + fade, 220ms ease-out, `@starting-style` | This surface exists only when something failed; blinking in is indistinguishable from a repaint |
| 3 skeleton bars pulsing in unison | `animationDelay` 0 / 60 / 120ms | Synchronised pulsing reads as one mechanical block; offset reads as a wave |
| Session dot `animate-pulse` forever | static dot | Highest-frequency animation in the app — always on screen, always moving — and the chip already says "Open" in the session colour |

## Verification

`npm test` — **166 passed, 38 files, rc=0**, run with `--no-file-parallelism`.

> A parallel run first reported 11 failures, all in `userEvent.type` tests.
> They were a **load artifact**: `uptime` showed a load average of 39 with
> another session's Python `unittest` suite running concurrently, and all 6
> affected files pass in isolation. CSS changes cannot alter jsdom behaviour —
> jsdom never loads the stylesheet. Nothing was accepted on that basis alone.

`npm run build` — clean, rc=0. (The >500 kB chunk warning is pre-existing and
comes from Recharts; not introduced here.)

### Real-browser checks — 11/11

The DoD asks for a browser pass. jsdom cannot do any of this: it does not load
CSS, does not run animations, and has no media-query emulation. So the
production `dist/` was served on a spare port and driven with Playwright,
asserting on the **live engine's** `getAnimations()` and computed styles.

| Check | Result |
| --- | --- |
| Dialog enter animates | `titan-dialog-in` 220ms `cubic-bezier(0.23, 1, 0.32, 1)` |
| Dialog exit animates | `titan-dialog-out` 150ms |
| Exit faster than enter | 220ms enter vs 150ms exit |
| Enter from a visible scale | `0% … scale(0.95)` → `100% … scale(1)`, never `scale(0)` |
| Reduced motion **off** | `animate-pulse` iteration-count `infinite`, still running after 100ms |
| Reduced motion **on** | iteration-count `1`, duration `1e-06s`, **stopped** after 100ms |
| Hover on fine pointer | `@media (hover: hover) and (pointer: fine)` matches |
| Hover on Pixel 5 (touch) | does **not** match — hover cannot stick |
| Button `:active` scale | `active:scale-[0.97]` present and compiled |
| `transform` transitionable | in `transition-property` |
| Press timing | `0.15s` / `cubic-bezier(0.23, 1, 0.32, 1)` |

That last row is why this pass was worth running. It initially read
`cubic-bezier(0.25, 0.1, 0.25, 1)` — the default `--ease`, which the token
comment reserves for hover and colour. The suite was green and could not see
it; the fix is commit `08adcd0`.

### What was NOT verified

**The 4x slow-motion feel-check was not done.** The Playwright pass proves each
animation *fires* with the intended curve and duration; it does not prove the
result *feels* right, which is a human judgement made by watching the real
modal open in DevTools' Animations panel at reduced speed. The app also could
not be driven end-to-end here: the offline harness (`scripts/gui_demo_server.py`)
hardcodes port 8770, and the live demo-forward bot has held that port for ~20h.
I did not go near it. Watching the real dialog, sidebar and toast in a browser
is the remaining step, and it is yours to make or mine on request.

- **`aria-live` on P&L.** Asked for, deliberately not built. P&L updates on every
  heartbeat; a live region on it would announce a new number every few seconds
  and make the dashboard unusable with a screen reader — the opposite of the
  goal. If you want this, it needs a trigger worth announcing (crossing zero, a
  threshold move, or a position closing) rather than the raw figure. That is a
  product decision, so I left it for you.
- **Virtualizing `PositionsTable`.** 12 traded pairs means tens of rows;
  a virtualizer costs measurement work and breaks find-in-page for no gain.
- **Compact/density mode.** The brief says propose before building. Proposal: a
  single `data-density="compact"` on the table wrapper driving row padding via a
  token, persisted alongside the sidebar-collapsed preference. Not built.
- **Memoizing around `useNow`.** Not needed — see the stale-premise table.
- **Any animation on `CommandPalette`.** Left untouched, as instructed.
