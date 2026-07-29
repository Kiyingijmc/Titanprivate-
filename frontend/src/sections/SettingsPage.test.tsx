import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ReadOnlyProvider } from "@/context/ReadOnlyContext";
import { ControllerProvider } from "@/context/ControllerContext";
import type { SettingRow } from "@/lib/types";
import type { Api } from "@/lib/api";
import SettingsPage from "./SettingsPage";

const ROWS: SettingRow[] = [
  { key: "signal_grading.min_grade", value: "B", source: "default", tier: "live" },
  { key: "risk.trade.risk_per_trade_pct", value: 1, source: "override", tier: "live" },
  { key: "connection.zeromq.push_port", value: 32768, source: "default", tier: "restart" },
];

function fakeApi(overrides: Partial<Api> = {}): Api {
  return {
    getState: vi.fn(),
    getEvents: vi.fn(),
    getHistory: vi.fn(),
    getSettings: vi.fn().mockResolvedValue(ROWS),
    getRegistry: vi.fn(),
    postCommand: vi.fn(),
    patchSetting: vi.fn().mockResolvedValue({ applied: "ok" }),
    registryAction: vi.fn(),
    ...overrides,
  } as unknown as Api;
}

function renderPage({ api = fakeApi(), readOnly = false }: { api?: Api; readOnly?: boolean } = {}) {
  function Wrapper() {
    return (
      <MemoryRouter>
        <ReadOnlyProvider>
          <ControllerProvider
            value={{
              snapshot: null,
              events: [],
              connectionStatus: { status: "live", stale: false },
              api,
            }}
          >
            <SettingsPage />
          </ControllerProvider>
        </ReadOnlyProvider>
      </MemoryRouter>
    );
  }
  void readOnly;
  const utils = render(<Wrapper />);
  return { ...utils, api };
}

describe("SettingsPage", () => {
  it("loads and renders all rows across domains", async () => {
    renderPage();
    expect(await screen.findByText("signal_grading.min_grade")).toBeInTheDocument();
    expect(screen.getByText("risk.trade.risk_per_trade_pct")).toBeInTheDocument();
    expect(screen.getByText("connection.zeromq.push_port")).toBeInTheDocument();
  });

  it("typing 'connection' in the search filters to only the connection row", async () => {
    renderPage();
    await screen.findByText("signal_grading.min_grade");

    const search = screen.getByRole("textbox", { name: /search settings/i });
    await userEvent.type(search, "connection");

    expect(screen.getByText("connection.zeromq.push_port")).toBeInTheDocument();
    expect(screen.queryByText("signal_grading.min_grade")).not.toBeInTheDocument();
    expect(screen.queryByText("risk.trade.risk_per_trade_pct")).not.toBeInTheDocument();
  });

  it("renders domain group headers", async () => {
    renderPage();
    await screen.findByText("signal_grading.min_grade");

    expect(screen.getByRole("heading", { name: "signal_grading" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "risk" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "connection" })).toBeInTheDocument();
  });

  it("shows a restart badge for the restart-tier row", async () => {
    renderPage();
    expect(await screen.findByText(/restart/i)).toBeInTheDocument();
  });

  it("a patchSetting 422 renders the detail inline near the row", async () => {
    const api = fakeApi({
      patchSetting: vi.fn().mockRejectedValue({ status: 422, kind: "validation", detail: "bad value" }),
    });
    renderPage({ api });
    await screen.findByText("signal_grading.min_grade");

    const saveButtons = await screen.findAllByRole("button", { name: /save/i });
    await userEvent.click(saveButtons[0]);

    expect(await screen.findByText(/bad value/i)).toBeInTheDocument();
  });
});
