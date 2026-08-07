#!/usr/bin/env node
/**
 * Prints the probe and driving recipe for the exact measurement that found the
 * market-context strip overflow (sub-project D, 2026-08-04): for every element
 * in the strip, compare scrollWidth against clientWidth (falling back to
 * getBoundingClientRect().width for inline elements, which report 0 for
 * clientWidth), and flag any single-line row that has grown taller than its
 * own computed line-height (the wrap tell — "New York" measured 40px against
 * a ~20px line).
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
import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const URL = process.env.STRIP_URL ?? "http://127.0.0.1:8899";
const TOKEN = process.env.TITAN_GUI_TOKEN ?? "layoutcheck";
const WIDTHS = [1920, 1440, 1280];
// Multiplier over the element's OWN computed line-height, not a fixed pixel
// value. A fixed SINGLE_LINE_MAX_PX=24 false-positived on text-3xl leaves
// (LocalityClock's clock is ~30px) and on deliberately two-line empty states,
// so "zero findings" was unattainable and the gate got hand-waved (I4).
const LINE_HEIGHT_MULTIPLIER = 1.4;

/**
 * Runs in the page. Returns a plain JSON string so it survives serialisation
 * across the browse daemon's `js` command.
 *
 * Card selectors are asserted INDEPENDENTLY (I1): the old `cards.length < 4`
 * guard was satisfied by the four session chips alone, so renaming
 * `locality-clock`, `dollar-bias`, or `news-panel` (or the `market-sessions`
 * card added below, I2) would still report a clean run.
 */
const PROBE = `(() => {
  const findings = [];

  const SELECTORS = {
    'session-chip': '[data-testid^="session-chip-"]',
    // I2: the probe never measured the Market Sessions CARD itself — only its
    // chips — so the <h3>, the overlap badge, and the timeline went unmeasured.
    'market-sessions': '[data-testid="market-sessions"]',
    'locality-clock': '[data-testid="locality-clock"]',
    'dollar-bias': '[data-testid="dollar-bias"]',
    'news-panel': '[data-testid="news-panel"]',
  };

  for (const [name, selector] of Object.entries(SELECTORS)) {
    if (document.querySelectorAll(selector).length < 1) {
      findings.push({ kind: 'PROBE_BROKEN',
        detail: \`selector "\${selector}" (\${name}) matched 0 elements — stale testid, NOT a clean run\` });
    }
  }
  if (findings.some((f) => f.kind === 'PROBE_BROKEN')) return JSON.stringify(findings);

  const cards = document.querySelectorAll(Object.values(SELECTORS).join(', '));

  // I3: an element whose only element children are aria-hidden (e.g. the open
  // status pill: a coloured dot + its text) is still effectively a leaf for
  // overflow purposes — the old 'el.children.length > 0' bail skipped it
  // entirely, missing exactly the pattern this program keeps getting wrong.
  function isLeafLike(el) {
    if (el.children.length === 0) return true;
    return Array.from(el.children).every((c) => c.hasAttribute('aria-hidden'));
  }

  cards.forEach((card) => {
    const id = card.getAttribute('data-testid');
    card.querySelectorAll('*').forEach((el) => {
      if (!isLeafLike(el)) return;
      const text = (el.textContent || '').trim();
      if (!text) return;

      // I3: clientWidth is 0 for inline elements (e.g. a bare <span> without
      // a flex/inline-block display) — fall back to the layout box width.
      const rectWidth = el.getBoundingClientRect().width;
      const visibleWidth = Math.max(el.clientWidth, rectWidth);
      if (el.scrollWidth > visibleWidth + 1) {
        findings.push({ card: id, text, kind: 'CLIPPED',
                        scrollW: el.scrollWidth, clientW: el.clientWidth, rectW: Math.round(rectWidth) });
      }

      // I4: compare against the element's OWN computed line-height, not a
      // fixed pixel constant. 'normal' has no numeric parse, so fall back to
      // the CSS-default ~1.2x font-size approximation in that case.
      const cs = getComputedStyle(el);
      let lineHeight = parseFloat(cs.lineHeight);
      if (!Number.isFinite(lineHeight)) {
        lineHeight = (parseFloat(cs.fontSize) || 16) * 1.2;
      }
      const h = el.getBoundingClientRect().height;
      if (h > ${LINE_HEIGHT_MULTIPLIER} * lineHeight) {
        findings.push({ card: id, text, kind: 'WRAPPED', height: Math.round(h), lineHeight: Math.round(lineHeight) });
      }
    });
  });
  return JSON.stringify(findings);
})()`;

console.log(`Measuring ${URL} at ${WIDTHS.join(", ")}px`);
console.log("--- PROBE (paste verbatim into `$B js`) ---");
console.log(PROBE);
console.log("--- end probe ---");

// I5: the old version never printed the probe itself — only "probe ready" and
// a recipe telling the reader to paste "<the PROBE constant from this file>",
// which is a literal placeholder (invalid JS) and can't survive shell quoting
// anyway. Write the real probe to a temp file so the recipe below is a command
// that actually runs, not a fill-in-the-blank.
const probeFile = join(tmpdir(), "titan-strip-overflow-probe.js");
writeFileSync(probeFile, PROBE, "utf8");

console.log(`
Probe written to ${probeFile}. Drive this through the browse daemon:

  B="$HOME/.claude/skills/gstack/browse/dist/browse"
  $B goto ${URL}
  # authenticate with the token ${TOKEN} on first load
  for w in ${WIDTHS.join(" ")}; do
    $B viewport \${w}x900
    $B js "$(cat ${probeFile})"
  done

Any CLIPPED or WRAPPED finding, or any PROBE_BROKEN finding (a stale
selector), is a regression. Zero findings at all three widths is the
requirement.
`);
