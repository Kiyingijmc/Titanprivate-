# Maximizable panels — design (sub-project A)

**Date:** 2026-08-03
**Status:** approved design, not yet implemented
**Scope:** the shared maximize-to-75% primitive for the Equity and Economic Calendar
panels, plus the chart sizing change that makes maximizing meaningful.

---

## 1. Why

The operator asked for the equity chart and the news panel to be maximizable to 75% of
the screen. Both panels are small tiles on a dense Overview page; the equity curve in
particular is drawn at a hardcoded **140px** tall, which is too short to read a day of
trading, let alone a month.

This spec covers **only** the shared expand mechanism and the sizing work it depends on.
The richer content that will eventually fill the expanded views is deliberately deferred
— see §10.

## 2. Scope

**In scope**

- A reusable maximize affordance and dialog, used by both panels.
- `EquitySparkline` becomes size-driven rather than fixed-height.
- The single-instance invariant (§6) that makes the above safe.

**Explicitly NOT in scope** (each has its own spec)

- Chart legend, risk overlays, trade-exit markers, analytics strip → sub-project **B**
- Week-ahead calendar, impact levels, per-event symbol impact, filters → sub-project **C**
- Market-context strip redesign and its text-overflow bug → sub-project **D**
- Semantic colour tokens and status tinting → sub-project **A2**

Maximizing the news panel in A shows **the same content in a bigger box**. That is
expected, not a defect; C fills it. Stated here so it does not read as broken on first
click.

## 3. Components

Three additions. No new dependencies — `@radix-ui/react-dialog` and
`components/ui/dialog.tsx` already exist.

| File | Responsibility |
|---|---|
| `components/shell/MaximizeButton.tsx` | Icon-only button (lucide `Maximize2`), `aria-label="Maximize {title}"`. Presentational; no state. |
| `components/shell/MaximizedDialog.tsx` | Wraps `Dialog`/`DialogContent` with 75% sizing, a required `DialogTitle`, and a flex-column body whose child region is `flex-1 min-h-0` so content *fills* instead of sitting at a fixed height. |
| `sections/OverviewPage.tsx` | Owns one state value: `maximized: "equity" \| "news" \| null`. |

### Wiring

The two panels are built differently and neither is forced to become the other:

- **`shell/Panel.tsx`** gains an optional `onMaximize?: () => void`. When present it
  appends `<MaximizeButton>` to the existing `actions` slot. Panels that omit it are
  unchanged.
- **`market/NewsPanel.tsx`** gains the same optional prop, rendered in its existing
  `Header` beside the status badge.

A single `maximized` value (rather than a boolean per panel) makes "only one panel
maximized at a time" structural instead of something to enforce.

## 4. Sizing

```
w-[95vw] h-[85vh]  md:w-[75vw] md:h-[75vh]
```

75% of a phone screen is unusable, so the 75% target applies from the `md` breakpoint up.
The stock `DialogContent` carries `max-w-lg`, which must be overridden with `max-w-none`
or the dialog will never exceed 32rem regardless of the width class.

`EquitySparkline`'s `height` prop widens from `number` to `number | string` and is passed
`"100%"` inside the dialog. `ResponsiveContainer` measures its parent, so the dialog body
must be a real sized box (`flex-1 min-h-0`) — without `min-h-0` a flex child refuses to
shrink below its content and the chart overflows the dialog.

## 5. Data flow

Nothing new fetches. `useEquitySeries(api, range)`, `useLiveEquityTail`, `withLiveTail`
and `range` all already live in `OverviewPage`; the dialog receives the same computed
values as props. Maximizing costs zero extra requests, and the maximized chart is the
same live object as the collapsed one.

The range selector **moves into** the dialog while maximized, so ranges can still be
switched — it reads and writes the same `range` state.

## 6. The single-instance invariant

**While a panel is maximized, its collapsed body renders only a fixed-height placeholder
— no chart, no range selector, no news card.** The dialog owns the single live instance.

This is a correctness constraint, not tidiness. Three reasons, in order of severity:

1. **It breaks the existing test suite.** `OverviewPage.test.tsx` does
   `await screen.findByTestId("range-selector")` and then
   `within(selector).getByRole("radio", { name: "1d" })`. Testing Library's
   `findByTestId`/`getByTestId` **throw on multiple matches**. A second `range-selector`,
   `equity-sparkline`, or `news-panel` in the tree fails tests that have nothing to do
   with this feature.
2. **Assistive tech announces both.** Two identical radio groups, two charts.
3. **It doubles live chart work.** Two `ComposedChart` instances re-rendering on every
   heartbeat, one of them invisible behind an opaque backdrop — the opposite of the
   "feels live / snappier" goal that motivated this work.

Keeping the placeholder at the collapsed body's height means closing the dialog causes no
layout shift.

## 7. Status, errors, accessibility, motion

**Status and errors follow the live instance.** The `equity-fetch-error` banner and the
`PanelStatus` states render wherever the single live instance is. A dead `/api/equity`
must stay visible at 75%; wiring errors only to the collapsed panel would re-introduce, in
a new place, the exact defect the equity branch's final review caught — a healthy-looking
frozen curve with the failure hidden.

**Accessibility** is mostly Radix's: Esc, click-outside, focus trap, focus restored to the
maximize button, body scroll lock. We supply `DialogTitle` (Radix warns without one; it is
what names the dialog for assistive tech) and the button's `aria-label`.

**Motion** needs no new work. `index.css` already binds `@keyframes titan-dialog-in/out`
and `titan-overlay-in/out` to `[data-titan-dialog]`/`[data-titan-overlay]` via
`--motion-base`/`--ease-out`, and the global `prefers-reduced-motion` block pins
iteration-count to 1.

**Read-only mode** is unaffected — maximize is a view action with no mutating route.

## 8. Testing

Vitest + Testing Library:

- Maximize button renders only when `onMaximize` is passed.
- Clicking opens a dialog with an accessible name — `getByRole("dialog", { name: /equity/i })`.
- **Single-instance invariant:** `getAllByTestId("equity-sparkline")` has length exactly 1
  while maximized; likewise `range-selector` and `news-panel`. This is the test that
  catches the §6 regression.
- Esc closes and focus returns to the maximize button.
- Switching range from inside the dialog calls `api.getEquity` with the new range.
- `equity-fetch-error` renders inside the dialog when the fetch is failing while maximized.

### Deliberately not unit-tested

**No assertion on `w-[75vw]`/`h-[75vh]` class strings, and none on dialog easing.** jsdom
computes no layout, so `className.includes("w-[75vw]")` passes whether or not the dialog
is actually 75% — a green test proving nothing. This repo has been bitten by exactly this
before (`expect(Component.toString()).not.toContain('isAnimationActive={true}')` could
never fail, because JSX compilation means that string never exists). Real sizing and
motion belong in the committed Playwright harness.

The test to ask of any guard here: *what mutation makes this red?* If the answer is
"none", it should not be written.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Duplicate testids break unrelated existing tests | §6 invariant, with a test that asserts the count |
| `max-w-lg` silently caps the dialog | Explicit `max-w-none`; verified visually, not by class assertion |
| Flex child won't shrink, chart overflows | `min-h-0` on the fillable region |
| Closing causes layout shift | Placeholder matches collapsed body height |

## 10. Roadmap (recorded so it is not lost)

Ordered. Each gets its own spec → plan → implementation cycle.

- **A2 — Visual language foundation.** Semantic colour tokens: news impact levels,
  win/loss on markers, drawdown severity, per-session colours, panel status tinting, and
  a richer surface/accent treatment. Defined once in `tokens.css` so B/C/D consume one
  vocabulary instead of inventing three.
- **B — Equity chart, institutional grade.** Legend/key (there is currently **none**, for
  three drawn series). Risk overlays: high-water mark, max-drawdown marker, daily 3%
  breaker threshold. Trade **exit** markers. Analytics strip: peak, max DD %, return %,
  win rate, profit factor.
  *Constraint:* `trade_history` stores `close_time` but **no open timestamp** (`entry` is
  a price). Exits are plottable today; entry markers would need a new column and could
  never be backfilled, so markers mean exits.
- **C — News expanded view.** Week ahead, all impact levels, per-event symbol impact with
  countdown, filters. *Requires backend work:* `NewsManager.snapshot()` exposes only
  `next` (first HIGH) and `today` (today's HIGH). `store.events()` already holds the whole
  week at all impact levels — the data exists, the API does not send it.
- **D — Market-context strip redesign** (professional/institutional) **including the live
  text-overflow bug**: `SessionChip` has no `min-w-0`/`truncate`/`shrink-0`, so at
  `sm:grid-cols-4` inside a `2fr` column (~106px usable) it must render ~122px of content.
  Same class of bug in the overlap badge and `LocalityClock`'s `date · timezone` row. The
  4-column strip that exposed it arrived with the news-dashboard merge.
