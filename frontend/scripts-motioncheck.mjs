/**
 * Real-browser verification of the motion rules, against the PRODUCTION build
 * (dist/) served on 127.0.0.1:8123. jsdom cannot do any of this: it does not
 * load CSS, does not run animations, and has no media-query emulation.
 */
import { chromium, devices } from "playwright";

const URL = "http://127.0.0.1:8123/";
const out = [];
const log = (name, pass, detail) => {
  out.push({ name, pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name} :: ${detail}`);
};

// Reuse the already-cached Chromium rather than downloading another build.
const browser = await chromium.launch({
  executablePath: "/home/kiyingijmc/.cache/ms-playwright/chromium-1217/chrome-linux64/chrome",
});

// ── 1. Dialog enter/exit actually animate, with our timing ──────────────────
{
  const page = await browser.newPage();
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 120000 });
  const r = await page.evaluate(async () => {
    const d = document.createElement("div");
    d.setAttribute("data-titan-dialog", "");
    d.setAttribute("data-state", "open");
    document.body.appendChild(d);
    await new Promise((res) => requestAnimationFrame(res));
    const open = d.getAnimations().map((a) => ({
      name: a.animationName,
      dur: a.effect.getComputedTiming().duration,
      ease: getComputedStyle(d).animationTimingFunction,
    }));
    d.setAttribute("data-state", "closed");
    // Two frames: one for the style recalc that swaps animation-name, one for
    // the new animation to be registered on the timeline.
    await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
    const closed = d.getAnimations().map((a) => ({
      name: a.animationName,
      dur: a.effect.getComputedTiming().duration,
    }));
    const closedComputed = {
      name: getComputedStyle(d).animationName,
      dur: getComputedStyle(d).animationDuration,
    };
    // What the first frame of the enter actually looks like.
    d.setAttribute("data-state", "open");
    const kf = [...document.styleSheets]
      .flatMap((s) => { try { return [...s.cssRules]; } catch { return []; } })
      .filter((r) => r.type === 7 && r.name === "titan-dialog-in")
      .map((r) => [...r.cssRules].map((k) => `${k.keyText} ${k.style.transform}`).join(" | "))[0];
    d.remove();
    return { open, closed, closedComputed, kf };
  });
  const enter = r.open[0], exit = r.closed[0];
  const exitName = exit?.name ?? r.closedComputed.name;
  const exitDur = exit?.dur ?? parseFloat(r.closedComputed.dur) * 1000;
  log("dialog enter animates", enter?.name === "titan-dialog-in", `${enter?.name} ${enter?.dur}ms ${enter?.ease}`);
  log("dialog exit animates", exitName === "titan-dialog-out", `${exitName} ${exitDur}ms`);
  log("exit is faster than enter", exitDur < enter?.dur, `enter ${enter?.dur}ms vs exit ${exitDur}ms`);
  log("enter starts from a visible scale", /scale\(0\.95\)/.test(r.kf) && !/scale\(0\)/.test(r.kf), r.kf);
  await page.close();
}

// ── 2. prefers-reduced-motion actually STOPS infinite animations ────────────
for (const mode of ["no-preference", "reduce"]) {
  const page = await browser.newPage();
  await page.emulateMedia({ reducedMotion: mode });
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 120000 });
  const r = await page.evaluate(async () => {
    const d = document.createElement("div");
    d.className = "animate-pulse";
    document.body.appendChild(d);
    await new Promise((res) => requestAnimationFrame(res));
    const cs = getComputedStyle(d);
    const declared = { iters: cs.animationIterationCount, dur: cs.animationDuration };
    // Let real time pass, then ask whether anything is STILL running. This is
    // the question that matters: a 0.001ms animation with infinite iterations
    // is still running (and strobing) forever.
    await new Promise((res) => setTimeout(res, 100));
    const stillRunning = d.getAnimations().some((a) => a.playState === "running");
    d.remove();
    return { declared, stillRunning };
  });
  const stops = !r.stillRunning;
  log(
    `reduced-motion=${mode}: animate-pulse ${stops ? "has stopped" : "is still running"} after 100ms`,
    mode === "reduce" ? stops : !stops,
    `iteration-count=${r.declared.iters} duration=${r.declared.dur}`
  );
  await page.close();
}

// ── 3. Hover does not stick on touch ───────────────────────────────────────
for (const [label, ctxOpts] of [
  ["desktop (fine pointer)", {}],
  ["phone (coarse pointer)", devices["Pixel 5"]],
]) {
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 120000 });
  const applies = await page.evaluate(() => {
    const d = document.createElement("div");
    d.className = "hover:bg-muted";
    document.body.appendChild(d);
    const hoverRuleApplies = [...document.styleSheets]
      .flatMap((s) => { try { return [...s.cssRules]; } catch { return []; } })
      .filter((r) => r.type === 4 && /hover/.test(r.conditionText || ""))
      .some((r) => matchMedia(r.conditionText).matches);
    d.remove();
    return hoverRuleApplies;
  });
  log(
    `hover styles enabled on ${label}`,
    label.startsWith("desktop") ? applies : !applies,
    `@media (hover:hover) and (pointer:fine) matches = ${applies}`
  );
  await ctx.close();
}

// ── 4. Button press feedback is real and transitionable ────────────────────
{
  const page = await browser.newPage();
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 120000 });
  const r = await page.evaluate(() => {
    const b = document.querySelector("button");
    if (!b) return null;
    const cs = getComputedStyle(b);
    return {
      cls: b.className.includes("active:scale-[0.97]"),
      transitionProp: cs.transitionProperty,
      transitionDur: cs.transitionDuration,
      timing: cs.transitionTimingFunction,
    };
  });
  if (!r) log("button press feedback", false, "no <button> on the page");
  else {
    log("button carries the :active scale", r.cls, r.cls ? "active:scale-[0.97]" : "missing");
    log("transform is transitionable", r.transitionProp.includes("transform"), r.transitionProp);
    log("press timed by the motion tokens", r.transitionDur.startsWith("0.15"), `${r.transitionDur} / ${r.timing}`);
  }
  await page.close();
}

await browser.close();
const failed = out.filter((o) => !o.pass);
console.log(`\n${out.length - failed.length}/${out.length} checks passed`);
process.exit(failed.length ? 1 : 0);
