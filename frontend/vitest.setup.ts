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
