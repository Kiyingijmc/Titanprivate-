import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import postcss from "postcss";
import tailwindcss from "tailwindcss";
import type { Config } from "tailwindcss";

import { MemoryRouter } from "react-router-dom";

import tailwindConfig from "../../tailwind.config";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/shell/Panel";
import { StatTiles } from "@/components/StatTiles";
import { Sidebar } from "@/components/shell/Sidebar";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ReadOnlyProvider } from "@/context/ReadOnlyContext";

const root = resolve(__dirname, "../..");
const read = (p: string) => readFileSync(resolve(root, p), "utf8");

/**
 * Compiles the classes actually present on a rendered element and returns the
 * emitted CSS. Asserting on the class string alone cannot tell a working
 * utility from one that emits nothing — the exact defect Phase 1 fixed — so
 * every claim about what a class *does* goes through real compilation.
 */
async function compileClassesOf(el: Element): Promise<string> {
  const markup = `<div class="${el.getAttribute("class") ?? ""}"></div>`;
  const { css } = await postcss([
    tailwindcss({ ...(tailwindConfig as Config), content: [{ raw: markup, extension: "html" }] } as Config),
  ]).process("@tailwind utilities;", { from: undefined });
  return css;
}

describe("pressable surfaces answer the press", () => {
  it("a button scales down on :active, and the transition covers transform", async () => {
    render(<Button>Panic</Button>);
    const css = await compileClassesOf(screen.getByRole("button"));

    // The press feedback must exist as a real :active rule.
    expect(css).toMatch(/:active\s*\{[^}]*--tw-scale-x:\s*\.?0?\.97/);
    // …and be transitionable: a scale that is not in transition-property snaps.
    const transitionRule = /transition-property:([^;]*)/.exec(css)?.[1] ?? "";
    expect(transitionRule).toContain("transform");
  });

  it("presses are timed by the motion tokens, not Tailwind's defaults", async () => {
    render(<Button>Panic</Button>);
    const css = await compileClassesOf(screen.getByRole("button"));
    expect(css).toContain("var(--motion-fast)");
    expect(css).toContain("var(--ease");
  });
});

describe("hover effects never stick on touch", () => {
  it("gates every hover utility behind a fine pointer", async () => {
    const { css } = await postcss([
      tailwindcss({
        ...(tailwindConfig as Config),
        content: [{ raw: '<div class="hover:bg-muted">', extension: "html" }],
      } as Config),
    ]).process("@tailwind utilities;", { from: undefined });
    // Without this, a tap on a phone fires :hover and the element stays stuck
    // in its hover state until the next tap elsewhere.
    expect(css).toMatch(/@media\s*\(hover:\s*hover\)\s*and\s*\(pointer:\s*fine\)/);
  });
});

describe("transitions name what they animate", () => {
  // These assert on the class attribute of the *rendered* element, not on file
  // text: source comments explaining why `transition-all` was removed contain
  // the string "transition-all", and a grep over the file cannot tell an
  // explanation from a regression.
  function tileClasses() {
    render(
      <StatTiles
        account={{ balance: 10000, equity: 10500 }}
        arbiter={{ stats: { submitted: 4, approved: 3, blocked_by: {} }, throttle: { enabled: false, current_mult: 1 } }}
        dayPnl={0}
        openPnl={0}
        openCount={1}
      />
    );
    return screen.getByTestId("tile-openpnl").getAttribute("class") ?? "";
  }

  it("the KPI tiles animate named properties, not everything", () => {
    const cls = tileClasses();
    // transition-all animates properties you never intended — including layout
    // ones that arrive later via a className override.
    expect(cls).not.toMatch(/\btransition-all\b/);
    expect(cls).toContain("transition-[border-color,box-shadow]");
  });

  it("the KPI row does not lift on hover", () => {
    // Frequency rule: an operator scans this row constantly. A springy tile
    // reads as noise on a dense dashboard; the border/shadow change is enough.
    expect(tileClasses()).not.toMatch(/hover:-translate-y/);
  });

  it("a tab trigger animates named properties, not everything", () => {
    render(
      <Tabs defaultValue="a">
        <TabsList>
          <TabsTrigger value="a">Positions</TabsTrigger>
        </TabsList>
      </Tabs>
    );
    const cls = screen.getByRole("tab").getAttribute("class") ?? "";
    expect(cls).not.toMatch(/\btransition-all\b/);
    expect(cls).toContain("transition-[color,background-color,box-shadow]");
  });

  it("the sidebar does not animate its own width", () => {
    render(
      <MemoryRouter>
        <ReadOnlyProvider>
          <Sidebar collapsed={false} onToggleCollapse={() => {}} />
        </ReadOnlyProvider>
      </MemoryRouter>
    );
    // width is a layout property: transitioning it relayouts and repaints the
    // entire main content tree (charts + positions table) every frame.
    const cls = screen.getByRole("complementary").getAttribute("class") ?? "";
    expect(cls).not.toContain("transition-[width]");
  });
});

describe("the failure toast does not blink into existence", () => {
  it("enters with a transition from offscreen", () => {
    const css = read("src/index.css");
    const block = css.slice(css.indexOf("[data-titan-toast]"));
    expect(block).toContain("@starting-style");
    // Off the bottom edge and centred — the X half of the transform is what
    // centres the toast, so it has to ride along on every frame.
    expect(block).toContain("translate(-50%, 100%)");
    expect(block).toContain("var(--ease-out)");
  });

  it("is marked up so that CSS can find it", () => {
    expect(read("src/components/shell/AppShell.tsx")).toContain("data-titan-toast");
  });
});

describe("loading skeletons read as a wave, not a block", () => {
  it("staggers the three bars", () => {
    render(<Panel status="loading" />);
    const bars = Array.from(screen.getByTestId("skeleton").children) as HTMLElement[];
    expect(bars).toHaveLength(3);
    const delays = bars.map((b) => b.style.animationDelay);
    // Synchronised pulsing reads as one mechanical block.
    expect(new Set(delays).size).toBe(3);
    expect(delays).toEqual(["0ms", "60ms", "120ms"]);
  });
});
