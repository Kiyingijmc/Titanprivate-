import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TokenGate } from "./TokenGate";

describe("TokenGate", () => {
  it("gates children until a token is entered", async () => {
    render(<TokenGate>{(token) => <div>token:{token}</div>}</TokenGate>);
    expect(screen.queryByText(/token:/)).toBeNull();
    await userEvent.type(screen.getByLabelText(/token/i), "sekret");
    await userEvent.click(screen.getByRole("button", { name: /connect/i }));
    expect(screen.getByText("token:sekret")).toBeInTheDocument();
  });
});
