import "@testing-library/jest-dom/vitest";

// jsdom has no ResizeObserver; Recharts' <ResponsiveContainer> needs one to mount.
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;
}

// jsdom performs no layout, so <ResponsiveContainer>'s initial
// getBoundingClientRect() reads 0x0 and it never mounts its chart children
// (width/height <= 0 short-circuits Recharts' render). Stub a plausible panel
// size so chart component tests can assert on real SVG output.
if (typeof HTMLElement !== "undefined") {
  HTMLElement.prototype.getBoundingClientRect = () => ({
    width: 400,
    height: 200,
    top: 0,
    left: 0,
    bottom: 200,
    right: 400,
    x: 0,
    y: 0,
    toJSON() {},
  });
}
