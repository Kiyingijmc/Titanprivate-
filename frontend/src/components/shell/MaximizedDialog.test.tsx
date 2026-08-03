import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MaximizedDialog } from "./MaximizedDialog";
import { MaximizeButton } from "./MaximizeButton";

describe("MaximizedDialog", () => {
  it("renders nothing while closed", () => {
    render(
      <MaximizedDialog open={false} onOpenChange={() => {}} title="Equity">
        <p>chart goes here</p>
      </MaximizedDialog>
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("chart goes here")).not.toBeInTheDocument();
  });

  it("exposes an accessible name from its title and renders children when open", () => {
    render(
      <MaximizedDialog open onOpenChange={() => {}} title="Equity">
        <p>chart goes here</p>
      </MaximizedDialog>
    );
    expect(screen.getByRole("dialog", { name: "Equity" })).toBeInTheDocument();
    expect(screen.getByText("chart goes here")).toBeInTheDocument();
  });

  it("asks to close on Escape", async () => {
    const onOpenChange = vi.fn();
    render(
      <MaximizedDialog open onOpenChange={onOpenChange} title="Equity">
        <p>chart goes here</p>
      </MaximizedDialog>
    );
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("MaximizeButton", () => {
  it("is named for the panel it maximizes and calls back on click", async () => {
    const onClick = vi.fn();
    render(<MaximizeButton title="Equity" onClick={onClick} />);
    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
