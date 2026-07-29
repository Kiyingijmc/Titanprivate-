import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Panel } from "./Panel";

describe("Panel", () => {
  it("error shows Retry that fires onRetry", async () => {
    const onRetry = vi.fn();
    render(<Panel status="error" onRetry={onRetry}>x</Panel>);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalled();
  });
  it("empty shows message; loading shows skeleton; stale marks children", () => {
    const { rerender } = render(<Panel status="empty" emptyMessage="No positions">x</Panel>);
    expect(screen.getByText("No positions")).toBeInTheDocument();
    rerender(<Panel status="loading">x</Panel>);
    expect(screen.getByTestId("skeleton")).toBeInTheDocument();
    rerender(<Panel status="stale"><span>rows</span></Panel>);
    expect(screen.getByText("rows")).toBeInTheDocument();
    expect(screen.getByTestId("stale-marker")).toBeInTheDocument();
  });
});
