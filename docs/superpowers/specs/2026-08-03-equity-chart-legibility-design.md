# Equity chart legibility — design (sub-project B1)

**Date:** 2026-08-03
**Status:** approved design, not yet implemented
**Scope:** make the equity panel readable — a legend, a high-water-mark line, a drawdown ramp
that means something, and a daily-breaker reference that is only drawn where it is true.

---

## 1. Why this exists, and why it is B1 rather than B

The operator's ask for sub-project B was "institutional-grade, with a key". That decomposes along a
hard backend seam:

- **B1 (this spec)** — legibility. Every input already exists in the API response or the snapshot.
  Pure frontend. Lands without touching Python.
- **B2 (later, own spec)** — trade analytics: exit markers and a range-linked analytics strip with a
  per-strategy breakdown, plus a coverage statement when the curve is shorter than the range. All of
  that needs one new backend endpoint returning trades-in-range, so it is deliberately not here.

Splitting this way means the chart becomes readable *before* more is drawn on top of it. The
alternative — markers first — adds information to a plot that cannot yet explain the three series it
already has.

The trigger is concrete. Sub-project A widened the maximized chart to 555px, and at that size the
drawdown overlay reads as a large red wash across the plot (it was subtle at 140px). Nothing on
screen tells the operator what that red is. There is **no `<Legend>` in `EquitySparkline.tsx` at
all** — three series are drawn and none is named.

## 2. Scope

**In scope:** a legend, a high-water-mark line, re-colouring drawdown with the A2 `--dd-*` ramp,
a daily-breaker reference line on intraday ranges, and moving drawdown into its own pane in the
maximized view.

**Explicitly NOT in scope:** trade exit markers, the analytics strip, the coverage statement, any
backend or Python change, series-toggling from the legend, and the coarse tier's `equity_min` /
`equity_max` envelope (fetched today, used by nothing — it stays unused).

## 3. What the data already gives us

Verified against the running system on 2026-08-03, not assumed:

- `src/ops/equity_recorder.py:48` defines the served series: `equity`, `balance`, `peak` (both
  tiers), plus `equity_min` / `equity_max` (coarse only).
- **`peak` is already fetched and already reaching the frontend.** `equityChartData.ts:87` reads it,
  but only to derive `drawdown = equity - peak`; it is never drawn. The high-water-mark line is
  therefore a display change, not a data change.
- `ChartRow` (`equityChartData.ts:3`) carries `ts / equity / balance / drawdown`. B1 adds `peak`.
- Drawdown is drawn as an `<Area>` on its own axis (`yAxisId="dd"`, hidden, domain `[ddFloor, 0]`),
  filled `hsl(var(--loss))` at `fillOpacity={0.18}`.
- The snapshot's risk block exposes `day_anchor`, `day_pnl`, `day_pnl_pct` and `max_daily_dd_pct`
  (`src/ops/web/state_view.py:112-131`) — **for today only.** No historical anchor is stored.
- A2 shipped `--dd-shallow: 358 40% 55%`, `--dd-moderate: 358 65% 60%`, `--dd-severe: 358 84% 64%`
  (identical to `--loss`), all bound as Tailwind colours.
- Ranges (`equity_view.py` `RANGES`): `15m 30m 1h 4h 12h 1d 1w 1mo 4mo 6mo 1y`.

## 4. The dual-axis problem, and the chosen fix

Equity and balance share the left axis in account currency. Drawdown has a **separate hidden axis**,
and that was a deliberate fix: on a shared axis a realistic drawdown (tens of units against an equity
in the hundreds) collapses to a 1–2px sliver pinned to the bottom edge — visible in source, invisible
on screen.

A legend over that as-is would be dishonest: four entries implying one scale, one of them measured
against an axis nobody can see. Three options were considered:

- **Grouped legend, single pane** — split entries into "Value" and "Risk". Cheapest, but labels the
  hidden axis rather than fixing it, and leaves the red wash over the plot.
- **Reveal the drawdown axis on the right** — honest, but crowds a 555px chart and still leaves the
  wash.
- **Underwater pane (chosen)** — drawdown moves out of the equity plot into its own short pane
  directly beneath, sharing the x-axis. This is the standard institutional underwater curve.

The underwater pane is chosen because it makes the legend honest **by construction**: each pane has
one axis and one meaning, so no label has to compensate for a hidden scale. It also removes the red
wash from the equity plot outright, and gives the A2 depth ramp somewhere it actually reads.

**Cost, accepted:** vertical space. The underwater pane therefore appears **only in the maximized
view**. The collapsed 140px card keeps exactly today's single-pane sparkline with the drawdown area
as-is. This matches the operator's stated use: analysis is a maximized-view job.

## 5. Equity pane

Unchanged except for one addition: a **high-water-mark line** drawn from `peak`, on the same left
axis as equity and balance (it is the same unit and the same scale, so no axis honesty problem).

Rendered as a thin line, visually subordinate to equity — it is a reference, not a series the
operator tracks moment to moment. It is monotonically non-decreasing within a window, so it reads as
a staircase above the equity area, and the gap between the two *is* the drawdown, which is exactly
the relationship the underwater pane then quantifies.

## 6. Underwater pane

Drawdown as depth below zero, sharing the equity pane's x-axis so timestamps line up.

**Colour is the A2 ramp keyed to how much of the daily breaker the drawdown has consumed** — not to
an absolute currency amount, which would mean nothing across accounts of different size:

| Fraction of `max_daily_dd_pct` consumed | Token |
|---|---|
| < 1/3 | `--dd-shallow` |
| 1/3 to 2/3 | `--dd-moderate` |
| > 2/3 | `--dd-severe` |

`--dd-severe` is byte-identical to `--loss`, so a deep drawdown and a losing P&L read as the same
red — deliberate, per the A2 spec.

The ramp selection is a **pure function of (drawdown, day_anchor, max_daily_dd_pct)** returning a
token name. That is the unit under test; the colour it resolves to is a browser concern.

When `max_daily_dd_pct` or `day_anchor` is unavailable (0.0, the documented default before the risk
manager has anchored), the ramp cannot be computed. It then falls back to `--dd-moderate` flat rather
than guessing a severity — the panel must never imply "shallow" when it does not know.

A **max-drawdown reference** for the visible window marks the deepest point reached. It lives in the
underwater pane, so it is maximized-only.

**The ramp applies to the collapsed card too.** What differs between the two views is the drawdown's
*placement* — its own pane when maximized, the existing in-plot area when collapsed — not its colour.
A 140px card showing severity at a glance is strictly better than one showing flat `--loss`, and
splitting the colour logic by view would mean two code paths and two things to keep in sync.

## 7. Daily breaker line

Drawn as a horizontal reference on the equity pane at `day_anchor × (1 − max_daily_dd_pct/100)`.

**It is drawn only on the intraday ranges `15m, 30m, 1h, 4h, 12h, 1d`, and is absent — legend entry
included — on `1w` and longer.** The anchor is a today-only value and no historical anchors are
stored, so drawing it across past days would invite reading old equity against a threshold that was
never in force then. An overlay that silently spans days it did not govern is the same failure as a
test that passes for the wrong reason: it looks like information and is not.

Its legend entry appears and disappears with it, so nothing dangles pointing at an invisible line.

## 8. Legend

One legend per pane. Each entry is a colour swatch plus a label: equity, balance, high-water mark,
and (intraday only) daily breaker on the equity pane; drawdown on the underwater pane.

**Not interactive.** No click-to-toggle series. Nobody asked for it, and a toggled-off series is a
new piece of hidden state that every screenshot and bug report then has to account for.

Swatches derive from the same tokens the series are drawn with, so a retune moves both together.

## 9. Collapsed vs maximized

| | Collapsed (140px) | Maximized (555px) |
|---|---|---|
| Equity + balance | yes | yes |
| High-water mark | yes | yes |
| Drawdown | in-plot area, as today | own underwater pane |
| Drawdown colour | A2 `--dd-*` ramp | A2 `--dd-*` ramp (same logic) |
| Legend | no | yes |
| Breaker line | no | intraday ranges only |
| Max-DD reference | no | yes |

The collapsed card stays a glanceable sparkline. Everything that needs reading room lives in the
view sub-project A built for exactly that.

The single-instance invariant from sub-project A still binds: only ONE chart is mounted at a time.
Testing Library's `getByTestId` throws on multiple matches, so a duplicated `equity-sparkline` breaks
unrelated existing tests — and doubles live chart work on every heartbeat.

## 10. Testing

jsdom computes no layout and resolves no colour, so no test may assert a Tailwind class string, a
hex, or a rendered colour. Every guard below names the mutation that turns it red.

| Guard | Mutation that breaks it |
|---|---|
| `peak` reaches `ChartRow` as a finite number, and is `null` (not `0`, not fabricated) when the source bucket is null | dropping `peak` from the row builder, or letting `null` coerce to a number |
| The ramp function returns `dd-shallow / dd-moderate / dd-severe` at the 1/3 and 2/3 boundaries | moving a threshold, or inverting the ramp |
| The ramp falls back to `--dd-moderate` when `max_daily_dd_pct` or `day_anchor` is 0 | returning `dd-shallow` for un-computable input |
| The breaker line and its legend entry are absent for `1w` and present for `1d` | widening the intraday set, or leaving the legend entry behind |
| The underwater pane renders only when maximized | rendering it in the collapsed card |
| Exactly one chart instance is mounted | reintroducing a second mounted chart |

The `equity - peak` derivation already has a hard-won guard in `equityChartData.ts:52-58` — a bucket
null for equity but numeric for peak would otherwise fabricate a full-equity drawdown and squash
every real drawdown into an invisible sliver. B1 must not weaken it.

**Browser pass (required).** Colour, layout and the pane split are only verifiable in a real browser.
Use the recipe proven in A and A2, which never touches the live bot: build `dist` in the worktree,
serve it with the fake-controller devserver on `TITAN_GUI_PORT=8899` / `TITAN_GUI_TOKEN`, drive it
with the `browse` skill, and confirm with `ss -tlnp` before and after that 8770 and 32768-9 remained
the bot's. Confirm: the two panes share an x-axis, the ramp is visibly distinct at different depths,
the high-water line reads as subordinate to equity, and the breaker line disappears on 1w.

⚠️ The devserver's fake controller reports equity 10,000 flat. The **real** account is ~457 against a
peak of 469.29 — about −2.6% drawdown. A browser pass against fake data proves layout and wiring, not
that the ramp picks sensible severities on real numbers; that is what the ramp's unit tests are for.

## 11. Risks

| Risk | Mitigation |
|---|---|
| The underwater pane eats reading room the equity curve needs | It is maximized-only; the collapsed card is unchanged |
| Two panes drift out of x-alignment | They share one x-axis domain, derived from the same rows |
| Ramp keyed to a breaker that is 0 before anchoring | Explicit fallback to `--dd-moderate`, tested |
| Breaker line read as historical on long ranges | Not drawn at all beyond `1d`, legend entry included |
| Legend implies one scale across two axes | Structurally impossible — one legend per pane, one axis per pane |
| A2's `--dd-*` tokens turn out indistinguishable on screen | Browser pass checks exactly this; tokens are one-line retunes in `tokens.css` |
