#!/usr/bin/env node
/**
 * Prints the probe and driving recipe for the exact measurement that found the
 * market-context strip overflow (sub-project D, 2026-08-04): for every element
 * in the strip, compare scrollWidth against clientWidth (falling back to
 * getBoundingClientRect().width for inline elements, which report 0 for
 * clientWidth), and flag any single-line row that has grown taller than its
 * own computed line-height (the wrap tell — "New York" measured 40px against
 * a ~20px line). Elements that carry an explicit `max-width` (e.g. the
 * `max-w-[24ch]` empty-state prose) are exempt from the wrap check — see the
 * comment above `allowedToWrap` in the probe body for why.
 *
 * The probe returns `{ findings, cardWidths }`, not a bare array: `findings`
 * is the pass/fail signal (CLIPPED/WRAPPED/PROBE_BROKEN); `cardWidths` is
 * informational-only telemetry (each strip card's rendered width) with no
 * pass/fail threshold — see the comment above `cardWidths` in the probe body
 * for why no threshold is offered.
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
  if (findings.some((f) => f.kind === 'PROBE_BROKEN')) return JSON.stringify({ findings, cardWidths: [] });

  const cards = document.querySelectorAll(Object.values(SELECTORS).join(', '));

  // I3: an element whose only element children are aria-hidden (e.g. the open
  // status pill: a coloured dot + its text) is still effectively a leaf for
  // overflow purposes — the old 'el.children.length > 0' bail skipped it
  // entirely, missing exactly the pattern this program keeps getting wrong.
  function isLeafLike(el) {
    if (el.children.length === 0) return true;
    return Array.from(el.children).every((c) => c.hasAttribute('aria-hidden'));
  }

  // Post-review fix: C2's grid fix (fit-content tracks) and I4's fix (dynamic
  // line-height wrap check) were each correct in isolation and collided —
  // C2 bounded DollarBias's/NewsPanel's empty-state prose with 'max-w-[24ch]'
  // so it can no longer dominate the grid's max-content sizing, and that
  // SAME bound is what makes the 73/75-char sentence wrap to 3-4 lines BY
  // DESIGN. I4's height-vs-line-height check has no notion of "this element
  // is deliberately allowed more than one line", so it would flag both empty
  // states as WRAPPED on every single run — reinstating exactly the
  // always-fires, gets-hand-waved failure mode I4 existed to close.
  //
  // Signal used: a computed 'max-width' other than 'none' is treated as an
  // explicit "this element is allowed to wrap" marker, so the wrap check is
  // skipped for it entirely. Chosen over deriving an expected line count from
  // max-width/char-count because that would need a font-metrics assumption
  // (avg char width) — exactly the kind of hand-tuned constant this
  // sub-project's three Criticals were about UNLEARNING. Elements without an
  // explicit max-width (the overwhelming majority of the strip: names,
  // clocks, status pills, badges) get no free pass and are still held to the
  // single-line bar. CLIPPED detection below is UNCHANGED by this and still
  // runs for every leaf, wrap-exempt or not — bounding max-width does not
  // exempt an element from overflowing its own box horizontally.
  function allowedToWrap(el) {
    return getComputedStyle(el).maxWidth !== 'none';
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

      if (allowedToWrap(el)) return;

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

  // C3: the probe only ever measured LEAVES, so a Sessions card squeezed to
  // one chip column (each chip now with MORE room, not less) reports zero
  // findings while being visibly wrong — a starved-card blind spot. C2's
  // bounded tracks make that less likely, but only incidentally, not by
  // design; the blind spot is still real.
  //
  // Reported as DATA, not a pass/fail: deliberately NO "too narrow" threshold
  // — there is no principled number for it, and inventing one would be
  // exactly the kind of hand-tuned constant this sub-project spent three
  // Criticals unlearning. A human (or the next probe iteration, once a real
  // threshold is EARNED from observed data) reads these widths; silence here
  // is not a pass, it is simply not measured.
  const cardWidths = Array.from(cards).map((card) => ({
    card: card.getAttribute('data-testid'),
    widthPx: Math.round(card.getBoundingClientRect().width),
  }));

  return JSON.stringify({ findings, cardWidths });
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

The probe returns { findings, cardWidths } — TWO different kinds of output:

  - findings: the pass/fail signal. Any CLIPPED or WRAPPED entry, or any
    PROBE_BROKEN entry (a stale selector), is a regression. Zero findings at
    all three widths is the requirement. (Elements with an explicit max-width,
    e.g. the bounded empty-state prose, are deliberately EXEMPT from WRAPPED —
    they are allowed to wrap; see the allowedToWrap comment in the probe.)
  - cardWidths: INFORMATIONAL ONLY, no pass/fail threshold. Each strip card's
    rendered width in px. Read this by eye for anything that looks squeezed
    (e.g. Market Sessions reduced to one chip column, or a card near-zero
    width) — the findings array cannot see a starved-but-not-clipped card, so
    silence in findings is NOT proof the layout is healthy; cross-check
    cardWidths too.
`);
