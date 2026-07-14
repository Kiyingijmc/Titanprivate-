import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrategiesTab } from "./StrategiesTab";

function api(rows: any[], overrides: Record<string, any> = {}) {
  return {
    getRegistry: vi.fn().mockResolvedValue(rows),
    registryAction: vi.fn().mockResolvedValue({ status: "ok" }),
    ...overrides,
  } as any;
}

describe("StrategiesTab promote", () => {
  it("requires typed id before confirming promote", async () => {
    const a = api([{ id: "gyroscope", version: "0.1", status: "research", state: "LOADED" }]);
    render(<StrategiesTab api={a} readOnly={false} />);
    await userEvent.click(await screen.findByRole("button", { name: /promote/i }));
    const confirm = screen.getByRole("button", { name: /confirm promote/i });
    expect(confirm).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/type the strategy id/i), "gyroscope");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    expect(a.registryAction).toHaveBeenCalledWith("gyroscope", "promote", { confirm: "gyroscope" });
  });

  it("does not enable confirm on a partial or mismatched id", async () => {
    const a = api([{ id: "gyroscope", version: "0.1", status: "research", state: "LOADED" }]);
    render(<StrategiesTab api={a} readOnly={false} />);
    await userEvent.click(await screen.findByRole("button", { name: /promote/i }));
    const confirm = screen.getByRole("button", { name: /confirm promote/i });
    await userEvent.type(screen.getByLabelText(/type the strategy id/i), "gyro");
    expect(confirm).toBeDisabled();
  });
});

describe("StrategiesTab enable/disable", () => {
  it("calls registryAction with enable/disable for the row id", async () => {
    const a = api([{ id: "antibody", version: "1.0", status: "live", state: "ACTIVE" }]);
    render(<StrategiesTab api={a} readOnly={false} />);
    await userEvent.click(await screen.findByRole("button", { name: /^enable$/i }));
    expect(a.registryAction).toHaveBeenCalledWith("antibody", "enable");

    await userEvent.click(screen.getByRole("button", { name: /^disable$/i }));
    expect(a.registryAction).toHaveBeenCalledWith("antibody", "disable");
  });

  it("disables all mutating buttons in read-only mode", async () => {
    const a = api([{ id: "antibody", version: "1.0", status: "live", state: "ACTIVE" }]);
    render(<StrategiesTab api={a} readOnly />);
    const buttons = await screen.findAllByRole("button");
    buttons.forEach((b) => expect(b).toBeDisabled());
  });
});

describe("StrategiesTab rendering", () => {
  it("does not crash when getRegistry rejects", async () => {
    const a = {
      getRegistry: vi.fn().mockRejectedValue({ status: 500, kind: "error", detail: "boom" }),
      registryAction: vi.fn(),
    } as any;
    render(<StrategiesTab api={a} readOnly={false} />);
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });
});
