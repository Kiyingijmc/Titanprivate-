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

describe("Panel maximize affordance", () => {
  it("renders no maximize control unless onMaximize is provided", () => {
    render(<Panel status="populated" title="Equity">body</Panel>);
    expect(screen.queryByRole("button", { name: /maximize/i })).not.toBeInTheDocument();
  });

  it("renders a maximize control named for the panel and calls back", async () => {
    const onMaximize = vi.fn();
    render(
      <Panel status="populated" title="Equity" onMaximize={onMaximize}>
        body
      </Panel>
    );
    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));
    expect(onMaximize).toHaveBeenCalledTimes(1);
  });
});
