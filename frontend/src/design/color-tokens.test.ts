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

  it("chromatic HSL→RGB conversions: red on white ≈ 4.0, green on white ≈ 1.37", () => {
    expect(contrastRatio("0 100% 50%", "0 0% 100%")).toBeCloseTo(4.0, 1);
    expect(contrastRatio("120 100% 50%", "0 0% 100%")).toBeCloseTo(1.37, 1);
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

  // Fix 1: nothing previously pinned SATURATION — a mutation changing --bg
  // from `240 18% 8%` to `240 30% 8%` turned zero tests red (hue and
  // lightness are asserted above, but the middle HSL component never was).
  const SATURATIONS = {
    "--bg": "18%",
    "--surface-1": "16%",
    "--surface-2": "14%",
    "--elevated": "14%",
    "--border": "14%",
    "--border-strong": "14%",
  } as const;

  it("holds the saturation ladder EXACTLY — closes the gap the lightness/hue tests left open", () => {
    for (const [name, saturation] of Object.entries(SATURATIONS)) {
      expect(tokenValue(name).split(/\s+/)[1], `${name} saturation`).toBe(saturation);
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

/**
 * Fix 2: `--domain-execution` is hardcoded to the violet accent value in
 * `:root`, so the `:root[data-accent="blue"]` theme override (which re-skins
 * --accent/--accent-hover/--accent-active/--accent-subtle/--focus-ring/--blocked)
 * left it behind — toggling the blue theme put two competing brand colours on
 * screen (violet Controls/Top Positions tint vs. a blue-skinned everything
 * else). `tokenValue()` returns the FIRST match in the file, which is the
 * `:root` (violet) declaration, so it cannot see the blue block at all; this
 * local helper extracts that block's body specifically.
 */
function blueThemeTokenValue(name: string): string {
  const block = tokensCss.match(/:root\[data-accent="blue"\]\s*\{([^}]*)\}/);
  if (!block) throw new Error('block :root[data-accent="blue"] not found in tokens.css');
  const m = block[1].match(new RegExp(`${name}\\s*:\\s*([^;]+);`));
  if (!m) throw new Error(`token ${name} is not defined in the :root[data-accent="blue"] block`);
  return m[1].trim();
}

describe("--domain-execution tracks --accent under the blue theme (fix 2)", () => {
  it("matches --accent inside :root[data-accent=\"blue\"] — mutation: delete the blue-block --domain-execution line", () => {
    expect(blueThemeTokenValue("--domain-execution")).toBe(blueThemeTokenValue("--accent"));
  });
});

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
