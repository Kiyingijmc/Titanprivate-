# Titan — Brand Identity Design Brief (prompt for claude.ai design tool)

> **Purpose:** paste the block below into claude.ai's design/artifact tool to generate the Titan
> visual identity (logo, wordmark, color, type, brand board). Bring the returned palette / wordmark /
> type pairing back into the repo as the concrete design tokens for the GUI redesign spec.
>
> **Established direction (2026-07-15 brainstorm):** ambition = *credibility showcase* (shown to
> investors / collaborators / prop firms); redesign depth = *rethink the design language*; name =
> keep **Titan**, refine it; personality = *modern premium fintech* (Linear/Stripe/Arc craft applied
> to trading); robustness = all four (complete UI states, responsive, real-data resilience, operator
> speed + a11y).
>
> **Two open levers to lock before/while generating:**
> 1. **Signature accent** — electric cyan-blue (safe, universally "trustworthy") vs. indigo/violet
>    (more ownable, less "every fintech is blue"). *Recommendation for a credibility piece: indigo/violet.*
> 2. **Mark concept** — T-monogram vs. precision/gyroscope vs. monolith. *Recommendation: precision/
>    gyroscope (ties to the quant arsenal, avoids clichés).*

---

You are a senior brand identity designer. Design a complete visual identity for **Titan**, and deliver it as a single self-contained interactive brand board (inline SVG + CSS, no external assets) plus clean, copyable SVG logo assets.

**What Titan is.** Titan is an *algorithmic trading control system* — a private, institutional-grade "cockpit" that runs and supervises automated trading strategies in real time: live positions & P&L, risk controls, a strategy registry, a live event feed, and system health. It is sophisticated quant / trading-operations software with a dark, data-dense operator dashboard.

**Audience & goal.** The identity is a *credibility signal* shown to serious audiences — investors, collaborators, prop firms. It must read as trustworthy, precise, and high-craft: the kind of tool a professional quant desk would run. Not a mass-market consumer app.

**Personality.** Modern premium fintech — the craft and restraint of Linear, Stripe, Arc, and Vercel, applied to trading. Confident, sleek, understated authority; precision over flash. "Titan" connotes strength, scale, and control — the identity should feel powerful but composed, never loud or clichéd.

**Name & wordmark.** Public name: **Titan** (drop any "ICT Bot" descriptor). Design a refined wordmark — a modern geometric / neo-grotesque sans, tight and confident, with one subtle distinctive detail (a custom letterform in the T or A, or a precise ligature). Premium and legible at small sizes. Also propose 2–3 short tagline/descriptor options (e.g. "Algorithmic Trading Control").

**Mark / symbol.** Design a standalone mark that works as an app icon and favicon, monochrome-friendly and crisp at 16px. Explore 2–3 distinct concepts and AVOID trading clichés (bulls, bears, candlesticks, arrows, coins). Directions to consider: (1) a geometric **"T" monogram** with an architectural/structural quality — titan as colossal pillar/monolith: strength, stability, foundation; (2) an abstract **precision/control mark** evoking an axis, gyroscope, or signal node (Titan's strategies are named after instruments like a Kalman "Gyroscope") — a modular geometric form suggesting equilibrium and control; (3) a **monolithic titan silhouette** abstracted to pure geometry — imposing but minimal. Recommend one as primary and explain why.

**Color.** Dark-first. A near-black, slightly cool base (deep slate/charcoal, not pure black), premium neutrals (steel/graphite), and one confident signature accent. Explore two accent directions and recommend one: (a) a refined **electric cyan-blue** (techy, trustworthy, "signal") or (b) a distinctive **indigo/violet** (premium, less common in trading = more ownable). Keep functional **green = profit/up** and **red = loss/down** as reserved semantic colors — never use the signature accent for P&L. Deliver the full palette as hex tokens: background, surfaces, borders, text (primary/secondary/muted), signature accent + tints, and semantic profit/loss/warning/info.

**Typography.** Propose a pairing: a premium UI sans (e.g. Inter / Geist / a Söhne-like grotesque) plus a technical **monospace** for numbers, prices, and data (tabular figures — essential for a trading UI). Give the wordmark its own treatment if it differs.

**Deliverables (in the brand board).** (1) Primary logo lockup (mark + wordmark), plus mark-only and wordmark-only; (2) app icon / favicon, square, working 16–512px, monochrome + reversed versions; (3) full color palette with hex + roles; (4) type system (families, weights, a sample scale, and a tabular-number sample); (5) 2–3 in-context applications — an app icon, a login/access screen, and a dark dashboard header using the identity; (6) a one-line rationale for the primary logo and the accent choice.

**Format & constraints.** Output a single self-contained HTML brand board (inline SVG + CSS) I can view, plus the logo as clean inline SVG I can copy. Everything must render on a dark background and hold up in monochrome and at small sizes. Restraint over decoration — no stock icons, no gratuitous gradients, no clichés. Show the 2–3 mark concepts, then commit to a recommended primary.

---

## When the design comes back

Bring these values into the repo so they become the redesign's design tokens:

- [ ] Signature accent hex (+ tints) and the final semantic profit/loss/warning/info hexes
- [ ] Background / surface / border / text (primary/secondary/muted) hexes
- [ ] Wordmark + mark as inline SVG (for the app header, token gate, favicon)
- [ ] UI sans + monospace family names (self-hostable — the app is CSP/offline, no font CDN)
- [ ] The chosen tagline/descriptor (if any)

These replace the placeholder tokens in the GUI redesign design system
(`docs/superpowers/specs/2026-07-15-titan-gui-redesign-design.md` §7).
