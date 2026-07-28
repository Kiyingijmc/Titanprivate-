import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { ReadOnlyProvider } from "@/context/ReadOnlyContext";
import { CommandPalette, type PaletteAction } from "./CommandPalette";

// jsdom has no scrollIntoView; cmdk calls it on selection-change to keep the highlighted
// item in view. Stub locally rather than touching the shared vitest.setup.ts.
if (typeof Element.prototype.scrollIntoView !== "function") {
  Element.prototype.scrollIntoView = () => {};
}

/** Renders the current router pathname so navigation can be asserted without mocking useNavigate. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{location.pathname}</div>;
}

function Harness({
  onOpenChange = vi.fn(),
  actions = [],
}: {
  onOpenChange?: (open: boolean) => void;
  actions?: PaletteAction[];
}) {
  return (
    <MemoryRouter initialEntries={["/overview"]}>
      <ReadOnlyProvider>
        <CommandPalette open onOpenChange={onOpenChange} actions={actions} />
        <LocationProbe />
      </ReadOnlyProvider>
    </MemoryRouter>
  );
}

describe("CommandPalette", () => {
  it("renders a searchable combobox with the Navigate group populated", () => {
    render(<Harness />);
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    for (const name of ["Overview", "Positions", "Strategies", "Activity", "Settings"]) {
      expect(screen.getByRole("option", { name })).toBeInTheDocument();
    }
  });

  it("filters items as the operator types", async () => {
    render(<Harness />);
    const input = screen.getByRole("combobox");
    await userEvent.type(input, "Posit");
    expect(screen.getByRole("option", { name: "Positions" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Overview" })).not.toBeInTheDocument();
  });

  it("navigates and closes when a Navigate item is selected", () => {
    const onOpenChange = vi.fn();
    render(<Harness onOpenChange={onOpenChange} />);
    fireEvent.click(screen.getByRole("option", { name: "Positions" }));
    expect(screen.getByTestId("location-probe")).toHaveTextContent("/positions");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("runs a provided action and closes when selected", () => {
    const run = vi.fn();
    const onOpenChange = vi.fn();
    const actions: PaletteAction[] = [{ id: "pause", label: "Pause bot", run }];
    render(<Harness onOpenChange={onOpenChange} actions={actions} />);
    expect(screen.getByRole("option", { name: "Pause bot" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("option", { name: "Pause bot" }));
    expect(run).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("marks a disabled action as disabled and never runs it", () => {
    const run = vi.fn();
    const onOpenChange = vi.fn();
    const actions: PaletteAction[] = [{ id: "closeall", label: "Close all", run, disabled: true }];
    render(<Harness onOpenChange={onOpenChange} actions={actions} />);
    const item = screen.getByRole("option", { name: "Close all" });
    expect(item).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(item);
    expect(run).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("gives destructive actions a distinct visual treatment", () => {
    const actions: PaletteAction[] = [
      { id: "panic", label: "Panic close", run: vi.fn(), destructive: true },
    ];
    render(<Harness actions={actions} />);
    const item = screen.getByRole("option", { name: "Panic close" });
    expect(item.className).toMatch(/text-loss/);
  });
});
