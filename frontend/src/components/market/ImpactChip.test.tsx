import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ImpactChip } from "./ImpactChip";

describe("ImpactChip", () => {
  // jsdom resolves no colour, so the colour is NOT asserted here — it is
  // measured in the browser (plan Task 8). What jsdom CAN prove is the half
  // of spec §5 that matters most: the text label always exists.
  it.each([["HIGH", "High"], ["MEDIUM", "Med"], ["LOW", "Low"]] as const)(
    "renders the text label for %s so colour is never the only channel",
    (impact, label) => {
      render(<ImpactChip impact={impact} />);
      expect(screen.getByText(label)).toBeInTheDocument();
    });
});
