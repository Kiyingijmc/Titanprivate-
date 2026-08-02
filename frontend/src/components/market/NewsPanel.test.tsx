import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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
  });

  it("marks a stale calendar", () => {
    render(<NewsPanel data={{ status: "stale", cache_age_min: 3000 }} />);
    expect(screen.getByTestId("news-panel-stale")).toBeInTheDocument();
  });
});
