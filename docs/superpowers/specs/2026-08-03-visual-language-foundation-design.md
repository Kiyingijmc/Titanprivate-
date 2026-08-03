# Visual language foundation — design (sub-project A2)

**Date:** 2026-08-03
**Status:** approved design, not yet implemented
**Scope:** the semantic colour vocabulary that sub-projects B, C and D all consume, plus a
retune of the surface neutrals so panels stop reading as flat grey.

---

## 1. Why this exists, and why it comes first

The operator asked for colour on the dashboard panels. That request spans three later
sub-projects: B (equity chart), C (news expanded view) and D (market-context strip). If
each invents its own colour, the dashboard ends up incoherent — three reds that mean three
different things.

There is already evidence of exactly that drift: `SESSION_COLORS` in
`frontend/src/components/market/MarketSessions.tsx:41-44` is four raw hex literals living
in a component, the only colour in the app outside the token system. Meanwhile news
`importance` — which the backend already sends — renders as **plain text** with no colour
at all (`NewsPanel.tsx:81`), and drawdown reuses `--loss` flat, which is why it became a
large red wash once the chart grew to 555px in sub-project A.

A2 defines the vocabulary once. B, C and D consume it.

## 2. Scope

**In scope:** new tokens in `frontend/src/design/tokens.css`, their bindings in
`frontend/tailwind.config.ts`, the surface retune, and moving `SESSION_COLORS` into tokens.

**Explicitly NOT in scope:** *applying* the new colours. Impact chips are C, the drawdown
ramp is B, the strip is D. A2's only visible change is the warmed surfaces and the domain
tints on panel headers.

Deliberate consequence: after A2, `--impact-*` and `--dd-*` exist but nothing references
them yet. That is intended, not dead code — B and C land immediately after.

## 3. Surface retune

Current neutrals are cool slate (hue 220-225). They keep their **exact lightness ladder**
so every existing contrast ratio is unchanged; only hue and saturation move, toward the
brand violet (hue 252).

| Token | Now | A2 |
|---|---|---|
| `--bg` | `225 20% 8%` | `240 18% 8%` |
| `--surface-1` | `223 19% 15%` | `240 16% 15%` |
| `--surface-2` | `222 16% 21%` | `240 14% 21%` |
| `--elevated` | `220 17% 24%` | `240 14% 24%` |
| `--border` | `222 16% 21%` | `240 14% 21%` |
| `--border-strong` | `221 16% 27%` | `240 14% 27%` |

**Naming honesty:** this is "warm" in the sense of *less clinical*, not literally warmer
(orange). On a dark UI with a violet accent, tinting the neutrals toward the accent hue is
what makes surfaces read as intentional; true orange-tinted greys would fight the violet.
If the operator wants literal warmth instead, the same lightness ladder can be re-hued to
~25 — a one-line change per token, which is the point of doing this in one file.

Text tokens (`--text-primary/secondary/muted`) are untouched.

## 4. Domain tints

Four hues so a section is identifiable at a glance. Used at low alpha on a panel's header
background and at full strength on a 2px left border.

```
--domain-risk:       20 70% 55%    /* risk engine, exposure, breaker */
--domain-market:    200 70% 55%    /* sessions, clock, dollar, calendar */
--domain-execution: 252 83% 65%    /* controls, positions, orders — the brand accent */
--domain-analytics: 160 60% 50%    /* equity, research, journal */
--tint-weak:  0.07                 /* header wash */
--tint-strong: 0.16                /* active/selected wash */
```

The alphas are tokens too, so "how strong is a tint" is one decision, not a number
scattered across components.

## 5. News impact levels

```
--impact-high:   10 85% 56%
--impact-medium: 32 90% 55%
--impact-low:    48 75% 55%
```

🔴 **Colour is never the only channel for impact.** `--impact-high` (hue 10) and `--loss`
(hue 358) are only ~12° apart — deliberately, because both want to be red by convention —
so on a trading screen "high-impact release" and "losing money" could otherwise be
confused at a glance, and would be indistinguishable to a red-green colour-blind operator.
Every impact indicator C builds MUST also carry its text label (High / Med / Low). Colour
is redundant encoding, not the carrier.

## 6. Drawdown severity

Replaces the flat `--loss` wash with a ramp keyed to distance from the 3% daily breaker
(`risk.account.max_daily_dd_pct`), converging on `--loss` at the severe end:

```
--dd-shallow:  358 40% 55%     /* < 1/3 of the cap */
--dd-moderate: 358 65% 60%     /* 1/3 to 2/3 */
--dd-severe:   358 84% 64%     /* > 2/3 — identical to --loss */
```

B decides the thresholds and applies them; A2 only names the colours.

## 7. Session colours

The four hex literals move out of `MarketSessions.tsx` into tokens, converted faithfully to
HSL so there is **zero visual change** — D retunes them later if it wants.

```
--session-sydney:   38 92% 50%    /* was #F59E0B */
--session-tokyo:   348 95% 67%    /* was #FB5C7D */
--session-london:  247 87% 73%    /* was #8B7CF6 */
--session-newyork: 164 66% 50%    /* was #2DD4A7 */
```

`MarketSessions` reads them via `hsl(var(--session-<id>))`. Its `BAND_ALPHA = "B3"` hex
suffix trick stops working on an HSL variable, so the band opacity moves to a real alpha
channel — a mechanical change, same rendered result.

## 8. Status tints

No new colours: `stale` reuses `--warning`, `error` reuses `--loss`, both at `--tint-weak`
on the panel surface. This keeps "something is wrong" to one vocabulary rather than
inventing a second yellow.

## 9. Binding — the trap this project has already hit

Every token ships **defined in `tokens.css` AND bound in `tailwind.config.ts`** in the same
change. The GUI motion foundation on this codebase shipped tokens bound to *nothing*: valid
CSS, referenced by no utility, silently dead. Colour has the identical failure mode.

## 10. Testing

One guard that actually bites: a test that reads `tokens.css` and `tailwind.config.ts` and
asserts every new token is **both defined and bound**. Deleting either half turns it red.

Plus a contrast assertion that `--text-primary` on each retuned surface still clears WCAG
AA (4.5:1), computed from the token values — this is what makes the "lightness ladder
unchanged" claim in §3 checkable rather than asserted.

**Not tested:** no test asserting a hex equals itself, and no test asserting a Tailwind
class string appears in a component. jsdom computes no layout and those guards cannot fail;
this repo has been bitten by that twice. Visual confirmation is a browser pass, using the
A-verified recipe (build the dist, serve it with the fake-controller devserver on
`TITAN_GUI_PORT=8899`, never the live bot's 8770).

## 11. Risks

| Risk | Mitigation |
|---|---|
| Retune quietly breaks contrast somewhere | Lightness ladder held identical; contrast test computes it |
| Tokens defined but unbound (motion's bug) | §10 guard fails if either half is missing |
| Impact red confused with P&L red | §5: text label always accompanies colour |
| Session colours shift during the move | Faithful HSL conversion; the band-alpha change is mechanical |
| A2 lands with unused tokens | Intended — B and C consume them next; stated in §2 |
