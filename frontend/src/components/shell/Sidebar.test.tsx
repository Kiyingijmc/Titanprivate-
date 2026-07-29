import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { useEffect } from "react";
import { ReadOnlyProvider, useReadOnly } from "@/context/ReadOnlyContext";
import { Sidebar } from "./Sidebar";

function Harness({ collapsed = false, onToggleCollapse = vi.fn() }: { collapsed?: boolean; onToggleCollapse?: () => void }) {
  return (
    <MemoryRouter initialEntries={["/overview"]}>
      <ReadOnlyProvider>
        <Sidebar collapsed={collapsed} onToggleCollapse={onToggleCollapse} />
      </ReadOnlyProvider>
    </MemoryRouter>
  );
}

/** Flips the ReadOnlyContext to read-only on mount, then renders the Sidebar under it. */
function ReadOnlyHarness() {
  function Flip({ children }: { children: React.ReactNode }) {
    const { setReadOnly } = useReadOnly();
    useEffect(() => {
      setReadOnly(true);
    }, [setReadOnly]);
    return <>{children}</>;
  }
  return (
    <MemoryRouter initialEntries={["/overview"]}>
      <ReadOnlyProvider>
        <Flip>
          <Sidebar collapsed={false} onToggleCollapse={vi.fn()} />
        </Flip>
      </ReadOnlyProvider>
    </MemoryRouter>
  );
}

describe("Sidebar", () => {
  it("renders the 5 enabled section nav links", () => {
    render(<Harness />);
    for (const name of ["Overview", "Positions", "Strategies", "Activity", "Settings"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument();
    }
  });

  it("marks Research and Journal as present but disabled", () => {
    render(<Harness />);
    for (const name of ["Research", "Journal"]) {
      const el = screen.getByText(name).closest('[aria-disabled], [disabled]') as HTMLElement | null;
      expect(el).not.toBeNull();
      const isAriaDisabled = el?.getAttribute("aria-disabled") === "true";
      const isDisabled = el?.hasAttribute("disabled");
      expect(isAriaDisabled || isDisabled).toBe(true);
      expect(el?.getAttribute("title")).toMatch(/Phase 2/i);
    }
    // must NOT be real links (react-router NavLinks)
    expect(screen.queryByRole("link", { name: "Research" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Journal" })).not.toBeInTheDocument();
  });

  it("active section gets aria-current", () => {
    render(<Harness />);
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
  });

  it("hides the read-only badge by default", () => {
    render(<Harness />);
    expect(screen.queryByText(/read-only/i)).not.toBeInTheDocument();
  });

  it("shows the read-only badge when the context is read-only", () => {
    render(<ReadOnlyHarness />);
    expect(screen.getByText(/read-only/i)).toBeInTheDocument();
  });

  it("calls onToggleCollapse when the collapse toggle is clicked", async () => {
    const onToggleCollapse = vi.fn();
    render(<Harness onToggleCollapse={onToggleCollapse} />);
    const toggle = screen.getByRole("button", { name: /collapse sidebar/i });
    await userEvent.click(toggle);
    expect(onToggleCollapse).toHaveBeenCalledTimes(1);
  });

  it("shows Expand sidebar accessible name when collapsed", () => {
    render(<Harness collapsed />);
    expect(screen.getByRole("button", { name: /expand sidebar/i })).toBeInTheDocument();
  });

  it("hides nav labels when collapsed (icon-only)", () => {
    render(<Harness collapsed />);
    expect(screen.queryByText("Overview")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument();
  });
});
