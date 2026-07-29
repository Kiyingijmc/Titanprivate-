import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ReadOnlyProvider } from "@/context/ReadOnlyContext";
import { ControllerProvider } from "@/context/ControllerContext";
import type { Api } from "@/lib/api";
import StrategiesPage from "./StrategiesPage";

function fakeApi(overrides: Partial<Api> = {}): Api {
  return {
    getState: vi.fn(),
    getEvents: vi.fn(),
    getHistory: vi.fn(),
    getSettings: vi.fn(),
    getRegistry: vi.fn().mockResolvedValue([]),
    postCommand: vi.fn(),
    patchSetting: vi.fn(),
    registryAction: vi.fn().mockResolvedValue({ status: "ok" }),
    ...overrides,
  } as unknown as Api;
}

function renderPage(api: Api) {
  return render(
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
          <StrategiesPage />
        </ControllerProvider>
      </ReadOnlyProvider>
    </MemoryRouter>
  );
}

describe("StrategiesPage", () => {
  it("renders a research strategy id inside a titled Strategies Panel", async () => {
    const api = fakeApi({
      getRegistry: vi.fn().mockResolvedValue([
        { id: "gyroscope", version: "0.1", status: "research", state: "LOADED" },
      ]),
    });
    renderPage(api);

    expect(await screen.findByText("Strategies")).toBeInTheDocument();
    expect(await screen.findByText("gyroscope")).toBeInTheDocument();
  });

  it("shows Panel error state with Retry when getRegistry rejects, then recovers on retry", async () => {
    const getRegistry = vi
      .fn()
      .mockRejectedValueOnce({ status: 500, kind: "error", detail: "boom" })
      .mockResolvedValue([
        { id: "gyroscope", version: "0.1", status: "research", state: "LOADED" },
      ]);
    const api = fakeApi({ getRegistry });
    renderPage(api);

    const retryBtn = await screen.findByRole("button", { name: /retry/i });
    expect(retryBtn).toBeInTheDocument();
    expect(screen.queryByText("gyroscope")).not.toBeInTheDocument();

    await userEvent.click(retryBtn);

    expect(await screen.findByText("gyroscope")).toBeInTheDocument();
  });

  it("flips read-only on a 403 from a registry mutation, disabling further actions", async () => {
    const api = fakeApi({
      getRegistry: vi.fn().mockResolvedValue([
        { id: "antibody", version: "1.0", status: "live", state: "ACTIVE" },
      ]),
      registryAction: vi.fn().mockRejectedValue({ status: 403, kind: "readOnly", detail: "read only" }),
    });
    renderPage(api);

    const enableBtn = await screen.findByRole("button", { name: /^enable$/i });
    await userEvent.click(enableBtn);

    const buttons = await screen.findAllByRole("button", { name: /^(enable|disable|promote)$/i });
    for (const b of buttons) {
      expect(b).toBeDisabled();
    }
  });
});
