import { describe, it, expect } from "vitest";
import { money, signedPnl, ageLabel } from "./format";

describe("format", () => {
  it("money is fixed-2 with thousands", () => {
    expect(money(10250)).toBe("10,250.00");
    expect(money(-3.5)).toBe("-3.50");
  });
  it("signedPnl tags tone by sign", () => {
    expect(signedPnl(12.5)).toEqual({ text: "+12.50", tone: "profit" });
    expect(signedPnl(-4)).toEqual({ text: "-4.00", tone: "loss" });
    expect(signedPnl(0)).toEqual({ text: "0.00", tone: "flat" });
  });
  it("ageLabel is human", () => {
    expect(ageLabel(2)).toBe("2s");
    expect(ageLabel(125)).toBe("2m 5s");
  });
});
