#!/usr/bin/env node
/**
 * Prints the probe and driving recipe for the exact measurement that found the
 * market-context strip overflow (sub-project D, 2026-08-04): for every element
 * in the strip, compare scrollWidth against clientWidth, and flag any
 * single-line row that has grown taller than one line (the wrap tell — "New
 * York" measured 40px against a ~20px line).
 *
 * NOT a Vitest test: jsdom computes no layout, so this can only be answered by
 * a real browser running layout. This script PRINTS the probe and the recipe;
 * it does not open a browser or connect to anything, so it always exits 0. It
 * cannot gate CI on its own — a human or agent must run the printed recipe
 * through the shared `browse` daemon (at $HOME/.claude/skills/gstack/browse/...)
 * and interpret the findings. Making it self-driving would require calling that
 * daemon's HTTP interface; do NOT add puppeteer — this project deliberately
 * keeps one Chromium.
 *
 * Usage:
 *   node frontend/scripts/measure-strip-overflow.mjs
 *
 * This prints the probe and a step-by-step recipe to run it at 1920, 1440, and
 * 1280px widths. Follow those instructions manually, or dispatch an agent to.
 */
const URL = process.env.STRIP_URL ?? "http://127.0.0.1:8899";
const TOKEN = process.env.TITAN_GUI_TOKEN ?? "layoutcheck";
const WIDTHS = [1920, 1440, 1280];
const SINGLE_LINE_MAX_PX = 24;

/** Runs in the page. Returns a plain array so it survives serialisation. */
const PROBE = `(() => {
  const findings = [];

  // Select all four cards: session chips, local time, dollar bias, and news panel
  const CARD_SELECTOR = [
    '[data-testid^="session-chip-"]',
    '[data-testid="locality-clock"]',
    '[data-testid="dollar-bias"]',
    '[data-testid="news-panel"]',
  ].join(", ");

  const cards = document.querySelectorAll(CARD_SELECTOR);

  // Guard: if the selector stops matching, fail loudly rather than report false success
  if (cards.length < 4) {
    return JSON.stringify([{ kind: "PROBE_BROKEN",
      detail: \`expected >=4 strip cards, matched \${cards.length} — the selector is stale, NOT a clean run\` }]);
  }

  cards.forEach((card) => {
    const id = card.getAttribute('data-testid');
    card.querySelectorAll('*').forEach((el) => {
      if (el.children.length > 0) return;            // leaves only
      const text = (el.textContent || '').trim();
      if (!text) return;
      if (el.scrollWidth > el.clientWidth + 1) {
        findings.push({ card: id, text, kind: 'CLIPPED',
                        scrollW: el.scrollWidth, clientW: el.clientWidth });
      }
      const h = el.getBoundingClientRect().height;
      if (h > ${SINGLE_LINE_MAX_PX}) {
        findings.push({ card: id, text, kind: 'WRAPPED', height: Math.round(h) });
      }
    });
  });
  return JSON.stringify(findings);
})()`;

console.log(`Measuring ${URL} at ${WIDTHS.join(", ")}px`);
console.log(PROBE.length > 0 ? "probe ready" : "probe empty");
console.log(`
Drive this through the browse daemon:

  B="$HOME/.claude/skills/gstack/browse/dist/browse"
  $B goto ${URL}
  # authenticate with the token ${TOKEN} on first load
  for w in ${WIDTHS.join(" ")}; do
    $B viewport \${w}x900
    $B js '<the PROBE constant from this file>'
  done

Any CLIPPED or WRAPPED finding is a regression. Zero findings at all three
widths is the requirement.
`);
