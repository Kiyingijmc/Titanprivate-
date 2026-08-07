import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { SESSIONS } from "@/lib/sessions";
import { MarketSessions } from "./MarketSessions";

describe("MarketSessions", () => {
  it("shows London and New York as Open during their overlap window", () => {
    // 2026-07-15 14:00 UTC — both London (BST, 07-16 UTC) and New York
    // (EDT, 12-21 UTC) are open; classic London<->NY overlap.
    const now = new Date("2026-07-15T14:00:00Z");
    render(<MarketSessions now={now} />);

    const londonChip = screen.getByTestId("session-chip-london");
    const nyChip = screen.getByTestId("session-chip-newyork");
    expect(within(londonChip).getByText(/open/i)).toBeInTheDocument();
    expect(within(nyChip).getByText(/open/i)).toBeInTheDocument();

    // overlap callout should surface somewhere on the page
    expect(screen.getByText(/overlap/i)).toBeInTheDocument();
  });

  it("shows an 'Opens in' countdown for a session that hasn't opened yet", () => {
    // 2026-07-15 03:00 UTC — Sydney is open (BST offset aside, Sydney's
    // local window is 07-16 local = ~21:00-06:00 UTC in July, AEST no DST),
    // but Tokyo (00:00-09:00 UTC) is open and London hasn't opened yet
    // (London opens 07:00 UTC in July). Assert London shows a countdown.
    const now = new Date("2026-07-15T03:00:00Z");
    render(<MarketSessions now={now} />);
    const londonChip = screen.getByTestId("session-chip-london");
    expect(within(londonChip).getByText(/opens in/i)).toBeInTheDocument();
  });

  it("shows a weekend-closed banner on Saturday for an FX-only book", () => {
    const now = new Date("2026-07-18T12:00:00Z"); // Saturday
    render(<MarketSessions now={now} />);
    expect(screen.getByText(/markets closed/i)).toBeInTheDocument();
  });

  // Regression for the 2026-08-02 operator report: the card claimed "Markets
  // closed" on a Sunday while the engine was trading ETHUSD, and it rendered a
  // live session-overlap badge on top of that same banner.
  describe("with a 24/7 instrument in the book", () => {
    const sunday = new Date("2026-08-02T07:14:00Z");

    it("keeps the timeline instead of the closed banner", () => {
      render(<MarketSessions now={sunday} hasCrypto />);
      expect(screen.queryByTestId("weekend-closed-banner")).not.toBeInTheDocument();
      expect(screen.getByTestId("session-timeline")).toBeInTheDocument();
    });

    it("explains that FX is shut but the engine is live", () => {
      render(<MarketSessions now={sunday} hasCrypto />);
      expect(screen.getByTestId("crypto-only-note")).toBeInTheDocument();
    });

    it("still shows the closed banner when the book is FX-only", () => {
      render(<MarketSessions now={sunday} hasCrypto={false} />);
      expect(screen.getByTestId("weekend-closed-banner")).toBeInTheDocument();
    });
  });

  it("never shows an overlap badge while FX is closed", () => {
    // Sunday 07:14Z: Tokyo and London both compute as 'open' on their own
    // clocks, so the badge used to render directly above "Markets closed".
    const sunday = new Date("2026-08-02T07:14:00Z");
    render(<MarketSessions now={sunday} />);
    expect(screen.queryByText(/overlap/i)).not.toBeInTheDocument();
  });

  // Guard for the session-colour token migration. SESSION_COLORS values are
  // full `hsl(var(--session-<id>))` strings consumed from inline `style`, not
  // Tailwind classes — so this component is the one place where a broken
  // migration (e.g. still appending a hex-alpha suffix like "B3"/"14"/"26"
  // onto an hsl(var(...)) string) produces INVALID CSS that a browser drops,
  // rendering the session bands/chips fully transparent. No unit test on
  // text/test-ids can see that. jsdom, unlike a real browser, does NOT
  // validate `var()` colours — it stores whatever string was assigned to
  // `style.backgroundColor`/`style.boxShadow` verbatim, broken or not — so the
  // broken form IS visible here via the DOM, with no production change needed.
  it("never emits a broken hex-alpha suffix on a session token colour", () => {
    const now = new Date("2026-07-15T14:00:00Z"); // London×NY overlap: everything renders
    const { container } = render(<MarketSessions now={now} />);

    // Every session band and chip inline style references a `--session-*`
    // custom property. If this matched nothing, assertion (b) below would
    // pass vacuously and prove nothing — so first prove the selector actually
    // found the elements under test.
    const styledNodes = container.querySelectorAll('[style*="--session-"]');
    expect(styledNodes.length).toBeGreaterThanOrEqual(4);

    const brokenConcatenation = /hsl\(var\(--session-[a-z]+\)\)[0-9A-Fa-f]{2}/;
    for (const node of styledNodes) {
      const style = node.getAttribute("style") ?? "";
      expect(style).not.toMatch(brokenConcatenation);
    }
  });
});

describe("SessionChip layout (spec §3)", () => {
  // 2026-08-04 08:30 UTC. VERIFIED against Intl, not reasoned about:
  //   sydney  local 18:30, window 7-16  => closed
  //   tokyo   local 17:30, window 9-18  => OPEN
  //   london  local 09:30, window 8-17  => OPEN
  //   newyork local 04:30, window 8-17  => closed
  // Pinning `now` is mandatory: sessionStates() reads the wall clock, so an
  // unpinned test passes or fails depending on the hour it runs, and never
  // exercises the strings that actually break the layout.
  const NOW = new Date("2026-08-04T08:30:00Z");

  it("gives an OPEN session a clock row", () => {
    render(<MarketSessions now={NOW} />);
    const chip = screen.getByTestId("session-chip-london");
    expect(chip.querySelector('[data-testid="session-clock"]')).not.toBeNull();
  });

  it("gives a CLOSED session no clock row", () => {
    // The mutation this kills: rendering the clock unconditionally, which is
    // exactly what the pre-fix component did and what caused the overflow.
    render(<MarketSessions now={NOW} />);
    const chip = screen.getByTestId("session-chip-sydney");
    expect(chip.querySelector('[data-testid="session-clock"]')).toBeNull();
  });

  it("renders both states at this fixture — so neither assertion above is vacuous", () => {
    render(<MarketSessions now={NOW} />);
    expect(screen.getByTestId("session-chip-london").querySelector('[data-testid="session-clock"]')).not.toBeNull();
    expect(screen.getByTestId("session-chip-sydney").querySelector('[data-testid="session-clock"]')).toBeNull();
  });

  it("shows the closes-in countdown on an open chip, not a bare 'Open'", () => {
    // sessions.ts:127 already computes `Open · closes in Xh Ym` and the chip
    // threw it away for a hardcoded "Open". This surfaces it.
    render(<MarketSessions now={NOW} />);
    const status = screen.getByTestId("session-chip-london").querySelector('[data-testid="session-status"]')!;
    expect(status.textContent).toMatch(/Open/);
    expect(status.textContent).toMatch(/\d+m/);   // a countdown is present
  });

  it("shows the opens-in countdown on a closed chip", () => {
    render(<MarketSessions now={NOW} />);
    const status = screen.getByTestId("session-chip-sydney").querySelector('[data-testid="session-status"]')!;
    expect(status.textContent).toMatch(/\d+m/);
    expect(status.textContent).not.toMatch(/^Open\b/);
  });

  it("exercises a MAXIMUM-WIDTH countdown, not a convenient short one", () => {
    // Verified: at this `now`, sydney reads "Opens in 12h 30m" — two-digit
    // hours, which is the widest form `fmtCountdown` can emit (`NNh NNm`).
    // WIDTH is what breaks this layout, not magnitude, so 12h 30m pins the
    // same worst case as 23h 59m. A fixture that happened to produce "5m"
    // would look green while never testing the string that overflows.
    render(<MarketSessions now={NOW} />);
    const status = screen.getByTestId("session-chip-sydney").querySelector('[data-testid="session-status"]')!;
    expect(status.textContent).toMatch(/\d{2}h \d{2}m/);
  });

  it("keeps the name and clock as separate rows of the chip, not a shared flex row", () => {
    // The bug this kills: name + clock inside one `justify-between` row, which
    // needed ~118px in a 53px track and clipped every clock mid-digit. Both must
    // be direct children of the chip's flex-col root — if either gets re-wrapped
    // in a shared row, its parent is no longer the root and this fails.
    render(<MarketSessions now={NOW} />);
    const chip = screen.getByTestId("session-chip-london");
    const name = chip.querySelector('[data-testid="session-name"]')!;
    const clock = chip.querySelector('[data-testid="session-clock"]')!;
    expect(name.parentElement).toBe(chip);
    expect(clock.parentElement).toBe(chip);
  });

  it("gives every truncatable span a title, so truncation cannot destroy information", () => {
    render(<MarketSessions now={NOW} />);
    const chip = screen.getByTestId("session-chip-london"); // open: has all three
    for (const id of ["session-name", "session-clock"]) {
      const el = chip.querySelector(`[data-testid="${id}"]`)!;
      expect(el, id).not.toBeNull();
      expect(el.getAttribute("title"), id).toBe(el.textContent);
    }
    // session-status is special (Critical-1 fix): the visible text is a
    // SHORTENED reformat ("Open · 3h 12m"), not a CSS truncation of the full
    // label ("Open · closes in 3h 12m") — the word "closes in" is missing from
    // the MIDDLE, not the end, so `title` is not literally a superstring of
    // the visible text (`title.includes(visibleText)` would be false even
    // though `title` is strictly the fuller string). Assert the two
    // properties that actually matter instead: `title` is strictly longer
    // (carries more information) and still contains the exact duration the
    // chip shows (nothing about WHEN it closes was lost, only the "closes in"
    // wording).
    const status = chip.querySelector('[data-testid="session-status"]')!;
    const duration = status.textContent!.replace(/^Open\s*·\s*/, "");
    expect(duration.length).toBeGreaterThan(0); // or the containment check below is vacuous
    expect(status.getAttribute("title")).toContain(duration);
    expect(status.getAttribute("title")!.length).toBeGreaterThan(status.textContent!.length);
  });

  it("wraps the open status text in its own child element, not a bare text node (Critical-1 fix)", () => {
    // The mutation this kills: putting `{shortLabel}` back as a bare text
    // node directly inside the status span (sibling of the aria-hidden dot)
    // instead of inside its own <span>. `.children` is Element-only — a bare
    // text node never shows up in it — so if the fix regresses, no non-hidden
    // element child exists and the lookup below comes back empty.
    render(<MarketSessions now={NOW} />);
    const status = screen.getByTestId("session-chip-london").querySelector('[data-testid="session-status"]')!;
    const textEl = Array.from(status.children).find(
      (child) => !child.hasAttribute("aria-hidden") && (child.textContent?.length ?? 0) > 0
    );
    expect(textEl).toBeTruthy();
    expect(textEl?.textContent).toBe(status.textContent);
  });
});

describe("open/closed status affordance (I8)", () => {
  const NOW = new Date("2026-08-04T08:30:00Z"); // london OPEN, sydney CLOSED

  it("gives an OPEN chip's status pill a coloured dot", () => {
    // The mutation this kills: `session.open ? (...) : (...)` mutated to
    // `false ? (...) : (...)` — every chip (including an actually-open one)
    // would render the closed, dot-less branch, and every EXISTING test above
    // still passes because none of them assert the dot's presence directly.
    render(<MarketSessions now={NOW} />);
    const status = screen.getByTestId("session-chip-london").querySelector('[data-testid="session-status"]')!;
    expect(status.querySelector("[aria-hidden]")).not.toBeNull();
  });

  it("gives a CLOSED chip's status pill no dot", () => {
    render(<MarketSessions now={NOW} />);
    const status = screen.getByTestId("session-chip-sydney").querySelector('[data-testid="session-status"]')!;
    expect(status.querySelector("[aria-hidden]")).toBeNull();
  });
});

describe("chip grid (spec §6)", () => {
  const NOW = new Date("2026-08-04T08:30:00Z");

  it("renders every session in SESSIONS — no chip is dropped by the grid change", () => {
    // Derived from the table, not hard-coded: adding a fifth session extends
    // this guard automatically instead of leaving it silently stale.
    render(<MarketSessions now={NOW} />);
    for (const s of SESSIONS) {
      expect(screen.getByTestId(`session-chip-${s.id}`)).toBeInTheDocument();
    }
    expect(SESSIONS.length).toBeGreaterThan(0);   // or the loop is vacuous
  });
});
