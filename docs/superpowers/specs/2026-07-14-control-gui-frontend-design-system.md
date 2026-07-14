# Titan Control GUI — Frontend Design System (Phase 1b)

**Date:** 2026-07-14
**Status:** Design-system reference for the Phase 1b frontend plan (CITE THIS in every component task).
**Derived from:** `ui-ux-pro-max` (design-system + dark fintech palette + typography) and `dataviz`
(chart forms, color-by-job, validator). Product type = **admin/operator real-time trading cockpit**,
dark-mode-only. Stack = **Vite + React + Tailwind + shadcn/ui + Recharts**, TypeScript.

This document is the single source of truth for style, palette, typography, spacing, and chart specs.
Implementer subagents building components MUST match these tokens; do not invent colors or fonts.

---

## 1. Aesthetic & style

- **Style:** Dark-mode "cockpit" (OLED-friendly), data-dense but scannable, minimal chrome, high contrast.
  Flat surfaces with subtle elevation (card border + faint shadow), no glassmorphism/gradients that
  obscure data. Status is communicated by **color + icon + text**, never color alone.
- **Density:** Compact. This is an operator tool, not a marketing page — favor tabular rows, tight
  vertical rhythm, and at-a-glance KPIs over whitespace-heavy hero layouts.
- **Layout:** Left sidebar/tab rail (Cockpit / Strategies / Settings; Research + Journal tabs scaffolded,
  empty until Phase 2). Top health strip spanning the content width. Desktop-first (operator on a
  laptop/desktop), but responsive down to a tablet; no horizontal body scroll — wide tables/charts
  scroll inside their own `overflow-x:auto` container.
- **Icons:** Lucide (SVG) only — never emoji. One icon family, consistent stroke width (2px), 20–24px.

## 2. Color tokens (dark surface — the only theme)

Define as CSS custom properties / Tailwind theme tokens; reference by role, never raw hex in components.

| Role | Hex | Use |
|------|-----|-----|
| `--bg` (background) | `#0F172A` | app background (slate-900) |
| `--surface` (card) | `#222735` | cards, tables, panels |
| `--surface-2` | `#272F42` | muted rows, table header, input bg |
| `--border` | `#334155` | card/table borders, dividers |
| `--text` (foreground) | `#F8FAFC` | primary text |
| `--text-muted` | `#94A3B8` | secondary text, labels, axis/gridline ink |
| `--primary` | `#3987E5` | primary actions, links, focus ring, the equity line (dataviz dark series-1) |
| `--on-primary` | `#FFFFFF` | text on primary |

**Semantic / status palette (reserved — always paired with a Lucide icon + text label, never color-alone):**

| State | Hex | Meaning |
|-------|-----|---------|
| profit / up / BUY | `#22C55E` (green-500) | positive PnL, buy side, healthy/connected |
| loss / down / SELL | `#EF4444` (red-500) | negative PnL, sell side, destructive actions (closeall/panic), errors |
| warning / paused / throttle-active | `#F59E0B` (amber-500) | system paused, drawdown throttle engaged, restart-required badge |
| info / neutral | `#38BDF8` (sky-400) | informational chips, "live" status |
| blocked (event-feed rule chips) | `#A78BFA` (violet-400) | IntentBlocked rule chips (opposition / ttl-dedup / cap) — chip carries the rule text |

Contrast: all status colors pass ≥3:1 vs the dark surfaces (dataviz validator) and are always
accompanied by a text label, so they satisfy `color-not-only`. Destructive actions use the loss-red
and are visually separated from primary actions (confirm dialogs).

## 3. Typography

- **Body / UI:** **Fira Sans** (300/400/500/600/700). 16px base, line-height 1.5.
- **Headings / mono / numbers:** **Fira Code** (400–700) for headings, and **tabular figures**
  everywhere numbers align in columns (prices, PnL, lots, timers, equity axis) — prevents layout shift
  (`font-variant-numeric: tabular-nums`).
- Self-host the fonts (CSP/offline — no external font CDN); ship woff2 in `frontend/src/assets/fonts/`
  and `@font-face` them, `font-display: swap`. (The app is served same-origin from the FastAPI server.)
- Type scale: 12 / 14 / 16 / 18 / 24 / 32. Weight hierarchy: headings 600–700, body 400, labels 500.

## 4. Spacing, shape, motion

- **Spacing:** 4/8px rhythm. Section gaps 16/24/32. Card padding 16px. Table row height ≥40px.
- **Radius:** 8px cards/inputs/buttons (shadcn default), 6px chips/badges.
- **Elevation:** 1px `--border` + subtle shadow on cards; modals/dialogs use a 50% black scrim.
- **Motion:** 150–300ms ease-out on hover/state/dialog transitions; transform/opacity only. Respect
  `prefers-reduced-motion` (freeze the live-feed auto-scroll + any chart entrance animation).
- **Interaction states:** every clickable element has hover + focus-visible (2px `--primary` ring) +
  disabled (opacity 0.5, no pointer) states. Touch/hit targets ≥40px.

## 5. Charts (dataviz — READ `dataviz` before writing any chart code)

**Form first — most of these tiles are NOT charts:**

- **Stat tiles** (balance, equity, day-PnL, open positions, arbiter approved/blocked, throttle mult):
  single headline numbers → **hero-number stat tiles, not charts**. Day-PnL number is colored by sign
  (green/red) **with an up/down arrow icon** (color-not-alone). Tabular figures.
- **Equity / PnL over time:** **single-series line or area chart** (Recharts `<LineChart>`/`<AreaChart>`).
  - Single series ⇒ **no legend** (the tile title names it); line = `--primary` `#3987E5`, 2px stroke,
    area fill ~15% opacity of the same hue.
  - **One axis only** — never dual-axis. If both balance and equity are shown, they share the PnL scale
    → 2 series (dark series-1 `#3987E5` blue + series-2 `#199E70` aqua, a dataviz-validated CVD-safe
    pair) WITH a legend + direct labels.
  - Recessive grid/axes in `--text-muted` at low opacity; **crosshair + tooltip on hover** (default for
    line/area); tooltip shows exact timestamp + value. Reduced-motion: no entrance animation.
  - Sparkline variant (compact, inside a stat tile): same single line, no axes/grid, no legend.
- **Empty/loading states:** skeleton shimmer while loading; "No data yet" message (not a blank axis)
  when empty; error → message + retry, never a broken chart.
- Text (labels/values/legends) wears **text tokens**, never the series color.
- Do NOT run the categorical validator for the single-series equity chart; if a genuine multi-series
  chart is added, run `dataviz/scripts/validate_palette.js "<hex,…>" --mode dark` first.

## 6. Component patterns (shadcn/ui)

- **Health strip:** horizontal row of status pills (bridge connected/stale, heartbeat age, paused,
  throttle-active) — pill = dot(status color) + Lucide icon + label. Throttle-active pill shows the
  current multiplier.
- **Positions table:** shadcn `Table`; columns ticket/symbol/side(BUY green / SELL red chip)/lots/entry/
  sl/tp/pnl(green/red)/grade/strategy. Tabular figures. Sortable where useful. Per-row close button
  (confirm dialog).
- **Event feed:** virtualized/append list of `{topic, ts, …}`; IntentBlocked rows render the rule as a
  **violet chip** (`opposition`/`ttl-dedup`/`cap`) + detail. Auto-scroll with pause-on-hover; respects
  reduced-motion. aria-live="polite" for new critical events.
- **Controls:** button group pause/resume/close/closeall/panic. Destructive (closeall/panic) = red,
  separated, open a **confirm `AlertDialog`** (panic/closeall require explicit confirm — mirrors the
  backend confirm-gate; closeall/panic POST with `confirm:true`).
- **Strategies tab:** registry `Table` with status badges (live=info, research=amber, active=green);
  enable/disable buttons; **promote** opens a dialog requiring the operator to **type the strategy id**
  (mirrors backend typed-id confirm → POST `{confirm:"<id>"}`); research rows visually distinct (amber
  left-border).
- **Settings tab:** rows with **source badge** (default/override) + **tier badge** (live = green,
  restart = amber "restart-required"); editable control per key; on PATCH, inline **422** error under
  the field; success toast; restart-tier changes show a "takes effect on restart" note.
- **Read-only mode:** when `/api/state` or a probe indicates read-only (or the token is a read-only
  token → mutating routes 403), **grey out and disable ALL mutating controls** (buttons, toggles,
  settings inputs, promote/enable/disable) with a visible "read-only" banner; reads stay live.

## 7. Data layer

- **WS hook** (`useLiveState`): connect `/ws`, send the token as the **first frame** within 3s; on
  `{type:"state"}` seed the snapshot, on `{type:"event"}` append to the feed. **Auto-reconnect** with
  backoff; on disconnect fall back to polling `GET /api/state` on the heartbeat cadence. Token stored in
  memory (entered once), never in the URL.
- All REST calls send `Authorization: Bearer <token>`; 401 → re-prompt for token; 429 → show throttle
  backoff message; 403 on a mutation → surface read-only.
- Served **same-origin** from the FastAPI server (`frontend/dist/` mounted by the Phase 1a server), so
  API base is relative (`/api`, `/ws`) — no CORS, no external hosts (CSP-friendly, self-contained).

## 8. Accessibility & quality gates (from ui-ux-pro-max §1–3)

- Contrast ≥4.5:1 body text / ≥3:1 large & UI glyphs on every surface (dark validated).
- focus-visible rings everywhere; full keyboard nav; dialogs trap focus + Escape to close.
- Color never the sole signal (status = color+icon+text).
- `prefers-reduced-motion` respected. No layout shift (tabular figures, reserved chart space).
- No emoji icons; Lucide SVG only. Self-hosted fonts (no external CDN).
