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
