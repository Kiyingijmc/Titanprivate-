import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { createElement, useState } from "react";
import { ReadOnlyProvider, useReadOnly } from "../context/ReadOnlyContext";
import { useMutate } from "./useMutation";

function Probe() {
  const { readOnly } = useReadOnly();
  const { run } = useMutate();
  const [result, setResult] = useState("idle");

  return createElement(
    "div",
    null,
    createElement("span", { "data-testid": "readOnly" }, readOnly ? "RO" : "RW"),
    createElement("span", { "data-testid": "result" }, result),
    createElement(
      "button",
      {
        onClick: async () => {
          const r = await run(() => Promise.reject({ status: 403, kind: "readOnly", detail: "ro" }));
          setResult(JSON.stringify(r));
        },
      },
      "ro-trigger"
    ),
    createElement(
      "button",
      {
        onClick: async () => {
          const r = await run(() => Promise.reject({ status: 500, kind: "error", detail: "boom" }));
          setResult(JSON.stringify(r));
        },
      },
      "err-trigger"
    ),
    createElement(
      "button",
      {
        onClick: async () => {
          const r = await run(() => Promise.resolve(42));
          setResult(JSON.stringify(r));
        },
      },
      "ok-trigger"
    )
  );
}

function renderProbe() {
  return render(createElement(ReadOnlyProvider, null, createElement(Probe)));
}

describe("useMutate", () => {
  it("flips readOnly on kind===readOnly and returns ok:false", async () => {
    renderProbe();
    fireEvent.click(screen.getByText("ro-trigger"));
    await waitFor(() => expect(screen.getByTestId("readOnly").textContent).toBe("RO"));
    expect(screen.getByTestId("result").textContent).toBe(JSON.stringify({ ok: false, error: "read-only" }));
  });

  it("surfaces other errors without flipping readOnly", async () => {
    renderProbe();
    fireEvent.click(screen.getByText("err-trigger"));
    await waitFor(() =>
      expect(screen.getByTestId("result").textContent).toBe(JSON.stringify({ ok: false, error: "boom" }))
    );
    expect(screen.getByTestId("readOnly").textContent).toBe("RW");
  });

  it("returns ok:true with value on success", async () => {
    renderProbe();
    fireEvent.click(screen.getByText("ok-trigger"));
    await waitFor(() =>
      expect(screen.getByTestId("result").textContent).toBe(JSON.stringify({ ok: true, value: 42 }))
    );
  });
});
