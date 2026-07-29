import { describe, it, expect } from "vitest";
import { money, signedPnl, ageLabel, price, lots, pnlToneClass } from "./format";

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
  it("price trims float noise and avoids scientific notation", () => {
    expect(price(1.1)).toBe("1.1");
    expect(price(1.08500000001)).toBe("1.085");
    expect(price(0.00001)).toBe("0.00001");   // not 1e-5
    expect(price(91000.5)).toBe("91,000.5");
  });
  it("lots is a stable 2-decimal figure", () => {
    expect(lots(0.1)).toBe("0.10");
    expect(lots(1)).toBe("1.00");
  });
  it("pnlToneClass maps tone to a text color", () => {
    expect(pnlToneClass("profit")).toBe("text-profit");
    expect(pnlToneClass("loss")).toBe("text-loss");
    expect(pnlToneClass("flat")).toBe("text-muted-foreground");
  });
});
