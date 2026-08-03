import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Panel } from "./Panel";

describe("Panel", () => {
  it("error shows Retry that fires onRetry", async () => {
    const onRetry = vi.fn();
    render(<Panel status="error" onRetry={onRetry}>x</Panel>);
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalled();
  });
  it("empty shows message; loading shows skeleton; stale marks children", () => {
    const { rerender } = render(<Panel status="empty" emptyMessage="No positions">x</Panel>);
    expect(screen.getByText("No positions")).toBeInTheDocument();
    rerender(<Panel status="loading">x</Panel>);
    expect(screen.getByTestId("skeleton")).toBeInTheDocument();
    rerender(<Panel status="stale"><span>rows</span></Panel>);
    expect(screen.getByText("rows")).toBeInTheDocument();
    expect(screen.getByTestId("stale-marker")).toBeInTheDocument();
  });
});

describe("Panel maximize affordance", () => {
  it("renders no maximize control unless onMaximize is provided", () => {
    render(<Panel status="populated" title="Equity">body</Panel>);
    expect(screen.queryByRole("button", { name: /maximize/i })).not.toBeInTheDocument();
  });

  it("renders a maximize control named for the panel and calls back", async () => {
    const onMaximize = vi.fn();
    render(
      <Panel status="populated" title="Equity" onMaximize={onMaximize}>
        body
      </Panel>
    );
    await userEvent.click(screen.getByRole("button", { name: "Maximize Equity" }));
    expect(onMaximize).toHaveBeenCalledTimes(1);
  });
});

describe("Panel domain tint", () => {
  it("renders no domain marker unless a domain is given", () => {
    const { container } = render(<Panel status="populated" title="Plain">body</Panel>);
    expect(container.querySelector("[data-domain]")).toBeNull();
  });

  it("marks the panel with its domain so the tint is inspectable", () => {
    const { container } = render(
      <Panel status="populated" title="Risk" domain="risk">body</Panel>
    );
    expect(container.querySelector('[data-domain="risk"]')).not.toBeNull();
  });

  it("keeps rendering its children and title with a domain set", () => {
    render(<Panel status="populated" title="Risk" domain="risk">tinted body</Panel>);
    expect(screen.getByText("tinted body")).toBeInTheDocument();
    expect(screen.getByText("Risk")).toBeInTheDocument();
  });

  // Deliberate, narrow exception to the no-Tailwind-class-string-assertion rule
  // (same shape as the `bg-surface-1` guard above): the failure mode here is a
  // class being ABSENT from the header, which a presence assertion can prove
  // (it cannot prove a colour resolves — that needs the browser pass). Mutation
  // this guards against: removing `domain && DOMAIN_HEADER[domain]` from the
  // `CardHeader`'s className turns this red.
  it("washes the header background with the domain colour, and only when a domain is given", () => {
    render(<Panel status="populated" title="Plain">body</Panel>);
    const plainHeader = screen.getByText("Plain").parentElement as HTMLElement;
    expect(plainHeader.className).not.toMatch(/bg-domain-/);

    render(<Panel status="populated" title="Risk" domain="risk">body</Panel>);
    const tintedHeader = screen.getByText("Risk").parentElement as HTMLElement;
    expect(tintedHeader.className).toMatch(/bg-domain-risk\//);
  });
});

describe("Panel status tint (spec §8)", () => {
  it("marks a stale panel so the warning tint is inspectable", () => {
    const { container } = render(<Panel status="stale" title="S">body</Panel>);
    expect(container.querySelector('[data-tone="stale"]')).not.toBeNull();
  });

  it("marks an error panel", () => {
    const { container } = render(<Panel status="error" title="E" />);
    expect(container.querySelector('[data-tone="error"]')).not.toBeNull();
  });

  it("leaves a healthy panel untoned", () => {
    const { container } = render(<Panel status="populated" title="P">body</Panel>);
    expect(container.querySelector("[data-tone]")).toBeNull();
  });

  it("still shows the stale marker and children (tint is additive, not a replacement)", () => {
    render(<Panel status="stale" title="S">stale body</Panel>);
    expect(screen.getByTestId("stale-marker")).toBeInTheDocument();
    expect(screen.getByText("stale body")).toBeInTheDocument();
  });

  // PLAN DEFECT override: the brief's mechanism applies the status tint as a
  // second `bg-*` utility merged via `cn()` onto the same Card that already
  // carries `bg-surface-1`. `cn` is `twMerge(clsx(...))`, and tailwind-merge
  // treats both as background-color utilities — the later one wins and
  // `bg-surface-1` is dropped, so a stale/error panel would lose its card
  // surface entirely. This is a deliberate, narrow exception to the
  // no-Tailwind-class-string-assertion rule: the failure mode here IS a class
  // being elided by tailwind-merge, which is exactly what a class-presence
  // assertion can prove (a resolved-colour assertion could not, since jsdom
  // computes no colour). Mutation this guards against: reverting the
  // `STATUS_TONE` implementation to plain `bg-warning/[0.07]` / `bg-loss/[0.07]`
  // classes applied directly to the Card (instead of the `::before` overlay)
  // turns this test red.
  it("keeps bg-surface-1 on the Card even when a status tone is applied", () => {
    const { container } = render(<Panel status="stale" title="S">body</Panel>);
    const card = container.firstElementChild as HTMLElement;
    expect(card.className.split(/\s+/)).toContain("bg-surface-1");
  });
});
