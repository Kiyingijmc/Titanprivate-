import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import type { Config } from "tailwindcss";

import tailwindConfig from "../../tailwind.config";

const root = resolve(__dirname, "../..");
const read = (p: string) => readFileSync(resolve(root, p), "utf8");

/**
 * Compiles Tailwind against a scrap of markup and returns the emitted CSS.
 *
 * The point of doing this rather than asserting on the config object: the
 * defect this suite guards against is a class that compiles to *nothing*
 * (every `animate-in` in dialog.tsx did, because no plugin defined it). Only
 * real compilation can tell the difference between "configured" and "emitted".
 */
async function compile(markup: string): Promise<string> {
  const config = {
    ...(tailwindConfig as Config),
    content: [{ raw: markup, extension: "html" }],
  } as Config;
  const { css } = await postcss([tailwindcss(config)]).process(
    "@tailwind utilities;",
    { from: undefined }
  );
  return css;
}

describe("motion tokens are bound into Tailwind", () => {
  it("the bare transition utilities resolve to the motion tokens, not Tailwind's defaults", async () => {
    const css = await compile('<div class="transition-colors">');
    expect(css).toContain("var(--ease)");
    expect(css).toContain("var(--motion-fast)");
    // Tailwind's built-in fallbacks must no longer leak through.
    expect(css).not.toContain("cubic-bezier(0.4, 0, 0.2, 1)");
  });

  it("emits duration and easing utilities for every motion token", async () => {
    const css = await compile(
      '<div class="duration-fast duration-base ease-out ease-in-out">'
    );
    expect(css).toContain("var(--motion-fast)");
    expect(css).toContain("var(--motion-base)");
    expect(css).toContain("var(--ease-out)");
    expect(css).toContain("var(--ease-in-out)");
  });

  it("declares every motion token it binds", () => {
    const tokens = read("src/design/tokens.css");
    for (const token of [
      "--motion-fast:",
      "--motion-base:",
      "--ease:",
      "--ease-out:",
      "--ease-in-out:",
    ]) {
      expect(tokens).toContain(token);
    }
  });
});

describe("reduced motion actually stops motion", () => {
  it("pins infinite animations to a single iteration and disables smooth scroll", () => {
    const css = read("src/index.css");
    const block = css.slice(css.indexOf("prefers-reduced-motion"));
    // Without iteration-count, animate-pulse/animate-spin loop forever at
    // 0.001ms — faster and more distracting than the animation they replace.
    expect(block).toMatch(/animation-iteration-count:\s*1\s*!important/);
    expect(block).toMatch(/animation-duration:\s*0\.001ms\s*!important/);
    expect(block).toMatch(/transition-duration:\s*0\.001ms\s*!important/);
    expect(block).toMatch(/scroll-behavior:\s*auto\s*!important/);
  });
});

describe("dialog motion is hand-rolled, not dependent on a plugin", () => {
  it("does not reintroduce tailwindcss-animate", () => {
    const pkg = JSON.parse(read("package.json"));
    const deps = { ...pkg.dependencies, ...pkg.devDependencies };
    expect(deps["tailwindcss-animate"]).toBeUndefined();
  });

  it("defines keyframes for dialog enter and exit driven by Radix data-state", () => {
    const css = read("src/index.css");
    expect(css).toMatch(/@keyframes titan-dialog-in/);
    expect(css).toMatch(/@keyframes titan-dialog-out/);
    expect(css).toMatch(/@keyframes titan-overlay-in/);
    expect(css).toMatch(/@keyframes titan-overlay-out/);
    expect(css).toMatch(/\[data-titan-dialog\]\[data-state="open"\]/);
    expect(css).toMatch(/\[data-titan-dialog\]\[data-state="closed"\]/);
  });

  it("enters from a visible scale, never from nothing", () => {
    const css = read("src/index.css");
    const enter = css.slice(
      css.indexOf("@keyframes titan-dialog-in"),
      css.indexOf("@keyframes titan-dialog-out")
    );
    expect(enter).toContain("scale(0.95)");
    expect(enter).not.toMatch(/scale\(0\)/);
  });

  it("exits faster than it enters", () => {
    const css = read("src/index.css");
    const open = /\[data-titan-dialog\]\[data-state="open"\][^}]*\}/.exec(css)?.[0] ?? "";
    const closed = /\[data-titan-dialog\]\[data-state="closed"\][^}]*\}/.exec(css)?.[0] ?? "";
    expect(open).toContain("var(--motion-base)");
    expect(closed).toContain("var(--motion-fast)");
  });

  it("no component still relies on the plugin classes that compiled to nothing", () => {
    for (const file of [
      "src/components/ui/dialog.tsx",
      "src/components/ui/alert-dialog.tsx",
    ]) {
      const src = read(file);
      expect(src).not.toMatch(/animate-in|animate-out|fade-in-|fade-out-|zoom-in-|zoom-out-|slide-in-from-|slide-out-to-/);
    }
  });
});
