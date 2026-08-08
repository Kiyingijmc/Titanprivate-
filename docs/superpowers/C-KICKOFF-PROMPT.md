# Kickoff prompt for sub-project C — paste into a new session

---

Execute sub-project **C** of the Titan GUI program: the **news / economic-calendar expanded view**.

This is new feature work, so start with `superpowers:brainstorming` (spec → my approval →
`superpowers:writing-plans` → `superpowers:subagent-driven-development` → browser pass). Do not skip
to a plan; C has a real design question in it that I need to decide.

## Where the program stands

Four sub-projects came out of one ask ("make the equity graph institutional-grade with a key,
maximizable to 75%, same for news, add colour, the session clocks overflow"):

| | state |
|---|---|
| **A** maximize panels to 75% | merged + live |
| **A2** semantic colour tokens | merged + live |
| **B1** equity chart legibility | merged + live |
| **B2** trade exit markers + analytics strip | **not started** — needs a trades-in-range endpoint |
| **C** news expanded view | **this one** |
| **D** market-context strip | pushed as `feat/market-strip`, **unmerged**, one browser measurement outstanding |

## What C is

The Economic Calendar card currently shows the **next** high-impact release and **today's** high-impact
releases. The expanded view should show the week ahead, all impact levels, per-event symbol impact,
and filters.

## 🔴 C needs BACKEND work — this is the defining constraint

`NewsManager.snapshot()` (`src/analysis/news/manager.py`) filters hard:

```python
upcoming = [e for e in self.store.events()
            if e.importance == "HIGH" and e.when_utc >= now]
```

and returns only `next` (the first HIGH) plus `today` (today's HIGH events, via `digest()`).

**`self.store.events()` already holds the whole week at every impact level.** The data exists; the
snapshot throws it away. So C is not a pure frontend job like A2/B1/D were — it needs a widened
payload (or a new endpoint), and that is a Python change to a **live trading system**.

`src/ops/web/state_view.py:_news_block()` wraps `snapshot()` defensively — any fault degrades to
`{"status": "unavailable"}` rather than breaking the whole payload. **Preserve that property.**
Whatever you widen must not let a news fault take down the dashboard's state endpoint.

## 🔴 A2 left tokens specifically for C — and a hard accessibility rule

`--impact-high` / `--impact-medium` / `--impact-low` are defined in `frontend/src/design/tokens.css`
and bound in `tailwind.config.ts`. They have **no consumer yet**; C is the consumer.

From A2's spec §5, and this is binding, not advisory:

> `--impact-high` (hue 10) and `--loss` (hue 358) are only ~12° apart — deliberately, because both
> want to be red by convention — so on a trading screen "high-impact release" and "losing money"
> could be confused at a glance, and would be indistinguishable to a red-green colour-blind operator.
> **Every impact indicator MUST also carry its text label (High / Med / Low). Colour is redundant
> encoding, not the carrier.**

## Environment — read before touching anything

🔴 **A live trading bot runs from this checkout** and serves `frontend/dist`. It holds ports
**8770 / 32768 / 32769**. Check with `ss -tlnp` before and after anything.

- **Work in a fresh git worktree**, never the main checkout — `npm run build` there swaps the GUI the
  running bot is serving.
- `ln -sfn <main-checkout>/frontend/node_modules <worktree>/frontend/node_modules` — do **not** run
  `npm install` / `npm ci` (>10 min, and it leaves nothing behind if interrupted).
- `export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"` first, always.
- Frontend: `npx vitest run <path>`, `npm test` (slow — see below), `npx tsc -b`, `npm run build`.
- Python: `.venv/bin/python -m unittest discover -s tests/unit -p 'test_*.py'`.
- **A Python change means the bot needs a restart to pick it up.** Ask me first. A2/B1/D were all
  frontend-only and needed none.
- Another session often works in this repo concurrently. Re-check `git log`/`git status` before
  acting on them; do not stage files you did not create.

## Test-quality rules this repo enforces

Learned the hard way — A2, B1 and D shipped **fourteen** plan-level defects between them, and the
common shape was *a check that could not fail*:

- **jsdom computes no layout and resolves no colour.** Never assert a Tailwind class string, a hex,
  an HSL literal, a width, or "the text fits". All of those pass whether or not the behaviour works.
- Ask of every guard: **what mutation makes this red?** If nothing does, delete it — a test that
  cannot fail is worse than no test, because it gets counted as coverage.
- **Prove new guards bite.** Apply the mutation, watch it fail, restore, report both outputs.
- **Non-emptiness matters.** A loop or selector that matches nothing passes silently. Assert the
  collection is non-empty before asserting things about its members.
- Colour and layout are verified in a **browser**, never in jsdom.
- If a brief tells you to do something impossible, **say so with evidence** rather than working
  around it silently. That instinct caught three of my errors in D.

## Browser verification — required, and it is the real gate

jsdom cannot see any of this. The proven recipe never touches the live bot:

```bash
# in the worktree
npm run build
TITAN_GUI_PORT=8899 TITAN_GUI_TOKEN=layoutcheck \
  <main-checkout>/.venv/bin/python -m src.ops.web.devserver
# then drive http://127.0.0.1:8899 with the `browse` skill, token `layoutcheck`
```

⚠️ **The `browse` daemon has a hard 8-second start budget and `browse status` SPAWNS a daemon when
none is healthy.** Do **not** poll it in a loop — I did that and created 16 daemons, driving the box
to load 104. Start one with `nohup bun run src/server.ts &`, wait a **fixed** interval, then measure.
Headless Chromium needs a few GB free; check `free -g` first.

⚠️ The devserver's fake controller ships **no risk block** and often no dollar/news data, so
risk-dependent UI is absent for the *wrong* reason. Patch `window.fetch` to inject what you need,
or you will "verify" an empty state.

## Read these first

- `docs/superpowers/specs/2026-08-03-visual-language-foundation-design.md` — A2, especially §5
  (impact colours + the colour-blind rule) and §2 (why the impact tokens exist with no consumer).
- `docs/superpowers/specs/2026-08-04-market-context-strip-design.md` and its plan — D, for the
  overflow primitives (`min-w-0` on the flex parent, `truncate`, `title` on anything truncatable) and
  for how the strip's Economic Calendar card is currently sized (`fit-content` tracks).
- `frontend/src/components/market/NewsPanel.tsx` — the current card, including its `hideHeader` prop
  used by the maximized dialog, and its empty state.
- `src/analysis/news/manager.py`, `store.py`, `policy.py`.

## Questions I expect to be asked during brainstorming

Do not assume answers to these:

1. Is the expanded view a **redesign of the maximized dialog** (A already built the maximize
   affordance) or a new surface?
2. What does "per-event symbol impact" mean concretely — the `affects` list `snapshot()` already
   computes, or something richer?
3. Which filters actually earn their place? (Impact level, currency, symbol-affects-my-book, date?)
4. Does the **collapsed** strip card change at all, or only the expanded view? D just re-proportioned
   that card, and its width is now capped.
5. How much backend widening is in scope — widen `snapshot()`, or add a separate endpoint so the
   hot-path payload does not grow? The snapshot goes out on every poll.

Start by exploring the code, then ask me one question at a time.
