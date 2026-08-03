# Visual Language Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the dashboard's semantic colour vocabulary once — impact levels, drawdown severity, domain tints, session colours — and retune the surface neutrals so panels stop reading as flat grey.

**Architecture:** All colour lives in `frontend/src/design/tokens.css` as HSL triples and is bound to Tailwind utilities in `frontend/tailwind.config.ts`. A compile-based guard test proves each token both exists and *emits real CSS*, and a contrast test proves the surface retune preserved legibility.

**Tech Stack:** CSS custom properties, Tailwind 3 (`theme.extend.colors`), Vitest, PostCSS (already a dev dependency, used by the existing `motion.test.ts`).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-03-visual-language-foundation-design.md`. Read it before starting.
- Working directory for every command is `frontend/`. Put Node on PATH first: `export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"`.
- Run one test file with `npx vitest run <path>`; everything with `npm test`; type-check/build with `npm run build`.
- `node_modules` already exists. Do NOT run `npm install`/`npm ci`.
- tsconfig has `noUnusedLocals: true` / `noUnusedParameters: true` — unused imports are build errors.
- **Every token ships DEFINED in `tokens.css` AND BOUND in `tailwind.config.ts` in the same task.** The GUI motion foundation on this codebase shipped tokens bound to nothing — valid CSS, referenced by no utility, silently dead.
- **Do NOT write a test that asserts a hex/HSL literal equals itself, and do NOT assert that a Tailwind class string appears in a component.** Neither can fail. Ask of every guard: *what mutation makes this red?*
- Token format is a bare HSL triple (`240 18% 8%`), consumed as `hsl(var(--name))`. Never store a full `hsl(...)` string in the token.
- The brand rule stands: the violet accent is NEVER used for P&L.
- A2 defines colours; it does not apply impact or drawdown colours (that is sub-projects C and B). Tokens with no consumer yet are intended, per spec §2.
- The live trading bot serves `frontend/dist` from the main checkout. Work in the worktree you are given; do not rebuild `dist` in the main checkout and do not restart anything.
- Commit after every task.

---

### Task 1: Colour-token guard harness

**Files:**
- Create: `frontend/src/design/color-tokens.test.ts`
- Test: same file

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: two helpers later tasks extend —
  - `emittedFor(markup: string): Promise<string>` — compiles Tailwind against literal markup and returns the emitted CSS.
  - `tokenValue(name: string): string` — reads a token's HSL triple out of `tokens.css` (e.g. `tokenValue("--bg")` → `"225 20% 8%"`).
  - `contrastRatio(fgTriple: string, bgTriple: string): number` — WCAG contrast from two HSL triples.

This task builds the harness and points it at **tokens that already exist**, so the harness is proven before anything changes. Later tasks add cases to this same file.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/design/color-tokens.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import type { Config } from "tailwindcss";

import tailwindConfig from "../../tailwind.config";

const root = resolve(__dirname, "../..");
const tokensCss = readFileSync(resolve(root, "src/design/tokens.css"), "utf8");

/**
 * Compiles Tailwind against a scrap of markup and returns the emitted CSS.
 *
 * Asserting on the config object is NOT enough: a colour can be present in
 * `theme.extend.colors` and still emit nothing (wrong key shape, wrong
 * utility name). Only real compilation distinguishes "configured" from
 * "emitted". Same reasoning as design/motion.test.ts.
 */
export async function emittedFor(markup: string): Promise<string> {
  const config = { ...(tailwindConfig as Config), content: [{ raw: markup, extension: "html" }] } as Config;
  const { css } = await postcss([tailwindcss(config)]).process("@tailwind utilities;", { from: undefined });
  return css;
}

/** Reads a token's bare HSL triple out of tokens.css. Throws if absent. */
export function tokenValue(name: string): string {
  const m = tokensCss.match(new RegExp(`${name}\\s*:\\s*([^;]+);`));
  if (!m) throw new Error(`token ${name} is not defined in tokens.css`);
  return m[1].trim();
}

function hslTripleToRgb(triple: string): [number, number, number] {
  const m = triple.match(/^([\d.]+)\s+([\d.]+)%\s+([\d.]+)%$/);
  if (!m) throw new Error(`not a bare HSL triple: "${triple}"`);
  const h = parseFloat(m[1]) / 360, s = parseFloat(m[2]) / 100, l = parseFloat(m[3]) / 100;
  if (s === 0) return [l, l, l];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const channel = (t: number) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return [channel(h + 1 / 3), channel(h), channel(h - 1 / 3)];
}

/** WCAG 2.1 relative luminance + contrast ratio, from two bare HSL triples. */
export function contrastRatio(fgTriple: string, bgTriple: string): number {
  const lum = (t: string) => {
    const [r, g, b] = hslTripleToRgb(t).map((c) =>
      c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
    );
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const a = lum(fgTriple), b = lum(bgTriple);
  const [hi, lo] = a > b ? [a, b] : [b, a];
  return (hi + 0.05) / (lo + 0.05);
}

describe("colour token harness", () => {
  it("reads an existing token's triple", () => {
    expect(tokenValue("--accent")).toMatch(/^[\d.]+\s+[\d.]+%\s+[\d.]+%$/);
  });

  it("throws for a token that does not exist", () => {
    expect(() => tokenValue("--not-a-real-token")).toThrow(/not defined/);
  });

  it("computes a known contrast ratio (white on black is 21:1)", () => {
    expect(contrastRatio("0 0% 100%", "0 0% 0%")).toBeCloseTo(21, 1);
  });

  it("body text clears WCAG AA on every surface TODAY (baseline before any retune)", () => {
    for (const surface of ["--bg", "--surface-1", "--surface-2", "--elevated"]) {
      expect(
        contrastRatio(tokenValue("--text-primary"), tokenValue(surface)),
        `--text-primary on ${surface}`
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("an existing bound colour actually EMITS css, not merely configured", async () => {
    const css = await emittedFor('<div class="bg-surface-1 text-loss"></div>');
    expect(css).toContain("--surface-1");
    expect(css).toContain("--loss");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"
cd frontend && npx vitest run src/design/color-tokens.test.ts
```

Expected: FAIL — the file does not exist yet, so this run creates it and confirms the harness works. If any assertion fails on the CURRENT tokens, STOP and report: that means the baseline is already broken and the retune in Task 2 would be building on a false premise.

- [ ] **Step 3: No implementation needed**

This task's deliverable IS the test file — it asserts against tokens that already exist. If Step 2 passed on first run, that is the expected outcome; note it in your report.

- [ ] **Step 4: Confirm it passes**

```bash
cd frontend && npx vitest run src/design/color-tokens.test.ts
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/design/color-tokens.test.ts
git commit -m "test(design): colour token harness — compile-based binding + contrast checks"
```

---

### Task 2: Surface retune

**Files:**
- Modify: `frontend/src/design/tokens.css` (the six surface/line tokens)
- Test: `frontend/src/design/color-tokens.test.ts` (append)

**Interfaces:**
- Consumes: `tokenValue`, `contrastRatio` from Task 1.
- Produces: retuned surface tokens. Names are unchanged, so nothing downstream needs editing.

Exact values from spec §3 — the **lightness digits must not change**, only hue and saturation:

| Token | From | To |
|---|---|---|
| `--bg` | `225 20% 8%` | `240 18% 8%` |
| `--surface-1` | `223 19% 15%` | `240 16% 15%` |
| `--surface-2` | `222 16% 21%` | `240 14% 21%` |
| `--elevated` | `220 17% 24%` | `240 14% 24%` |
| `--border` | `222 16% 21%` | `240 14% 21%` |
| `--border-strong` | `221 16% 27%` | `240 14% 27%` |

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/design/color-tokens.test.ts`:

```ts
describe("surface retune (spec §3)", () => {
  const SURFACES = {
    "--bg": "8%",
    "--surface-1": "15%",
    "--surface-2": "21%",
    "--elevated": "24%",
    "--border": "21%",
    "--border-strong": "27%",
  } as const;

  it("holds the lightness ladder EXACTLY — this is what makes the contrast claim true", () => {
    for (const [name, lightness] of Object.entries(SURFACES)) {
      expect(tokenValue(name).split(/\s+/)[2], `${name} lightness`).toBe(lightness);
    }
  });

  it("moves the neutrals onto the brand hue", () => {
    for (const name of Object.keys(SURFACES)) {
      expect(Number(tokenValue(name).split(/\s+/)[0]), `${name} hue`).toBe(240);
    }
  });

  it("body text still clears WCAG AA on every retuned surface", () => {
    for (const name of Object.keys(SURFACES)) {
      expect(
        contrastRatio(tokenValue("--text-primary"), tokenValue(name)),
        `--text-primary on ${name}`
      ).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("muted text still clears WCAG AA large-text (3:1) on the card surface", () => {
    expect(contrastRatio(tokenValue("--text-muted"), tokenValue("--surface-1"))).toBeGreaterThanOrEqual(3);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/design/color-tokens.test.ts
```

Expected: FAIL — "moves the neutrals onto the brand hue" reports the current hues (225, 223, 222, 220, 222, 221), not 240.

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/design/tokens.css`, replace the surface and line block with:

```css
  /* surfaces — hue tinted toward the brand violet so panels read as
     intentional rather than flat slate. The LIGHTNESS ladder (8/15/21/24) is
     deliberately unchanged from the original brand board: every contrast
     ratio in the app is a function of lightness, and color-tokens.test.ts
     pins both the ladder and the resulting WCAG ratios. Hex comments dropped
     on purpose — they described the pre-retune values and would now lie. */
  --bg: 240 18% 8%;
  --surface-1: 240 16% 15%;    /* cards/panels */
  --surface-2: 240 14% 21%;    /* muted rows / inputs / table header */
  --elevated: 240 14% 24%;     /* popovers / command palette / dialogs */
  /* lines + text */
  --border: 240 14% 21%;
  --border-strong: 240 14% 27%;
```

Leave `--text-primary`, `--text-secondary`, `--text-muted` exactly as they are.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/design/color-tokens.test.ts
```

Expected: PASS. If a contrast assertion fails, do NOT weaken the assertion — report it; the spec's premise would be wrong.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/design/tokens.css frontend/src/design/color-tokens.test.ts
git commit -m "feat(design): retune surface neutrals onto the brand hue"
```

---

### Task 3: Semantic tokens — domain, impact, drawdown

**Files:**
- Modify: `frontend/src/design/tokens.css` (add a semantic block)
- Modify: `frontend/tailwind.config.ts` (`theme.extend.colors`, after the existing `profit`/`loss` entries)
- Test: `frontend/src/design/color-tokens.test.ts` (append)

**Interfaces:**
- Consumes: `emittedFor`, `tokenValue` from Task 1.
- Produces: Tailwind colour utilities later sub-projects use —
  `domain-risk`, `domain-market`, `domain-execution`, `domain-analytics`,
  `impact-high`, `impact-medium`, `impact-low`,
  `dd-shallow`, `dd-moderate`, `dd-severe`.
  So `bg-impact-high`, `text-dd-severe`, `border-domain-risk` all compile.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/design/color-tokens.test.ts`:

```ts
describe("semantic colour vocabulary (spec §4-§6)", () => {
  const TOKENS = [
    "--domain-risk", "--domain-market", "--domain-execution", "--domain-analytics",
    "--impact-high", "--impact-medium", "--impact-low",
    "--dd-shallow", "--dd-moderate", "--dd-severe",
  ];

  it("defines every semantic token as a bare HSL triple", () => {
    for (const name of TOKENS) {
      expect(tokenValue(name), name).toMatch(/^[\d.]+\s+[\d.]+%\s+[\d.]+%$/);
    }
  });

  it("BINDS every semantic token to a utility that actually emits css", async () => {
    // The failure this catches: a token defined in tokens.css but absent from
    // tailwind.config.ts is valid CSS referenced by nothing — exactly the bug
    // the GUI motion foundation shipped.
    const classes = TOKENS.map((t) => `bg-${t.replace(/^--/, "")}`).join(" ");
    const css = await emittedFor(`<div class="${classes}"></div>`);
    for (const name of TOKENS) {
      expect(css, `${name} emits no css — is it bound in tailwind.config.ts?`).toContain(name);
    }
  });

  it("keeps the drawdown ramp monotonically more saturated toward severe", () => {
    const sat = (n: string) => parseFloat(tokenValue(n).split(/\s+/)[1]);
    expect(sat("--dd-shallow")).toBeLessThan(sat("--dd-moderate"));
    expect(sat("--dd-moderate")).toBeLessThan(sat("--dd-severe"));
  });

  it("lands --dd-severe exactly on --loss so the ramp converges on the P&L red", () => {
    expect(tokenValue("--dd-severe")).toBe(tokenValue("--loss"));
  });

  it("gives the four domains four distinct hues", () => {
    const hues = ["--domain-risk", "--domain-market", "--domain-execution", "--domain-analytics"]
      .map((n) => Number(tokenValue(n).split(/\s+/)[0]));
    expect(new Set(hues).size).toBe(4);
  });

  it("exposes the tint alphas as tokens so tint strength is one decision", () => {
    expect(tokenValue("--tint-weak")).toBe("0.07");
    expect(tokenValue("--tint-strong")).toBe("0.16");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/design/color-tokens.test.ts
```

Expected: FAIL — `token --domain-risk is not defined in tokens.css`.

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/design/tokens.css`, add after the existing semantic block (the one holding `--profit`/`--loss`/`--warning`/`--info`/`--blocked`):

```css
  /* --- Semantic vocabulary (spec 2026-08-03 visual-language-foundation) ---
     Defined here so sub-projects B (equity chart), C (news) and D (market
     strip) share ONE vocabulary instead of inventing three. Some of these
     have no consumer yet; that is intended, not dead code. */

  /* Domain tints: identify a panel's subject at a glance. Used at --tint-weak
     on a header wash and full strength on a 2px left border. */
  --domain-risk: 20 70% 55%;
  --domain-market: 200 70% 55%;
  --domain-execution: 252 83% 65%;   /* the brand accent — execution IS the product */
  --domain-analytics: 160 60% 50%;
  --tint-weak: 0.07;
  --tint-strong: 0.16;

  /* News impact (red/orange/yellow folder convention).
     WARNING: --impact-high (hue 10) sits ~12 deg from --loss (hue 358), and
     that is deliberate — both are red by convention. Colour therefore must
     NEVER be the only channel: every impact indicator also carries its text
     label (High/Med/Low), so a red-green colour-blind operator cannot confuse
     "high-impact release" with "losing money". */
  --impact-high: 10 85% 56%;
  --impact-medium: 32 90% 55%;
  --impact-low: 48 75% 55%;

  /* Drawdown severity, keyed by B to distance from the daily breaker
     (risk.account.max_daily_dd_pct). Converges on --loss at the severe end so
     a deep drawdown and a losing P&L read as the same red. */
  --dd-shallow: 358 40% 55%;
  --dd-moderate: 358 65% 60%;
  --dd-severe: 358 84% 64%;
```

In `frontend/tailwind.config.ts`, inside `theme.extend.colors`, after the `profit`/`loss` lines:

```ts
        // Semantic vocabulary — see src/design/tokens.css. Bound here in the
        // SAME change as the token definitions: a token bound to nothing is
        // valid CSS referenced by no utility, which is how the motion tokens
        // silently shipped dead.
        "domain-risk": "hsl(var(--domain-risk))",
        "domain-market": "hsl(var(--domain-market))",
        "domain-execution": "hsl(var(--domain-execution))",
        "domain-analytics": "hsl(var(--domain-analytics))",
        "impact-high": "hsl(var(--impact-high))",
        "impact-medium": "hsl(var(--impact-medium))",
        "impact-low": "hsl(var(--impact-low))",
        "dd-shallow": "hsl(var(--dd-shallow))",
        "dd-moderate": "hsl(var(--dd-moderate))",
        "dd-severe": "hsl(var(--dd-severe))",
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/design/color-tokens.test.ts && npx tsc -b
```

Expected: PASS, and a clean type-check.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/design/tokens.css frontend/tailwind.config.ts frontend/src/design/color-tokens.test.ts
git commit -m "feat(design): semantic colour vocabulary — domain, impact, drawdown"
```

---

### Task 4: Move session colours into tokens

**Files:**
- Modify: `frontend/src/design/tokens.css` (add four session tokens)
- Modify: `frontend/tailwind.config.ts` (bind them)
- Modify: `frontend/src/components/market/MarketSessions.tsx:40-47` (`SESSION_COLORS`, `BAND_ALPHA`) and its two consumers at `:139` and `:172`/`SessionChip`
- Test: `frontend/src/design/color-tokens.test.ts` (append)

**Interfaces:**
- Consumes: `emittedFor`, `tokenValue` from Task 1.
- Produces: `--session-sydney`, `--session-tokyo`, `--session-london`, `--session-newyork` and matching `session-*` Tailwind colours. `SESSION_COLORS` keeps its shape `Record<string, string>` but its values become `hsl(var(--session-<id>))` strings, so every existing consumer keeps working.

**This is behaviour-preserving.** The HSL values below are faithful conversions of the current hexes; nothing should look different.

| Session | Current hex | HSL triple |
|---|---|---|
| sydney | `#F59E0B` | `38 92% 50%` |
| tokyo | `#FB5C7D` | `348 95% 67%` |
| london | `#8B7CF6` | `247 87% 73%` |
| newyork | `#2DD4A7` | `164 66% 50%` |

⚠️ `BAND_ALPHA = "B3"` is an 8-digit-hex alpha suffix appended to a hex colour (`SESSION_COLORS[id] + BAND_ALPHA`). That trick CANNOT work on an `hsl(var(--x))` string — appending "B3" produces invalid CSS and the band renders transparent. Replace it with a real alpha channel: `hsl(var(--session-<id>) / 0.70)`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/design/color-tokens.test.ts`:

```ts
describe("session colours moved into tokens (spec §7)", () => {
  // Faithful conversions of the hexes that used to live in MarketSessions.tsx.
  // If someone retunes a session colour later they must update this table —
  // that is the point: the value stops being invisible inside a component.
  const EXPECTED = {
    "--session-sydney": "38 92% 50%",
    "--session-tokyo": "348 95% 67%",
    "--session-london": "247 87% 73%",
    "--session-newyork": "164 66% 50%",
  } as const;

  it("defines all four session tokens with the converted values", () => {
    for (const [name, triple] of Object.entries(EXPECTED)) {
      expect(tokenValue(name), name).toBe(triple);
    }
  });

  it("binds them to utilities that emit css", async () => {
    const css = await emittedFor(
      '<div class="bg-session-sydney bg-session-tokyo bg-session-london bg-session-newyork"></div>'
    );
    for (const name of Object.keys(EXPECTED)) {
      expect(css, `${name} emits no css`).toContain(name);
    }
  });

  it("leaves no raw hex literals in MarketSessions", () => {
    const src = readFileSync(resolve(root, "src/components/market/MarketSessions.tsx"), "utf8");
    expect(src).not.toMatch(/#[0-9a-fA-F]{6}/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/design/color-tokens.test.ts
```

Expected: FAIL — `token --session-sydney is not defined in tokens.css`.

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/design/tokens.css`, add to the semantic block:

```css
  /* Trading-session identity colours. Moved out of MarketSessions.tsx, where
     they were the app's only raw hex literals. Values are faithful HSL
     conversions of those hexes, so this move is visually a no-op; sub-project
     D may retune them here. */
  --session-sydney: 38 92% 50%;
  --session-tokyo: 348 95% 67%;
  --session-london: 247 87% 73%;
  --session-newyork: 164 66% 50%;
```

In `frontend/tailwind.config.ts`, inside `theme.extend.colors`:

```ts
        "session-sydney": "hsl(var(--session-sydney))",
        "session-tokyo": "hsl(var(--session-tokyo))",
        "session-london": "hsl(var(--session-london))",
        "session-newyork": "hsl(var(--session-newyork))",
```

In `frontend/src/components/market/MarketSessions.tsx`, replace the `SESSION_COLORS` and `BAND_ALPHA` block:

```tsx
/**
 * Session identity colours, resolved from design tokens rather than hex
 * literals — see src/design/tokens.css. Values stay full `hsl(var(--x))`
 * strings because they are consumed from inline `style`, not Tailwind classes.
 */
const SESSION_COLORS: Record<string, string> = {
  sydney: "hsl(var(--session-sydney))",
  tokyo: "hsl(var(--session-tokyo))",
  london: "hsl(var(--session-london))",
  newyork: "hsl(var(--session-newyork))",
};

/** Timeline band fill: ~70% — vivid, still lets the now-marker + overlaps read. */
const sessionBand = (id: string) => `hsl(var(--session-${id}) / 0.70)`;
```

At the timeline band (was `backgroundColor: SESSION_COLORS[session.id] + BAND_ALPHA`):

```tsx
                    backgroundColor: sessionBand(session.id),
```

`SessionChip` uses `color` and a `${color}14` / `${color}26` suffix for its wash and chip background — those are the same hex-alpha trick and break identically. Replace them by passing the session id through and using the alpha form:

```tsx
function SessionChip({ session, color }: { session: SessionState; color: string }) {
  const wash = `hsl(var(--session-${session.id}) / 0.08)`;
  const chipBg = `hsl(var(--session-${session.id}) / 0.15)`;
```

then use `wash` where `${color}14` was and `chipBg` where `${color}26` was, leaving every plain `color` usage (the label and the dot) unchanged.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/design/color-tokens.test.ts src/components/market/MarketSessions.test.tsx && npx tsc -b
```

Expected: PASS — including the pre-existing MarketSessions tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/design/tokens.css frontend/tailwind.config.ts \
        frontend/src/components/market/MarketSessions.tsx frontend/src/design/color-tokens.test.ts
git commit -m "refactor(design): session colours become tokens, not hex literals"
```

---

### Task 5: Domain tints on panels

**Files:**
- Modify: `frontend/src/components/shell/Panel.tsx` (props + header/card classes)
- Modify: `frontend/src/sections/OverviewPage.tsx` (pass `domain` to each `Panel`)
- Test: `frontend/src/components/shell/Panel.test.tsx` (append)

**Interfaces:**
- Consumes: the `domain-*` tokens and `--tint-weak` from Task 3.
- Produces: `PanelProps` gains `domain?: "risk" | "market" | "execution" | "analytics"`. When present the panel gets a 2px left border in that domain's colour and a weak header wash. Panels that omit it render exactly as before.

This is A2's only visible application. Impact and drawdown colours stay unapplied — spec §2.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/shell/Panel.test.tsx`:

```tsx
describe("Panel domain tint", () => {
  it("renders no domain marker unless a domain is given", () => {
    const { container } = render(<Panel status="populated" title="Plain">body</Panel>);
    expect(container.querySelector("[data-domain]")).toBeNull();
  });

  it("marks the panel with its domain so the tint is inspectable", () => {
    const { container } = render(
      <Panel status="populated" title="Risk" domain="risk">body</Panel>
    );
    expect(container.querySelector('[data-domain="risk"]')).not.toBeNull();
  });

  it("keeps rendering its children and title with a domain set", () => {
    render(<Panel status="populated" title="Risk" domain="risk">tinted body</Panel>);
    expect(screen.getByText("tinted body")).toBeInTheDocument();
    expect(screen.getByText("Risk")).toBeInTheDocument();
  });
});

describe("Panel status tint (spec §8)", () => {
  it("marks a stale panel so the warning tint is inspectable", () => {
    const { container } = render(<Panel status="stale" title="S">body</Panel>);
    expect(container.querySelector('[data-tone="stale"]')).not.toBeNull();
  });

  it("marks an error panel", () => {
    const { container } = render(<Panel status="error" title="E" />);
    expect(container.querySelector('[data-tone="error"]')).not.toBeNull();
  });

  it("leaves a healthy panel untoned", () => {
    const { container } = render(<Panel status="populated" title="P">body</Panel>);
    expect(container.querySelector("[data-tone]")).toBeNull();
  });

  it("still shows the stale marker and children (tint is additive, not a replacement)", () => {
    render(<Panel status="stale" title="S">stale body</Panel>);
    expect(screen.getByTestId("stale-marker")).toBeInTheDocument();
    expect(screen.getByText("stale body")).toBeInTheDocument();
  });
});
```

Note this asserts on a `data-domain` attribute, not on a Tailwind class string — the attribute is real rendered state a mutation can break, whereas a class-string assertion passes whether or not the colour resolves.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/shell/Panel.test.tsx
```

Expected: FAIL — TypeScript rejects the unknown `domain` prop.

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/components/shell/Panel.tsx`, add to `PanelProps`:

```tsx
  /** Subject area. Adds a left border + weak header wash in the domain colour. */
  domain?: "risk" | "market" | "execution" | "analytics";
```

Add `domain` to the destructured params. Map it to classes (a literal lookup, because Tailwind cannot see dynamically-built class names):

```tsx
const DOMAIN_BORDER: Record<string, string> = {
  risk: "border-l-2 border-l-domain-risk",
  market: "border-l-2 border-l-domain-market",
  execution: "border-l-2 border-l-domain-execution",
  analytics: "border-l-2 border-l-domain-analytics",
};
```

Status tint (spec §8) reuses the existing semantic colours rather than inventing a second
yellow — `stale` → `--warning`, `error` → `--loss`, both weak:

```tsx
// Spec §8: no NEW colours for status. `/7` and `/16` are the --tint-weak and
// --tint-strong values; Tailwind's slash-opacity needs literals, so the tokens
// document the intent and these mirror them.
const STATUS_TONE: Partial<Record<PanelStatus, { tone: string; cls: string }>> = {
  stale: { tone: "stale", cls: "bg-warning/[0.07]" },
  error: { tone: "error", cls: "bg-loss/[0.07]" },
};
```

Apply both on the `Card`, and stamp the attributes:

```tsx
    <Card
      className={cn(
        "bg-surface-1 shadow-1",
        domain && DOMAIN_BORDER[domain],
        STATUS_TONE[status]?.cls,
        className
      )}
      data-domain={domain}
      data-tone={STATUS_TONE[status]?.tone}
    >
```

`data-domain={undefined}` / `data-tone={undefined}` render no attribute at all, which is what
the "renders no domain marker" and "leaves a healthy panel untoned" tests pin.

In `frontend/src/sections/OverviewPage.tsx`, tag the existing panels:

```tsx
      <Panel status={baseStatus} title="Overview" domain="analytics">
      <Panel status={baseStatus} title="Risk" domain="risk">
      <Panel status={equityStatus} title="Equity" domain="analytics" onMaximize={...}>
      <Panel status={baseStatus} title="Controls" domain="execution">
      <Panel status={positionsStatus} title="Top Positions" domain="execution" ...>
      <Panel status={activityStatus} title="Recent Activity" domain="market" ...>
```

Keep every other prop on those panels exactly as it is; only add `domain`.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/shell/Panel.test.tsx src/sections/OverviewPage.test.tsx && npx tsc -b
```

Expected: PASS.

- [ ] **Step 5: Full suite, build, and commit**

```bash
cd frontend && npm test && npm run build
```

`npm test` takes 4-7 minutes — run it in the FOREGROUND and wait. If `src/App.test.tsx > gates on token`, `Controls`, or `StrategiesTab` report "Test timed out in 5000ms", that is a known load-sensitive flake (that test uses ~3900ms of a 5000ms budget even on an idle box), not a regression. Re-run those three files in isolation and report both results.

```bash
git add frontend/src/components/shell/Panel.tsx frontend/src/components/shell/Panel.test.tsx \
        frontend/src/sections/OverviewPage.tsx
git commit -m "feat(gui): domain tints on Overview panels"
```

---

## Manual verification (not unit-testable)

jsdom computes no layout and no resolved colour, so the retune and tints need a real browser. Use the recipe proven in sub-project A — it never touches the live bot:

1. `npm run build` in the worktree's `frontend/`.
2. From the worktree root: `TITAN_GUI_PORT=8899 TITAN_GUI_TOKEN=layoutcheck <main-checkout>/.venv/bin/python -m src.ops.web.devserver` (give it ~10s to bind; the live bot owns 8770 and 32768-9 — confirm with `ss -tlnp` before and after).
3. Open `http://127.0.0.1:8899`, enter `layoutcheck`.
4. Confirm: panels read warmer, not grey; the four domain tints are distinguishable; session bands and chips look UNCHANGED from before (Task 4 is meant to be a visual no-op — a transparent band means the alpha migration broke).
5. Screenshot for the record, then stop the devserver.
