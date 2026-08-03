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
