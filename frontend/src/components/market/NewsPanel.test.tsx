import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NewsPanel } from "./NewsPanel";
import type { NewsBlock } from "@/lib/types";

const OK: NewsBlock = {
  status: "ok",
  cache_age_min: 12,
  next: { in_min: 47, title: "Core CPI m/m", currency: "USD", importance: "HIGH",
          forecast: "0.3%", previous: "0.2%", affects: ["EURUSD", "XAUUSD"] },
  blocked_symbols: { GBPJPY: "GBP BOE Rate Decision in 22m" },
};

describe("NewsPanel", () => {
  it("shows an explicit unavailable state with no data", () => {
    render(<NewsPanel />);
    expect(screen.getByTestId("news-panel-empty")).toBeInTheDocument();
  });

  it("shows unavailable when the backend degraded", () => {
    render(<NewsPanel data={{ status: "unavailable" }} />);
    expect(screen.getByTestId("news-panel-empty")).toBeInTheDocument();
  });

  it("renders the next event title and countdown", () => {
    render(<NewsPanel data={OK} />);
    expect(screen.getByText(/Core CPI m\/m/)).toBeInTheDocument();
    expect(screen.getByText(/47m/)).toBeInTheDocument();
  });

  it("lists the affected pairs", () => {
    render(<NewsPanel data={OK} />);
    expect(screen.getByText("EURUSD")).toBeInTheDocument();
    expect(screen.getByText("XAUUSD")).toBeInTheDocument();
  });

  it("names blocked symbols with their reason", () => {
    render(<NewsPanel data={OK} />);
    expect(screen.getByText(/GBPJPY/)).toBeInTheDocument();
    expect(screen.getByText(/BOE Rate Decision/)).toBeInTheDocument();
  });

  it("renders with no next event and no blocks", () => {
    render(<NewsPanel data={{ status: "ok", next: null, blocked_symbols: {} }} />);
    expect(screen.getByTestId("news-panel")).toBeInTheDocument();
    // A healthy-but-quiet calendar must NOT fall into the "unavailable"
    // branch -- silence is indistinguishable from a broken job.
    expect(screen.queryByTestId("news-panel-empty")).not.toBeInTheDocument();
  });

  it("marks a stale calendar", () => {
    render(<NewsPanel data={{ status: "stale", cache_age_min: 3000 }} />);
    expect(screen.getByTestId("news-panel-stale")).toBeInTheDocument();
  });

  it("renders a today strip when today has events", () => {
    render(
      <NewsPanel
        data={{
          ...OK,
          today: [
            { when_utc: "2026-07-30T12:30:00+00:00", title: "Core PCE m/m",
              currency: "USD", forecast: "0.3%", previous: "0.2%",
              affects: ["EURUSD"] },
          ],
        }}
      />
    );
    const strip = screen.getByTestId("news-today-strip");
    expect(strip).toBeInTheDocument();
    expect(within(strip).getByText(/Core PCE m\/m/)).toBeInTheDocument();
    expect(within(strip).getByText("USD")).toBeInTheDocument();
  });

  it("renders no today strip when today is an empty list", () => {
    render(<NewsPanel data={{ ...OK, today: [] }} />);
    expect(screen.queryByTestId("news-today-strip")).not.toBeInTheDocument();
  });

  it("renders no today strip when today is absent", () => {
    render(<NewsPanel data={OK} />);
    expect(screen.queryByTestId("news-today-strip")).not.toBeInTheDocument();
  });

  describe("overflow constraints (spec §4 fix)", () => {
    it("keeps the Economic Calendar title in its own element for truncation", () => {
      // The h3 is a flex container. The title text must live inside its own
      // CHILD ELEMENT, not as a bare text node directly inside the h3 (a bare
      // text node is what text-overflow:ellipsis can never reach).
      //
      // I9: this asserts STRUCTURE, not a Tailwind class string. A
      // `span.truncate` selector is falsifiable in the wrong direction — it
      // goes red if `truncate` is swapped for an equivalent overflow utility
      // (a non-regression), and it stays green for an INERT `truncate` class
      // sitting on the flex container itself rather than the text (the exact
      // defect this test exists to catch — see MarketSessions' status pill).
      // `.children` is Element-only, so a bare text node never appears in it:
      // if the fix regresses to `<h3><Icon/>Economic Calendar</h3>`, no
      // element child's textContent matches and this fails for the right
      // reason regardless of which CSS class does the truncating.
      render(<NewsPanel data={OK} />);
      const header = screen.getByRole("heading", { name: /Economic Calendar/ });
      const titleEl = Array.from(header.children).find(
        (child) => child.textContent?.trim() === "Economic Calendar"
      );
      expect(titleEl).toBeTruthy();
      expect(titleEl?.nodeType).toBe(Node.ELEMENT_NODE);
    });
  });

  it("renders a today title with a url as a link", () => {
    render(
      <NewsPanel
        data={{
          ...OK,
          today: [
            { when_utc: "2026-07-30T12:30:00+00:00", title: "Core PCE m/m",
              currency: "USD", affects: [], url: "https://example.test/pce" },
          ],
        }}
      />
    );
    const link = screen.getByRole("link", { name: /Core PCE m\/m/ });
    expect(link).toHaveAttribute("href", "https://example.test/pce");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("renders a today title without a url as plain text, no link", () => {
    render(
      <NewsPanel
        data={{
          ...OK,
          today: [
            { when_utc: "2026-07-30T12:30:00+00:00", title: "Core PCE m/m",
              currency: "USD", affects: [] },
          ],
        }}
      />
    );
    expect(screen.getByText(/Core PCE m\/m/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Core PCE m\/m/ })).not.toBeInTheDocument();
  });
});

describe("NewsPanel maximize affordance", () => {
  it("renders no maximize control unless onMaximize is provided", () => {
    render(<NewsPanel data={OK} />);
    expect(screen.queryByRole("button", { name: /maximize/i })).not.toBeInTheDocument();
  });

  it("renders a maximize control and calls back", async () => {
    const onMaximize = vi.fn();
    render(<NewsPanel data={OK} onMaximize={onMaximize} />);
    await userEvent.click(screen.getByRole("button", { name: "Maximize Economic Calendar" }));
    expect(onMaximize).toHaveBeenCalledTimes(1);
  });

  it("offers maximize even in the unavailable state", async () => {
    const onMaximize = vi.fn();
    render(<NewsPanel onMaximize={onMaximize} />);
    await userEvent.click(screen.getByRole("button", { name: "Maximize Economic Calendar" }));
    expect(onMaximize).toHaveBeenCalledTimes(1);
  });
});
