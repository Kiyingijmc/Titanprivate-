import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SideChip } from "./SideChip";

describe("SideChip", () => {
  it("tags BUY as profit-tone and SELL as loss-tone", () => {
    const { rerender } = render(<SideChip side="BUY" />);
    expect(screen.getByText("BUY").getAttribute("data-tone")).toBe("profit");
    rerender(<SideChip side="SELL" />);
    expect(screen.getByText("SELL").getAttribute("data-tone")).toBe("loss");
  });
});
