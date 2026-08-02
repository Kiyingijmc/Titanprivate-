import { describe, it, expect, vi } from "vitest";
import type { RangeName } from "@/lib/types";
import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RangeSelector, rangeSeconds, lookupRangeSeconds, enabledRangeNames } from "./RangeSelector";

const NOW = 1_800_000_000;

describe("RangeSelector", () => {
  it("renders all eleven ranges and marks the active one", () => {
    render(<RangeSelector value="1d" onChange={() => {}} firstSampleTs={0} now={NOW} />);
    expect(screen.getAllByRole("radio")).toHaveLength(11);
    expect(screen.getByRole("radio", { name: "1d" })).toHaveAttribute("aria-checked", "true");
  });

  it("disables ranges wider than the available history and says when they unlock", () => {
    // three days of history: 1d is fine, 1w is not
    render(<RangeSelector value="1d" onChange={() => {}} firstSampleTs={NOW - 3 * 86400} now={NOW} />);
    expect(screen.getByRole("radio", { name: "1d" })).not.toBeDisabled();
    const week = screen.getByRole("radio", { name: "1w" });
    expect(week).toBeDisabled();
    expect(week).toHaveAttribute("title", expect.stringContaining("unlocks"));
  });

  it("disables every range when there is no history at all", () => {
    render(<RangeSelector value="1d" onChange={() => {}} firstSampleTs={null} now={NOW} />);
    screen.getAllByRole("radio").forEach((b) => expect(b).toBeDisabled());
  });

  it("emits the clicked range and never emits a disabled one", async () => {
    const onChange = vi.fn();
    render(<RangeSelector value="1d" onChange={onChange} firstSampleTs={NOW - 3 * 86400} now={NOW} />);
    await userEvent.click(screen.getByRole("radio", { name: "4h" }));
    expect(onChange).toHaveBeenCalledWith("4h");
    await userEvent.click(screen.getByRole("radio", { name: "1y" }));
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("rangeSeconds covers every range name", () => {
    expect(rangeSeconds("15m")).toBe(900);
    expect(rangeSeconds("1d")).toBe(86_400);
    expect(rangeSeconds("1y")).toBe(31_536_000);
  });

  it("lookupRangeSeconds is null for a name that is not one of ours", () => {
    // Callers get `series.range` as a plain string from the API; blind indexing
    // would yield undefined and silently poison arithmetic downstream.
    expect(lookupRangeSeconds("1d")).toBe(86_400);
    expect(lookupRangeSeconds("5y")).toBeNull();
    expect(lookupRangeSeconds("toString")).toBeNull();
  });

  it("enabledRangeNames returns only the ranges the history reaches", () => {
    expect(enabledRangeNames(NOW - 3 * 86400, NOW)).toEqual(["15m", "30m", "1h", "4h", "12h", "1d"]);
    expect(enabledRangeNames(null, NOW)).toEqual([]);
  });

  // ---- C1 (second face): "no history" vs "could not load history" ----

  it("does not blame the recorder when it was the FETCH that failed", () => {
    const { rerender } = render(
      <RangeSelector value="1d" onChange={() => {}} firstSampleTs={null} now={NOW} />,
    );
    expect(screen.getByRole("radio", { name: "1d" })).toHaveAttribute(
      "title", "No equity history recorded yet",
    );

    rerender(<RangeSelector value="1d" onChange={() => {}} firstSampleTs={null} loadError now={NOW} />);
    const title = screen.getByRole("radio", { name: "1d" }).getAttribute("title")!;
    expect(title).toContain("Could not load");
    expect(title).not.toContain("No equity history recorded yet");
  });

  // ---- I5: WAI-ARIA radiogroup keyboard operation ----

  describe("keyboard", () => {
    it("exposes exactly ONE tab stop (roving tabindex), not eleven", () => {
      render(<RangeSelector value="1d" onChange={() => {}} firstSampleTs={0} now={NOW} />);
      const radios = screen.getAllByRole("radio");
      const stops = radios.filter((r) => r.getAttribute("tabindex") === "0");
      expect(stops).toHaveLength(1);
      expect(stops[0]).toHaveAccessibleName("1d");
      radios.filter((r) => r !== stops[0]).forEach((r) => expect(r).toHaveAttribute("tabindex", "-1"));
    });

    it("hands the tab stop to an enabled option when the selected one is disabled", () => {
      // e.g. the selection was restored from a wider range than the history now
      // supports — the group must not become unreachable by keyboard.
      render(<RangeSelector value="1y" onChange={() => {}} firstSampleTs={NOW - 3 * 86400} now={NOW} />);
      const stops = screen.getAllByRole("radio").filter((r) => r.getAttribute("tabindex") === "0");
      expect(stops).toHaveLength(1);
      expect(stops[0]).toHaveAccessibleName("15m");
    });

    it("moves and selects with ArrowRight / ArrowLeft", async () => {
      const onChange = vi.fn();
      render(<RangeSelector value="1d" onChange={onChange} firstSampleTs={0} now={NOW} />);
      screen.getByRole("radio", { name: "1d" }).focus();

      await userEvent.keyboard("{ArrowRight}");
      expect(onChange).toHaveBeenLastCalledWith("1w");

      await userEvent.keyboard("{ArrowLeft}");
      expect(onChange).toHaveBeenLastCalledWith("12h");
    });

    it("moves with ArrowDown / ArrowUp too", async () => {
      const onChange = vi.fn();
      render(<RangeSelector value="1d" onChange={onChange} firstSampleTs={0} now={NOW} />);
      screen.getByRole("radio", { name: "1d" }).focus();

      await userEvent.keyboard("{ArrowDown}");
      expect(onChange).toHaveBeenLastCalledWith("1w");
      await userEvent.keyboard("{ArrowUp}");
      expect(onChange).toHaveBeenLastCalledWith("12h");
    });

    it("jumps to the first / last ENABLED option with Home and End", async () => {
      const onChange = vi.fn();
      render(<RangeSelector value="1h" onChange={onChange} firstSampleTs={NOW - 3 * 86400} now={NOW} />);
      screen.getByRole("radio", { name: "1h" }).focus();

      await userEvent.keyboard("{Home}");
      expect(onChange).toHaveBeenLastCalledWith("15m");
      await userEvent.keyboard("{End}");
      expect(onChange).toHaveBeenLastCalledWith("1d"); // NOT 1y — 1w+ are disabled
    });

    it("never lands on a disabled option when arrowing past the end", async () => {
      const onChange = vi.fn();
      // three days of history: 15m..1d enabled, 1w..1y disabled
      render(<RangeSelector value="1d" onChange={onChange} firstSampleTs={NOW - 3 * 86400} now={NOW} />);
      screen.getByRole("radio", { name: "1d" }).focus();

      await userEvent.keyboard("{ArrowRight}");
      expect(onChange).toHaveBeenLastCalledWith("15m"); // wraps within the enabled set
      expect(onChange).not.toHaveBeenCalledWith("1w");
    });

    it("moves DOM focus along with the selection", async () => {
      // Focus must follow, or the next arrow press comes from the old element
      // and the group stops responding after one step.
      function Harness() {
        const [v, setV] = useState<RangeName>("1d");
        return <RangeSelector value={v} onChange={setV} firstSampleTs={0} now={NOW} />;
      }
      render(<Harness />);
      screen.getByRole("radio", { name: "1d" }).focus();

      await userEvent.keyboard("{ArrowRight}");
      expect(screen.getByRole("radio", { name: "1w" })).toHaveFocus();
      await userEvent.keyboard("{ArrowRight}");
      expect(screen.getByRole("radio", { name: "1mo" })).toHaveFocus();
      expect(screen.getByRole("radio", { name: "1mo" })).toHaveAttribute("aria-checked", "true");
    });

    it("does nothing when every option is disabled", async () => {
      const onChange = vi.fn();
      const { container } = render(
        <RangeSelector value="1d" onChange={onChange} firstSampleTs={null} now={NOW} />,
      );
      fireEvent.keyDown(container.querySelector("[role=radiogroup]")!, { key: "ArrowRight" });
      expect(onChange).not.toHaveBeenCalled();
    });
  });

  // ---- M2: selection must not change text metrics ----

  it("selection is a colour change only — it never reflows the row", () => {
    // `font-semibold` on the active pill changed glyph widths, so every click
    // re-laid-out the whole selector. jsdom cannot measure that, but it can
    // check the invariant that caused it: no metric-affecting utility class
    // differs between the active and inactive states.
    const METRIC_CLASSES = /^(font-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black)|text-(xs|sm|base|lg|xl|\d?xl)|tracking-\S+|px-\S+|py-\S+|p-\S+|uppercase|lowercase|capitalize)$/;
    const metricsOf = (el: Element) =>
      Array.from(el.classList).filter((c) => METRIC_CLASSES.test(c)).sort();

    render(<RangeSelector value="1d" onChange={() => {}} firstSampleTs={0} now={NOW} />);
    const active = screen.getByRole("radio", { name: "1d" });
    const inactive = screen.getByRole("radio", { name: "4h" });
    expect(metricsOf(active)).toEqual(metricsOf(inactive));
  });
});
