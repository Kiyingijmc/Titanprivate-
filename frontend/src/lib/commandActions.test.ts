import { describe, it, expect, vi } from "vitest";
import type { Api } from "./api";
import { buildCommandActions } from "./commandActions";

function makeApi(): Api {
  return {
    getState: vi.fn(),
    getEvents: vi.fn(),
    getHistory: vi.fn(),
    getSettings: vi.fn(),
    getRegistry: vi.fn(),
    postCommand: vi.fn().mockResolvedValue({ ok: true }),
    patchSetting: vi.fn(),
    registryAction: vi.fn(),
  } as unknown as Api;
}

describe("buildCommandActions", () => {
  it("marks every action disabled when readOnly", () => {
    const api = makeApi();
    const actions = buildCommandActions({
      paused: false,
      readOnly: true,
      run: vi.fn(),
      api,
      requestConfirm: vi.fn(),
    });

    expect(actions.length).toBeGreaterThan(0);
    for (const action of actions) {
      expect(action.disabled).toBe(true);
    }
  });

  it("paused:false includes a pause action whose run() posts {command:'pause'} via the injected run", () => {
    const api = makeApi();
    const run = vi.fn();
    const actions = buildCommandActions({
      paused: false,
      readOnly: false,
      run,
      api,
      requestConfirm: vi.fn(),
    });

    const pause = actions.find((a) => a.id === "pause");
    expect(pause).toBeDefined();
    expect(actions.find((a) => a.id === "resume")).toBeUndefined();

    pause!.run();

    expect(run).toHaveBeenCalledTimes(1);
    const fn = run.mock.calls[0][0] as () => Promise<unknown>;
    fn();
    expect(api.postCommand).toHaveBeenCalledWith({ command: "pause" });
  });

  it("paused:true includes a resume action (not pause)", () => {
    const api = makeApi();
    const run = vi.fn();
    const actions = buildCommandActions({
      paused: true,
      readOnly: false,
      run,
      api,
      requestConfirm: vi.fn(),
    });

    const resume = actions.find((a) => a.id === "resume");
    expect(resume).toBeDefined();
    expect(actions.find((a) => a.id === "pause")).toBeUndefined();

    resume!.run();
    expect(run).toHaveBeenCalledTimes(1);
    const fn = run.mock.calls[0][0] as () => Promise<unknown>;
    fn();
    expect(api.postCommand).toHaveBeenCalledWith({ command: "resume" });
  });

  it("closeall and panic are destructive and route through requestConfirm, never api.postCommand directly", () => {
    const api = makeApi();
    const run = vi.fn();
    const requestConfirm = vi.fn();
    const actions = buildCommandActions({
      paused: false,
      readOnly: false,
      run,
      api,
      requestConfirm,
    });

    const closeall = actions.find((a) => a.id === "closeall");
    const panic = actions.find((a) => a.id === "panic");
    expect(closeall).toBeDefined();
    expect(panic).toBeDefined();
    expect(closeall!.destructive).toBe(true);
    expect(panic!.destructive).toBe(true);

    closeall!.run();
    panic!.run();

    expect(requestConfirm).toHaveBeenCalledWith({ command: "closeall", label: expect.any(String) });
    expect(requestConfirm).toHaveBeenCalledWith({ command: "panic", label: expect.any(String) });
    expect(run).not.toHaveBeenCalled();
    expect(api.postCommand).not.toHaveBeenCalled();
  });

  it("includes a cancel action that posts {command:'cancel'} via the injected run", () => {
    const api = makeApi();
    const run = vi.fn();
    const actions = buildCommandActions({
      paused: false,
      readOnly: false,
      run,
      api,
      requestConfirm: vi.fn(),
    });

    const cancel = actions.find((a) => a.id === "cancel");
    expect(cancel).toBeDefined();

    cancel!.run();
    expect(run).toHaveBeenCalledTimes(1);
    const fn = run.mock.calls[0][0] as () => Promise<unknown>;
    fn();
    expect(api.postCommand).toHaveBeenCalledWith({ command: "cancel" });
  });
});
