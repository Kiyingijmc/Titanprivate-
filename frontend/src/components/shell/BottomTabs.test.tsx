import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { BottomTabs } from "./BottomTabs";

describe("BottomTabs", () => {
  it("renders the phone glance sections as links", () => {
    render(
      <MemoryRouter>
        <BottomTabs />
      </MemoryRouter>
    );
    for (const label of ["Overview", "Positions", "Activity"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
    // glance-only: no full-control sections in the bottom bar
    expect(screen.queryByRole("link", { name: "Settings" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Strategies" })).toBeNull();
  });
});
