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
    const buttons = await screen.findAllByRole("button", { name: /^(enable|disable|promote)$/i });
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
    expect(await screen.findByText("Could not load the strategy registry.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  });
});


describe("StrategiesTab registry feedback", () => {
  it("fetches once, filters without mutations, and resets matches", async () => {
    const a = api([
      { id: "silver_bullet", version: "1", status: "live", state: "ACTIVE", tf: "H1" },
      { id: "gyroscope", version: "2", status: "research", state: "LOADED", tf: "M15" },
    ]);
    render(<StrategiesTab api={a} readOnly={false} />);
    await screen.findByText("silver_bullet");
    expect(a.getRegistry).toHaveBeenCalledTimes(1);
    await userEvent.selectOptions(screen.getByLabelText("Strategy classification"), "research");
    expect(screen.queryByText("silver_bullet")).not.toBeInTheDocument();
    expect(screen.getByText("gyroscope")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Search strategies"), "missing");
    expect(screen.getByText("No strategies match these filters.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    expect(screen.getByText("silver_bullet")).toBeInTheDocument();
    expect(a.registryAction).not.toHaveBeenCalled();
  });

  it("keeps the last registry and exposes failed refreshes", async () => {
    const a = api([{ id: "silver_bullet", version: "1", status: "live", state: "ACTIVE" }]);
    render(<StrategiesTab api={a} readOnly />);
    await screen.findByText("silver_bullet");
    a.getRegistry.mockRejectedValueOnce(new Error("network unavailable"));
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Refresh failed");
    expect(screen.getByText("silver_bullet")).toBeInTheDocument();
  });

  it("surfaces promotion failure inside the dialog and keeps confirmation disabled in read-only", async () => {
    const a = api([{ id: "gyroscope", version: "2", status: "research", state: "LOADED" }], {
      registryAction: vi.fn().mockRejectedValue(new Error("failure")),
    });
    const { rerender } = render(<StrategiesTab api={a} readOnly={false} />);
    await userEvent.click(await screen.findByRole("button", { name: "Promote" }));
    await userEvent.type(screen.getByLabelText("Type the strategy id"), "gyroscope");
    await userEvent.click(screen.getByRole("button", { name: "Confirm promote" }));
    expect(await screen.findByText("Promotion failed. Please try again.")).toBeInTheDocument();
    rerender(<StrategiesTab api={a} readOnly />);
    expect(screen.getByRole("button", { name: "Confirm promote" })).toBeDisabled();
  });
});


it("shows a controller refusal even when the HTTP request succeeds", async () => {
  const a = api([{ id: "gambit", version: "1", status: "research", state: "LOADED" }], {
    registryAction: vi.fn().mockResolvedValue({ status: "ok", result: "Cannot enable: disabled via config." }),
  });
  render(<StrategiesTab api={a} readOnly={false} />);
  await userEvent.click(await screen.findByRole("button", { name: "Enable" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Cannot enable: disabled via config.");
});
