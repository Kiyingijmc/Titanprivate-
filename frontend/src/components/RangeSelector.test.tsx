import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RangeSelector, rangeSeconds } from "./RangeSelector";

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
});
