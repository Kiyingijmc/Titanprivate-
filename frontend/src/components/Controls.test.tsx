import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Controls } from "./Controls";

function api() {
  return { postCommand: vi.fn().mockResolvedValue({ status: "ok" }) } as any;
}

describe("Controls", () => {
  it("panic requires dialog confirm before calling api", async () => {
    const a = api();
    render(<Controls api={a} paused={false} readOnly={false} onResult={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /panic/i }));
    expect(a.postCommand).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(a.postCommand).toHaveBeenCalledWith({ command: "panic", confirm: true });
  });

  it("closeall requires dialog confirm before calling api", async () => {
    const a = api();
    render(<Controls api={a} paused={false} readOnly={false} onResult={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /close all/i }));
    expect(a.postCommand).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(a.postCommand).toHaveBeenCalledWith({ command: "closeall", confirm: true });
  });

  it("pause calls the api directly without a dialog", async () => {
    const a = api();
    render(<Controls api={a} paused={false} readOnly={false} onResult={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /^pause$/i }));
    expect(a.postCommand).toHaveBeenCalledWith({ command: "pause" });
  });

  it("resume shows instead of pause once paused, and cancel calls the api directly", async () => {
    const a = api();
    render(<Controls api={a} paused readOnly={false} onResult={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /^resume$/i }));
    expect(a.postCommand).toHaveBeenCalledWith({ command: "resume" });

    await userEvent.click(screen.getByRole("button", { name: /^cancel$/i }));
    expect(a.postCommand).toHaveBeenCalledWith({ command: "cancel" });
  });

  it("surfaces a readOnly ApiError via onResult", async () => {
    const onResult = vi.fn();
    const a = {
      postCommand: vi.fn().mockRejectedValue({ status: 403, kind: "readOnly", detail: "read only" }),
    } as any;
    render(<Controls api={a} paused={false} readOnly={false} onResult={onResult} />);
    await userEvent.click(screen.getByRole("button", { name: /^pause$/i }));
    expect(onResult).toHaveBeenCalledWith({ readOnly: true });
  });

  it("surfaces a non-readOnly command failure as a visible alert (never looks like success)", async () => {
    const onResult = vi.fn();
    const a = {
      postCommand: vi.fn().mockRejectedValue({ status: 500, kind: "error", detail: "bridge down" }),
    } as any;
    render(<Controls api={a} paused={false} readOnly={false} onResult={onResult} />);
    // destructive path: confirm, then the failed call must show an alert
    await userEvent.click(screen.getByRole("button", { name: /panic/i }));
    await userEvent.click(screen.getByRole("button", { name: /confirm/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/panic.*bridge down/i);
    expect(onResult).toHaveBeenCalledWith({ error: "bridge down" });
  });

  it("disables everything in read-only", () => {
    render(<Controls api={api()} paused={false} readOnly onResult={() => {}} />);
    screen.getAllByRole("button").forEach((b) => expect(b).toBeDisabled());
  });
});
