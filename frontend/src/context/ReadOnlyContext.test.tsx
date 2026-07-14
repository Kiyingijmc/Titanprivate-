import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReadOnlyProvider, useReadOnly } from "./ReadOnlyContext";

function Probe() {
  const { readOnly, setReadOnly } = useReadOnly();
  return <button onClick={() => setReadOnly(true)}>{readOnly ? "RO" : "RW"}</button>;
}
describe("ReadOnlyContext", () => {
  it("defaults RW and flips to RO", () => {
    render(<ReadOnlyProvider><Probe /></ReadOnlyProvider>);
    expect(screen.getByRole("button").textContent).toBe("RW");
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByRole("button").textContent).toBe("RO");
  });
});
