# News / economic-calendar expanded view — design (sub-project C)

**Date:** 2026-08-08
**Status:** approved design, not yet implemented
**Scope:** widen the calendar feed's forward horizon, expose it on a new endpoint, and replace the
maximized Economic Calendar dialog body with a dense, filterable week-ahead table.

---

## 1. Why this exists

The Economic Calendar card shows the **next** high-impact release and **today's** high-impact
releases. Maximizing it (sub-project A) currently renders *the same component* with `hideHeader`
(`OverviewPage.tsx:358`) — identical content in a bigger box. The expanded view should show the week
ahead, all impact levels, per-event symbol impact, and filters.

A2 left `--impact-high` / `--impact-medium` / `--impact-low` defined (`tokens.css:58-60`) and bound
(`tailwind.config.ts:46-48`) with **no consumer**. C is the consumer.

---

## 2. The data constraint that shaped this design

The kickoff brief stated that `self.store.events()` "already holds the whole week at every impact
level". **The 'every impact level' half is true; the 'whole week' half is backwards.** The store
holds the week *behind*, not the week *ahead*.

The source is `ff_calendar_thisweek.csv` (`sources/forexfactory.py:38`) — the **current** week only.
`CalendarStore.merge()` (`store.py:36`) only ever adds, never prunes, so past events accumulate.
Measured against the live cache on 2026-08-08:

```
now 2026-08-08T18:04:50Z          (Saturday — last day of the feed week)
events total 197   in the FUTURE: 2
  2026-08-09T01:30Z CNY LOW CPI y/y
  2026-08-09T01:30Z CNY LOW PPI y/y
past: 195   oldest 2026-07-26T23:50Z
```

The entire forward calendar was **two LOW-impact CNY prints**. This is not a today-only artifact:
the forward horizon decays across the week, from ~6 days of lookahead on Sunday to ~0 by Friday
evening. An expanded "week ahead" built on `thisweek` alone would be empty for much of its life.

**Decision: add `ff_calendar_nextweek.csv`.** See §3.1.

Two related facts, both confirmed against the cache:

- **`actual` is hardcoded `None`** (`forexfactory.py:104`); 0 of 197 events carry it. Any
  "released, came in at X vs forecast Y" treatment is **not buildable** from this feed.
- The 195 past events are dead weight. The new endpoint filters them out (§3.2); the store is
  **not** pruned (§7).

### 2.1 The `affects` fan-out is bimodal

`news.symbol_currencies` maps exactly the 12 traded pairs. Against the 197 stored events:

| currency | events | → symbols affected |
|---|---|---|
| **USD** | 58 (29%) | **11 of 12** |
| EUR / AUD / CAD | 75 | 1 each |
| GBP / JPY | 36 | 2 each |
| **CHF / CNY / NZD / ALL** | **28 (14%)** | **0 — irrelevant to this book** |

So a flat chip list per row is either 1–2 chips or an 11-chip wall, and 14% of rows would render
nothing. This drives §4.3.

### 2.2 Impact distribution

**LOW 149 (76%) · MEDIUM 21 (11%) · HIGH 27 (14%).** Three quarters of the feed is LOW-impact noise,
which is why impact is the load-bearing filter (§4.5) and why LOW is off by default.

---

## 3. Backend

Three changes, deliberately shaped so the failure ladder in `update_calendar()` — the code that
decides whether a live bot halts trading — **is not touched at all**.

### 3.1 `nextweek` lives inside the source, not the manager

The obvious design (two sources on `NewsManager`) requires restructuring `update_calendar()`'s
early-return ladder. Instead, `ForexFactoryCsvSource.fetch()` fetches **both URLs and returns the
union**. `update_calendar()`, `CalendarStore.merge()`, and the staleness ladder stay unchanged.

All risk collapses into one pure, testable class, under three rules:

| case | behaviour |
|---|---|
| `thisweek` fails | raise `NewsFetchError` — **exactly as today**; the degraded path is unchanged |
| `nextweek` fails | return `thisweek` alone, log WARN, set `next_week_ok = False`. **Not** `feed_degraded` — next week is display-only and must never imply the trading calendar is unhealthy |
| `thisweek` yields 0 events from non-empty rows | return `thisweek`'s empty result alone; **do not append `nextweek`** |

The third rule is the subtle one. The existing broken-feed guard is `if rows_seen and not events`
(`manager.py:70`). If a naive union let next week's events fill in for a `thisweek` whose date
format had drifted, `events` would be non-empty, the guard would never fire, and the cache would be
stamped fresh **while the bot traded blind through every red-folder event this week**. Keeping the
union out of that path preserves the guard exactly.

`last_rows_seen` is therefore reported from `thisweek` alone.

Dedup across the week boundary is already handled: `make_key` buckets on
`currency|title|5-minute-bucket` (`models.py:9`), and `_prefer`'s `source == "forexfactory"`
authority rule is unaffected since both files carry the same source name.

### 3.2 New endpoint `GET /api/news/calendar`

New `src/ops/web/news_view.py::build_calendar(controller)` — same `*_view.py` pattern as
`equity_view.py`, same defensive contract as `_news_block` (`state_view.py:226`): any fault degrades
to `{"status": "unavailable", "events": []}` and never propagates.

Registered in `server.py` alongside the other `dependencies=read` routes.

```json
{ "status": "ok|degraded|stale|unavailable",
  "cache_age_min": 42,
  "horizon_truncated": false,
  "events": [ { "when_utc": "2026-08-07T12:30:00+00:00", "currency": "USD",
                "importance": "HIGH", "title": "Non-Farm Employment Change",
                "forecast": "85K", "previous": "57K", "url": "...",
                "affects": ["XAUUSD", "EURUSD", "..."] } ] }
```

- **Forward-only** (`when_utc >= now`) — drops the 195 past events without pruning the store.
- All impact levels.
- `affects` is memoised **per currency**, not per event — otherwise it is 197 × 12 `currencies_for`
  calls per request to produce 10 distinct answers.
- `horizon_truncated` surfaces `next_week_ok`, so the UI can say "next week unavailable" rather than
  silently showing a short list (§4.4). It reflects **the most recent completed refresh attempt**.
  Before any attempt has completed (cold start against a cached store) it is `False` — absence of
  evidence of truncation, not a claim that a fetch succeeded. Feed health is already reported
  separately by `status` / `cache_age_min`, so this flag never has to double as a staleness signal.

### 3.3 `/api/state` is not widened

`/api/state` is polled **every 2 seconds** (`useLiveState.ts:97`) and is serialized inside the live
trading process's event loop. A widened calendar weighs ~232 bytes/event trimmed to display fields;
with `nextweek` merged (~200–400 forward events) that is **46–93 KB added to a 2-second poll** —
~23–46 KB/s, 2–4 GB/day — for data that changes once an hour (`refresh_interval_min: 60`). A 3600×
mismatch between change rate and ship rate.

**The hot path gains nothing.** The existing lean `next` / `today` / `blocked_symbols` block is
unchanged, which is also what keeps the collapsed card (§4.6) untouched.

---

## 4. Frontend

### 4.1 Module boundaries

**All filter/group/sort logic is pure and lives outside React.**

| file | responsibility | depends on |
|---|---|---|
| `lib/api.ts` | `+ getNewsCalendar()` — auth is already central at `api.ts:17` | — |
| `lib/newsCalendar.ts` | **pure**: filter → group by UTC day → sort → per-day tallies → held-symbol join | nothing (no React, no DOM) |
| `lib/useNewsCalendar.ts` | fetch + 60s poll, gated on `enabled`; mirrors `useEquitySeries` (injected `api`, keeps last-good on error) | api |
| `components/market/ImpactChip.tsx` | the `--impact-*` token consumer; colour **+ mandatory text label** | — |
| `components/market/CalendarFilters.tsx` | impact toggles, affects-my-book, horizon selector | — |
| `components/market/CalendarTable.tsx` | day-grouped table rows | ImpactChip |
| `components/market/CalendarExpanded.tsx` | composes the above + states; the only import `OverviewPage` adds | above |

Every consequential rule in this feature becomes a plain function test that runs without jsdom
(§6.2). Given that A2/B1/D shipped fourteen plan-level defects whose common shape was *a check that
could not fail*, moving the logic to where real assertions are possible is worth more than any
individual test.

### 4.2 Layout — dense institutional table

Chosen from three mockups reviewed in a browser against real NFP-day data. The deciding case is the
**five HIGH releases that all land at 12:30Z on 2026-08-07**: that is a table problem — you scan
forecast-vs-previous down an aligned column. The timeline alternative spent ~3× the vertical space
and pushed the cluster off-screen; the day-rail alternative hid six of seven days behind a click,
which is the wrong default for a view whose entire job is showing you the week.

Columns: **Time · Impact · Cur · Event · Forecast · Previous · Affects**

- `table-fixed` with explicit column widths — without it a long title blows out the grid instead of
  truncating.
- Event title: `truncate` + `title` attribute (D's overflow primitive; `min-w-0` on flex parents).
- Numerics: `font-mono tabnum`, so forecast/previous compare down the column. That alignment is the
  entire reason this layout was chosen.
- Sticky day header row (`<th scope="colgroup" colspan>`) carrying the day and its tally.
- **All times are UTC, suffixed `Z`** (`12:30Z`), and days are UTC days. This matches the existing
  collapsed card exactly (`NewsPanel.tsx:136` pins `timeZone: "UTC"`; `:142` appends the `Z`), so the
  two surfaces cannot disagree about when an event is. The dashboard already carries a separate
  `LocalityClock` for local time; the calendar does not duplicate that job.
- **The tally reflects the filtered set**, not the raw set — a header reading "5 high" above three
  rows is a contradiction the operator has to debug.

### 4.3 Per-event symbol impact

Each row shows the `affects` list (the same `currencies_for` logic `snapshot()` already uses for
`next`), plus a marker when an affected symbol has an **open position right now**. The frontend
joins against `snapshot.positions` client-side, so the calendar endpoint stays pure calendar data.

Given the bimodal fan-out (§2.1), the column shows **at most 2 symbol chips followed by `+N more`,
where N is the REMAINDER** (a USD event mapping to 11 symbols renders two chips and `+9 more`, not
`+11`). The full list is in `title` / `aria-label`. **Held symbols sort first**, so the symbol that
is currently costing you money is never the one hidden behind the counter.

**The held state carries three channels, not one.** A row tint alone would be colour-only encoding —
exactly the failure mode §5 legislates against for impact, and there is no reason to obey the rule
in one place and break it in the other. So: row tint, *plus* the held symbol chip rendered with a
distinct outline and a visible dot, *plus* `title` / `sr-only` text ("open position in XAUUSD").
Colour stays redundant, never load-bearing.

### 4.4 States

| state | treatment |
|---|---|
| first load | skeleton rows (the dialog is already open; a blank body reads as "no events") |
| `status: unavailable` / fetch error | the existing panel's empty-state language, unchanged |
| `status: stale` | reuse `NewsPanel`'s stale banner treatment |
| **`horizon_truncated`** | end-of-list note: *"Next week's calendar is unavailable — showing through &lt;date&gt;."* |
| **filtered to zero** | *"No events match these filters"* + a Reset control |

The bottom two rows are the ones that matter. A truncated horizon and an over-narrow filter both
produce **a short list that looks exactly like a quiet week** — and a quiet week is precisely the
wrong thing to believe about an economic calendar. Both must be visibly distinct from "the feed is
healthy and there is genuinely nothing".

### 4.5 Filters and defaults

Three filters: **impact level**, **affects my book**, and a **horizon selector**.

The horizon control is a compact segmented control — **Today / 3d / 7d / All** — not a date picker.
The horizon is only ~7–14 days, and a picker is heavy chrome for a dialog.

Currency filtering is **out of scope**: ten toggles, largely redundant with affects-my-book.

Defaults: impact **High + Med on, Low off** (LOW is 76% of the feed). Horizon **7d**.
Affects-my-book **off** — narrowing is one click, but a filter that silently hides 14% of the
calendar before the operator has touched anything is the kind of default that gets blamed after a
surprise.

### 4.6 The collapsed card does not change

C touches only the dialog body and the new endpoint. `NewsPanel.tsx` is not modified.

D re-proportioned that card to a `0.8fr` track and still has a browser measurement outstanding;
it is unmerged. Touching the collapsed branch would create a live merge and re-verification conflict
for no benefit C needs.

### 4.7 Motion

Effectively none. Radix already animates the dialog open. Row-level enter/exit on a 200-row table
under a filter toggle is jank with nothing to narrate — the operator changed the filter, they know
why the rows changed. The only motion is the existing dialog transition and the standard focus ring.

---

## 5. The colour-blind rule (binding, from A2 §5)

> `--impact-high` (hue 10) and `--loss` (hue 358) are only ~12° apart — deliberately, because both
> want to be red by convention — so on a trading screen "high-impact release" and "losing money"
> could be confused at a glance, and would be indistinguishable to a red-green colour-blind
> operator. **Every impact indicator MUST also carry its text label (High / Med / Low). Colour is
> redundant encoding, not the carrier.**

`ImpactChip` renders the text label unconditionally. §4.3 extends the same discipline to the
open-position marker.

---

## 6. Testing

### 6.1 Python (`tests/unit`, stdlib unittest)

Source rules from §3.1, each with the mutation that must redden it:

| guard | mutation that must make it fail |
|---|---|
| `thisweek` fails → `NewsFetchError` raised | let `nextweek`'s success rescue the return |
| `nextweek` fails → `thisweek` returned, `next_week_ok False`, `feed_degraded` untouched | set `feed_degraded` on a `nextweek` failure |
| `thisweek` yields 0 events from non-empty rows → `nextweek` not appended | append it anyway |
| week-boundary duplicate appears once | weaken `make_key` bucketing |

Plus the test that justifies the whole §3.1 shape: **broken `thisweek` + healthy `nextweek` must not
stamp `last_success`.** Assert `store.age()` is unchanged and an ERROR was logged. Without it,
nothing stops a future refactor from re-introducing a calendar that reports itself fresh while the
bot is blind to this week's red folders.

For `build_calendar`: forward-only filter (assert **non-empty first**, then the count), all three
impact levels present, `affects` correct at both extremes (USD → 11 symbols, CHF → `[]`), and the
per-currency memo (`currencies_for` called once per *distinct currency*; removing the memo makes the
call count jump).

And the isolation property, tested rather than asserted: a manager whose `store.events()` raises
must yield `{"status": "unavailable", "events": []}` **and `/api/state` must still return 200**.

### 6.2 Frontend pure logic (`newsCalendar.test.ts`, no jsdom)

- impact filter membership — **non-emptiness asserted before membership**
- affects-my-book: CHF excluded, USD included
- horizon boundary: an event at exactly `now + 3d` (inclusive, pinned by test)
- day grouping across the UTC midnight seam — 23:59Z and 00:01Z land on **different days**
- per-day tally equals the filtered rows beneath it (the §4.2 contradiction invariant)
- held symbols sort first in `affects`
- **stable sort across the NFP cluster** — five events share `12:30Z`; under a 60s poll an unstable
  comparator reshuffles those rows on every refresh. Untestable by screenshot, cheap to pin here.

### 6.3 jsdom (narrow — only what it can honestly see)

- `ImpactChip` renders the **text label** for each level (dropping the label goes red). The colour is
  **not** asserted.
- filtered-to-zero shows the "no events match" state **and not** the "unavailable" state — both
  directions, since the whole point is that they are distinguishable.
- `horizon_truncated` true → note present; false → absent.
- a held row exposes accessible text naming the symbol.
- the calendar api is **not called while the dialog is closed** (spy call count 0).

**Deliberately not tested in jsdom:** colours, sticky positioning, truncation, column widths, "does
it fit". jsdom computes no layout and resolves no colour, so those pass whether or not the behaviour
works and would manufacture fake coverage.

### 6.4 Browser — the actual gate

Fresh worktree; `ln -sfn <main>/frontend/node_modules <worktree>/frontend/node_modules` (never
`npm install`); `export PATH="/home/kiyingijmc/.nvm/versions/node/v20.20.2/bin:$PATH"`;
`npm run build`; devserver on **a free port — not 8899**, which is held by pid 1019418 (another
session's devserver, 12h+ old at time of writing). `ss -tlnp` before and after.

The fake controller ships no news manager and no positions, so `window.fetch` is patched to inject
both a `/api/news/calendar` payload and a positions array — otherwise the impact chips and the
entire held-row treatment are absent for the *wrong* reason and the verification is worthless.

Measured in the browser, not jsdom: the three impact tokens resolve to distinct computed colours;
the sticky day header holds on scroll; long titles truncate instead of overflowing; the page body
never scrolls horizontally; the five-row NFP cluster aligns down the Forecast/Previous columns.

The `browse` daemon has a hard 8-second start budget and `browse status` **spawns** a daemon when
none is healthy — start one, wait a **fixed** interval, then measure. Never poll it in a loop.

### 6.5 Reporting

For every new guard: **mutation applied → failing output → restored → passing output**, both pastes
included. Then the targeted suites, and the full Python suite before claiming done — it runs ~3000s,
so it is one deliberate run, not a loop.

---

## 7. Out of scope

- **Store pruning.** `merge()` never deletes, so the cache grows without bound (197 events over two
  weeks today; faster with `nextweek`). Real but slow, and it is a cache change to a live trading
  system with no urgency. **Backlog row, not C.**
- **`actual` values.** Hardcoded `None` (`forexfactory.py:104`), 0/197 populated. Not buildable from
  this feed (§2).
- **Currency filter** (§4.5).
- **The collapsed strip card** (§4.6).
- **A `Calendar` nav page.** The expanded view is the maximized dialog; the maximize affordance,
  the 75% sizing, and the focus-restore handling already exist and are tested.

---

## 8. Gates

- **Bot restart.** C changes Python, so none of it is live until the bot is restarted. The build
  does not restart it; the owner is asked when the work is otherwise finished and verified.
- **Merge.** C lands on its own branch. D is unmerged with a measurement outstanding; C does not
  reorder the integration queue.
