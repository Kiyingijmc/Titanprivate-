import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AccentToggle } from "./AccentToggle";

describe("AccentToggle", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("data-accent");
  });

  it("defaults to violet (no data-accent attribute)", () => {
    render(<AccentToggle />);
    expect(screen.getByRole("button", { name: /violet/i })).toBeInTheDocument();
    expect(document.documentElement.getAttribute("data-accent")).toBeNull();
  });

  it("flips to electric blue, sets the html attribute, and persists", async () => {
    render(<AccentToggle />);
    await userEvent.click(screen.getByRole("button", { name: /accent color/i }));
    expect(document.documentElement.getAttribute("data-accent")).toBe("blue");
    expect(localStorage.getItem("titan.accent")).toBe("blue");
    expect(screen.getByRole("button", { name: /electric blue/i })).toBeInTheDocument();
  });

  it("toggles back to violet on a second click, clearing the attribute", async () => {
    render(<AccentToggle />);
    const btn = screen.getByRole("button", { name: /accent color/i });
    await userEvent.click(btn);
    await userEvent.click(btn);
    expect(document.documentElement.getAttribute("data-accent")).toBeNull();
    expect(localStorage.getItem("titan.accent")).toBe("violet");
  });
});
