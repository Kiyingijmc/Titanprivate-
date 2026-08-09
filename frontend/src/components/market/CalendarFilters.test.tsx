import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CalendarFilters } from "./CalendarFilters";
import { DEFAULT_FILTERS } from "@/lib/newsCalendar";

describe("CalendarFilters", () => {
  it("reflects the active impact levels as pressed toggles", () => {
    render(<CalendarFilters value={DEFAULT_FILTERS} onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "High" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Med" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Low" })).toHaveAttribute("aria-pressed", "false");
  });

  it("removes an active impact when its toggle is clicked", async () => {
    const onChange = vi.fn();
    render(<CalendarFilters value={DEFAULT_FILTERS} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "High" }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ impacts: ["MEDIUM"] }));
  });

  it("adds an inactive impact when its toggle is clicked", async () => {
    const onChange = vi.fn();
    render(<CalendarFilters value={DEFAULT_FILTERS} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Low" }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ impacts: ["HIGH", "MEDIUM", "LOW"] }));
  });

  it("toggles the affects-my-book filter", async () => {
    const onChange = vi.fn();
    render(<CalendarFilters value={DEFAULT_FILTERS} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Affects my book" }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ affectsMyBookOnly: true }));
  });

  it("selects a horizon and marks the active one pressed", async () => {
    const onChange = vi.fn();
    render(<CalendarFilters value={DEFAULT_FILTERS} onChange={onChange} />);
    expect(screen.getByRole("button", { name: "7d" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "Today" }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ horizon: "today" }));
  });
});
