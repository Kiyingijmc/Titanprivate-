# Market-context strip redesign — design (sub-project D)

**Date:** 2026-08-04
**Status:** approved design, not yet implemented
**Scope:** re-proportion the market-context strip and fix the text overflow that currently
truncates every card in it.

---

## 1. Why this exists

The operator reported "the session clocks overflow". Measured in a real browser at 1440px, the
problem is larger than that: **every card in the strip overflows, and the session chips clip their
clocks mid-digit.**

Measurements taken 2026-08-04 against the running dashboard (devserver on `TITAN_GUI_PORT=8899`,
viewport 1440×900), not estimated:

| Chip | Row width available | Content needs | Overflow |
|---|---|---|---|
| Sydney | 53px | 115px | 62px |
| Tokyo | 53px | 103px | 50px |
| London | 53px | 114px | 61px |
| New York | 53px | 93px | 40px |

On screen this renders as `Sydney 19`, `Tokyo 18:2`, `London 10` — the live clock cut off
mid-digit — and "New York" wrapped onto two lines (its label row measures 40px tall against a
~20px single line).

It is not width-specific. The New York chip wraps at **1920, 1440, 1280 and 1024**. At 1920 it
needs exactly 117px in a 117px row: zero slack.

Nor is it confined to the session chips. `LocalityClock` renders its date as
`Tue, Aug · Africa/Kampala 4` — the `4` orphaned onto another line, so the date reads as broken.
The "ECONOMIC CALENDAR" title wraps to two lines, and Dollar Bias's "+5.5 USD STRONG" wraps.

**Root cause:** four cards share one row in a `2fr 1fr 1fr 1fr` grid, and every one of them sits
within a few pixels of its content's natural width. The strip has no slack anywhere, so it all
breaks at once. Inside the sessions card, `SessionChip` compounds this by placing the name and the
clock in a `justify-between` row — two items competing horizontally for 53px.

## 2. Scope

**In scope:** re-proportioning the strip's grid, restructuring `SessionChip`'s internal layout, and
adding the missing overflow primitives (`min-w-0` / `truncate` / `whitespace-nowrap` / `shrink-0`)
across all four cards.

**Explicitly NOT in scope:** rebuilding the Economic Calendar (that is sub-project C, which needs
backend work), changing what data the strip fetches, any Python change, and any change to the
session timeline band above the chips.

## 3. The core fix: stop competing horizontally

`SessionChip` currently puts the name and clock side by side:

```
[ New York          05:20:40 ]     ← needs 118px in a 53px row
[ Opens in 2h 38m            ]
```

It becomes a vertical stack:

```
New York            ← name
05:20:40            ← live clock — OPEN sessions only
● Open · 3h 12m     ← status
```

Closed sessions omit the clock row entirely and read `Opens in 11h 38m`.

Each row then needs only the width of its widest single element (~62px for "New York") instead of
the sum of two (~118px). **The overflow dissolves rather than being truncated away**, and because
the fix is width-independent it needs no responsive reflow of the chip's internals — which is what
makes supporting both laptop and desktop cheap.

Two deliberate consequences:

**The open session gains visual weight** — three rows against two — satisfying "open sessions
should have the clocks active and visible" without resorting to colour or size tricks.

**The discarded closes-in countdown is surfaced.** `sessions.ts:127` already computes
`Open · closes in ${fmtCountdown(...)}` for open sessions, and `SessionChip` throws it away in
favour of a hardcoded `"Open"`. Knowing London closes in 3h12m is more actionable than knowing the
wall-clock time there. Shortened to `Open · 3h 12m` (~80px) it fits the stacked layout.

## 4. Proportions

The grid changes from `minmax(0,2fr) minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)` to approximately
`minmax(0,2.6fr) minmax(0,1fr) minmax(0,1fr) minmax(0,0.8fr)`.

Sessions gains ~90px (370 → ~460 at 1440); Economic Calendar drops to ~180px. The calendar yields
first because it renders "Economic calendar unavailable" almost all the time, and sub-project C
rebuilds it regardless — shrinking the card that is showing nothing costs least.

The exact fractions are a starting point, not a contract. The binding requirement is §7's
zero-overflow measurement; if a different ratio achieves it, that is fine.

## 5. The other three cards

These need overflow primitives, not redesign:

- **LocalityClock** — `whitespace-nowrap` on the date so `Tue, Aug 4` cannot split, and
  `min-w-0` + `truncate` on the timezone so it degrades to `Africa/Kamp…` rather than orphaning
  the date's digits.
- **DollarBias** — `min-w-0` + `truncate` on the "+5.5 USD STRONG" label.
- **Panel titles** — `truncate` on the card headers so "ECONOMIC CALENDAR" stays on one line.

The `shrink-0` primitive belongs on any element that must never compress — status dots, icons.

## 6. Responsive behaviour

The strip is a single row from the `lg` breakpoint up and already stacks below it; that stays.

The chip's internal layout is identical at every width (§3), so the only responsive concern is the
4-across chip grid inside the sessions card. It already declares `grid-cols-2 sm:grid-cols-4`. With
the extra width from §4 and the stacked chip, 4-across holds at 1280 and above; the existing 2×2
fallback covers narrower.

## 7. Testing

jsdom computes no layout, so **no test may assert a width, a pixel value, or that text fits** —
such a test passes regardless of the behaviour. This project has been bitten by exactly that.

Falsifiable structural guards:

| Guard | Mutation that turns it red |
|---|---|
| An open chip renders a clock row; a closed chip does not | rendering the clock unconditionally, or dropping it entirely |
| An open chip's status carries the closes-in countdown, not a bare "Open" | reverting to the hardcoded string |
| A closed chip's status is the opens-in countdown | swapping the open/closed branches |
| The date element carries `whitespace-nowrap` — asserted via the rendered element, not a class string | removing the primitive |

The last one needs care: asserting a Tailwind class string is forbidden and cannot fail meaningfully
in jsdom. Assert instead on rendered structure — that the date and timezone are separate elements
with the timezone independently truncatable — and leave the visual proof to the browser pass.

**Browser pass (required, and it is the real gate).** Re-run the exact measurement that found this
bug: for every session chip, compare each row's summed child `scrollWidth` against the row's
`clientWidth`, at **1920, 1440 and 1280**. The requirement is **zero overflow at all three**. Also
confirm: no clock is clipped mid-digit, "New York" occupies one line (its label row ~20px, not
40px), the date reads `Tue, Aug 4 · Africa/Kampala` unbroken, and the open session is
distinguishable from the closed ones at a glance.

Use the recipe proven in A, A2 and B1 — build `dist` in a worktree, serve it with the
fake-controller devserver on `TITAN_GUI_PORT=8899`, and confirm with `ss -tlnp` before and after
that 8770 and 32768-9 remained the live bot's.

⚠️ The fake controller's session data is real (`sessionStates()` runs off the wall clock), so the
open/closed split is genuine — but which session is open depends on when the pass runs. Verify both
states, forcing a session open by shifting the clock if necessary rather than waiting.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Stacking makes chips taller and the strip grows | Chips gain one row only when open; closed chips are the same height as today |
| The closes-in countdown is wrong or confusing | It is already computed and tested in `sessions.ts`; this only surfaces it |
| New proportions break a different width | §7 measures three widths, not one |
| Truncation hides information the operator needs | Only the timezone truncates; every other element gets enough width to render fully |
| A test asserts a width and passes vacuously | §7 forbids it explicitly; guards are structural, fit is browser-verified |
