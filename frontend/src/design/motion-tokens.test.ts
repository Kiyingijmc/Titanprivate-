import { describe, it, expect } from "vitest";
import tailwindConfig from "../../tailwind.config";

// Guards a DELIBERATE override: `transitionTimingFunction.out` replaces
// Tailwind's stock `ease-out` utility (built-in `cubic-bezier(0, 0, 0.2, 1)`)
// with Titan's design-system curve app-wide (see the comment in
// tailwind.config.ts). That override is intentional and permanent — but it
// must stay visible, not silently drift or get reverted, since any future
// component reaching for the *documented* Tailwind `ease-out` is actually
// getting Titan's curve instead. This test pins both the timing-function and
// duration bindings that RangeSelector's `ease-out`/`duration-fast` classes
// (frontend/src/components/RangeSelector.tsx) rely on to be genuinely bound
// to the CSS custom properties in tokens.css, rather than dead config.
describe("motion token bindings (tailwind.config.ts)", () => {
  it("overrides the stock `ease-out` utility with the design-system curve", () => {
    expect(tailwindConfig.theme?.extend?.transitionTimingFunction).toMatchObject({
      out: "var(--ease-out)",
    });
  });

  it("binds `duration-fast` to the design-system fast-motion token", () => {
    expect(tailwindConfig.theme?.extend?.transitionDuration).toMatchObject({
      fast: "var(--motion-fast)",
    });
  });
});
