import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SettingsTab } from "./SettingsTab";

function api(rows: any[], patchSetting = vi.fn().mockResolvedValue({ applied: "ok" })) {
  return {
    getSettings: vi.fn().mockResolvedValue(rows),
    patchSetting,
  } as any;
}

describe("SettingsTab validation errors", () => {
  it("renders a 422 detail inline under the row", async () => {
    const patchSetting = vi.fn().mockRejectedValue({
      status: 422,
      kind: "validation",
      detail: "must be > 0",
    });
    const a = api(
      [{ key: "risk.max_lot", value: 1, source: "override", tier: "live" }],
      patchSetting
    );
    render(<SettingsTab api={a} readOnly={false} />);
    await userEvent.click(await screen.findByRole("button", { name: /save/i }));
    expect(await screen.findByText(/must be > 0/i)).toBeInTheDocument();
    expect(patchSetting).toHaveBeenCalledWith("risk.max_lot", 1);
  });

  it("shows applied/restart_required on a successful save", async () => {
    const patchSetting = vi.fn().mockResolvedValue({ applied: "risk.max_lot", restart_required: false });
    const a = api([{ key: "risk.max_lot", value: 1, source: "override", tier: "live" }], patchSetting);
    render(<SettingsTab api={a} readOnly={false} />);
    await userEvent.click(await screen.findByRole("button", { name: /save/i }));
    expect(await screen.findByText(/applied/i)).toBeInTheDocument();
  });
});

describe("SettingsTab badges", () => {
  it("shows a restart badge for a restart-tier row", async () => {
    const a = api([{ key: "bridge.port", value: 32768, source: "default", tier: "restart" }]);
    render(<SettingsTab api={a} readOnly={false} />);
    expect(await screen.findByText(/restart/i)).toBeInTheDocument();
  });

  it("shows source badges for default and override rows", async () => {
    const a = api([
      { key: "a", value: 1, source: "default", tier: "live" },
      { key: "b", value: 2, source: "override", tier: "live" },
    ]);
    render(<SettingsTab api={a} readOnly={false} />);
    expect(await screen.findByText("default")).toBeInTheDocument();
    expect(screen.getByText("override")).toBeInTheDocument();
  });
});

describe("SettingsTab read-only", () => {
  it("disables inputs and save buttons in read-only mode", async () => {
    const a = api([{ key: "risk.max_lot", value: 1, source: "override", tier: "live" }]);
    render(<SettingsTab api={a} readOnly />);
    expect(await screen.findByRole("button", { name: /save/i })).toBeDisabled();
    expect(screen.getByLabelText(/risk\.max_lot/i)).toBeDisabled();
  });
});
