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

  it("returns to the gate with an error message when children report an invalid token", async () => {
    render(
      <TokenGate>
        {(token, onInvalid) => (
          <div>
            <span>token:{token}</span>
            <button onClick={() => onInvalid("Invalid or expired token — please reconnect.")}>reject</button>
          </div>
        )}
      </TokenGate>
    );
    await userEvent.type(screen.getByLabelText(/token/i), "sekret");
    await userEvent.click(screen.getByRole("button", { name: /connect/i }));
    expect(screen.getByText("token:sekret")).toBeInTheDocument();

    // The live layer rejects the token → back to the gate with the message.
    await userEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(screen.queryByText(/token:/)).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent(/invalid or expired token/i);
    expect(screen.getByLabelText(/token/i)).toBeInTheDocument();
  });
});
