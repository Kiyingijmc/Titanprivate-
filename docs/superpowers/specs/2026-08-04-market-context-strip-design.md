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

## 4. Proportions — content-driven, not hand-tuned

The obvious fix is to re-guess the fractions (`2.6fr 1fr 1fr 0.8fr`). **Do not do that.** Fractions
tuned by eye at one width are exactly how the current strip arrived at zero slack: they encode one
viewport's arithmetic as if it were a rule, and they silently stop being right when a font, a label
or a breakpoint changes.

Size the cards by what their content actually needs, and give the remainder to the one card whose
content is elastic:

```
lg:grid-cols-[minmax(0,1fr)_max-content_max-content_minmax(0,0.8fr)]
```

- **Local Time** and **Dollar Bias** are `max-content`: their content has a definite natural width
  (a clock, a bias figure, four pair chips) and they should take exactly that, no more.
- **Market Sessions** is `minmax(0,1fr)` — elastic. It absorbs whatever is left, so it is never the
  card that runs out of room. This is the inversion that matters: today the starved card is the one
  with the most content.
- **Economic Calendar** is capped at `0.8fr` and yields first, per the owner decision. It renders
  "unavailable" almost always, and sub-project C rebuilds it regardless.

The `minmax(0, …)` wrappers are load-bearing, not decoration: a bare `1fr` has a `min-width: auto`
floor equal to its content, which is what lets a grid child refuse to shrink and overflow its track.

**The exact track list is not a contract — §7's zero-overflow measurement is.** If a different
sizing achieves it across all three widths, that is fine; if these tracks fail at any width, they
are wrong and must change.

## 5. The other three cards

These need overflow primitives, not redesign:

- **LocalityClock** — `whitespace-nowrap` on the date so `Tue, Aug 4` cannot split, and
  `min-w-0` + `truncate` on the timezone so it degrades to `Africa/Kamp…` rather than orphaning
  the date's digits.
- **DollarBias** — `min-w-0` + `truncate` on the "+5.5 USD STRONG" label.
- **Panel titles** — `truncate` on the card headers so "ECONOMIC CALENDAR" stays on one line.

The `shrink-0` primitive belongs on any element that must never compress — status dots, icons.

**Truncation must not destroy information.** Every element that can truncate carries a `title`
attribute with its full text, so the operator can recover it on hover. A truncated timezone with no
way to read it is a smaller bug than an orphaned date, but it is still a bug — and `title` costs one
attribute. This applies to the timezone, the bias label, and any panel title.

## 6. Responsive behaviour, and content this design has not seen

The strip is a single row from the `lg` breakpoint up and already stacks below it; that stays.

The chip's internal layout is identical at every width (§3), so the only responsive concern is the
chip grid inside the sessions card. It currently hard-codes `grid-cols-2 sm:grid-cols-4` — two
breakpoints chosen for a chip whose width is about to change.

Replace them with intrinsic reflow:

```
grid-cols-[repeat(auto-fit,minmax(6rem,1fr))]
```

The chips then wrap when they genuinely run out of room rather than when a viewport crosses a number
someone guessed. `6rem` (~96px) is the stacked chip's real floor: "New York" (~62px) plus the `px-3`
padding (24px) plus the left border. This survives a font change, a sidebar-collapse, and a card
being added to the strip — none of which a fixed breakpoint survives.

**Degradation for strings this design has not seen.** Today's data is narrow: four fixed session
names, countdowns under 24h, one timezone. The design must not assume that:

| Unseen input | Required behaviour |
|---|---|
| A longer timezone (`America/Argentina/Buenos_Aires`) | truncates with `title`; never wraps the date |
| A 3-digit countdown, or `0m` | renders on one line; the pill grows, the chip does not break |
| A longer session name, or a fifth session | the `auto-fit` grid reflows; no chip clips |
| A missing/None session clock | the clock row is omitted, not rendered blank or `--:--:--` |

These are the cases §7's worst-case fixtures pin.

## 7. Testing

jsdom computes no layout, so **no test may assert a width, a pixel value, or that text fits** —
such a test passes regardless of the behaviour. This project has been bitten by exactly that four
times across A2 and B1.

### 7.1 Test the worst case, not today's clock

`sessionStates()` runs off the wall clock, so a test that renders "whatever is on screen now" pins
nothing: it passes at 03:00 and fails at 14:00, or vice versa, and it never exercises the strings
that actually break the layout. **Every test supplies an explicit `now` and worst-case fixture
strings** — the mechanism already exists, `MarketSessions` accepts a `now` prop for exactly this.

The worst case is not today's data:

| Element | Today | Worst case to pin |
|---|---|---|
| Session name | "New York" | the longest name in `SESSIONS` — derive it, do not hard-code |
| Countdown | `2h 38m` | `23h 59m` (max `fmtCountdown` output) |
| Open status | `Open` | `Open · 23h 59m` |
| Timezone | `Africa/Kampala` | `America/Argentina/Buenos_Aires` |

Deriving the longest name from the `SESSIONS` table rather than hard-coding "New York" means adding
a fifth session automatically extends the guard instead of silently leaving it stale.

### 7.2 Structural guards

| Guard | Mutation that turns it red |
|---|---|
| An open chip renders a clock row; a closed chip does not | rendering the clock unconditionally, or dropping it entirely |
| An open chip's status carries the closes-in countdown, not a bare "Open" | reverting to the hardcoded string |
| A closed chip's status is the opens-in countdown | swapping the open/closed branches |
| Both states render at a pinned `now` where one session is open and one is not | a fixture where every session happens to be closed — which would make the open-chip assertions vacuous |
| Truncatable elements carry a `title` with the full text | dropping the attribute, silently losing information |
| The date and timezone are separate elements | merging them into one string, which is what allows the date to split |

Asserting a Tailwind class string is forbidden and cannot fail meaningfully in jsdom — assert on
rendered structure and attributes, which are real state, and leave fit to the browser pass.

### 7.3 Browser pass — the real gate, and it must be repeatable

Re-run the exact measurement that found this bug: for every session chip, compare each row's summed
child `scrollWidth` against the row's `clientWidth`. **Zero overflow required at 1920, 1440 and
1280.**

**Commit the measurement as a script**, not a one-off console paste. This bug shipped and survived
in production precisely because checking for it was manual, and anything manual is skipped when
someone is in a hurry. A committed script under `frontend/scripts/` that any future session can
point at a running devserver turns "did anyone check?" into a command — and it is the only artifact
of this sub-project that keeps paying after D lands.

The script asserts, per chip and per card: no element's `scrollWidth` exceeds its `clientWidth`, and
no single-line row exceeds ~24px tall (the wrap tell that caught "New York" at 40px).

Also confirm by eye: no clock clipped mid-digit, the date reads `Tue, Aug 4 · Africa/Kampala`
unbroken, and the open session is distinguishable at a glance.

Use the recipe proven in A, A2 and B1 — build `dist` in a worktree, serve it with the
fake-controller devserver on `TITAN_GUI_PORT=8899`, and confirm with `ss -tlnp` before and after
that 8770 and 32768-9 remained the live bot's.

⚠️ Which session is open depends on when the pass runs. Verify **both** states — drive
`MarketSessions`' `now` prop rather than waiting for the clock.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Stacking makes chips taller and the strip grows | Chips gain one row only when open; closed chips are the same height as today |
| The closes-in countdown is wrong or confusing | It is already computed and tested in `sessions.ts`; this only surfaces it |
| New proportions break a different width | §7.3 measures three widths, not one, and the sizing is content-driven rather than tuned to one viewport |
| Truncation hides information the operator needs | Only the timezone truncates, and §5 requires a `title` carrying the full text |
| A test asserts a width and passes vacuously | §7 forbids it explicitly; guards are structural, fit is browser-verified |
| Tests pass at one time of day and fail at another | §7.1 requires an explicit pinned `now` in every test |
| Guards go stale when a session is added | §7.1 derives the longest name from `SESSIONS` instead of hard-coding it |
| This regresses later and nobody notices | §7.3's committed measurement script makes the check a command, not a memory |

## 9. What this deliberately does not do

- **It does not rebuild the Economic Calendar.** That is sub-project C and needs backend work; D only
  narrows the card.
- **It does not add a second row.** The owner chose to shrink the calendar rather than grow the
  strip's height, which is real estate on a 1440 laptop.
- **It does not touch the session timeline band**, the sessions engine, or any Python.
- **It does not introduce a shared "OverflowSafe" wrapper component.** Four cards needing the same
  three utility classes is not yet an abstraction worth having; revisit if a fifth arrives.
