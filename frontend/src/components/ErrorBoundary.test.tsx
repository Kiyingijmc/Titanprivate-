import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom(): JSX.Element {
  throw new Error("kaboom in a section");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    // React logs the caught error; silence the expected noise for a clean run.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders children when they do not throw", () => {
    render(
      <ErrorBoundary>
        <div>healthy child</div>
      </ErrorBoundary>
    );
    expect(screen.getByText("healthy child")).toBeInTheDocument();
  });

  it("shows a themed fallback with the error message and a reload action when a child throws", () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/control panel hit an error/i)).toBeInTheDocument();
    expect(screen.getByText(/kaboom in a section/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload the panel/i })).toBeInTheDocument();
  });
});
