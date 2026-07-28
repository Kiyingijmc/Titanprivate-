"""Arbiter: the deterministic conflict-resolution stage between Intent
submission and execution.

Strategies never execute; they call `submit(intent)`. Once per bar cycle the
controller calls `resolve(open_positions, bar_key, timeframe)`, which runs a fixed,
five-rule pipeline over the cycle's submissions and returns the approved
Intents (the SAME objects that were submitted — no copying, no rebuilding,
so a lone intent is provably untouched). Every drop is journaled as an
IntentBlocked event; nothing is silently discarded.

Determinism
-----------
No wall-clock, no randomness. Submissions are sorted once, up front, by
(grade_rank desc, priority asc, strategy_id asc, symbol asc) and every rule
below walks that same order, so ties resolve identically on every run.

Pipeline (fixed order)
-----------------------
1. Thesis dedup — see "Thesis aging" below.
2. Same-symbol-same-direction dedup — within a (symbol, direction) group,
   the sort order above already puts the best intent first; the rest are
   blocked with rule="dedup".
3. Opposition — if a symbol has both a BUY and a SELL survivor (at most one
   of each, courtesy of rule 2), `opposition_policy` decides:
     "higher_grade_wins": keep the higher grade_rank; if grade_rank ties,
        block both (nobody had a stronger claim).
     "block_both": always block both.
   Opposition only ever compares intents submitted THIS cycle against each
   other — an open position's direction (if given) never participates here;
   it only feeds rule 4.
4. Symbol cap — vs `open_positions` (any position on the symbol counts,
   direction unknown or not) plus intents already approved earlier in this
   same resolve() call.
5. Total cap — vs total open positions (all symbols) plus intents already
   approved earlier in this same resolve() call.

Thesis aging (per-timeframe, bounded memory, no clock)
-------------------------------------------------------
Aging is scoped BY TIMEFRAME. The Arbiter tracks one monotonic bar counter
per timeframe in `_bar_index[timeframe]`: it increments once per resolve()
call in which `bar_key` differs from that timeframe's previous `bar_key`
(so re-resolving the same bar never ages anything). Each thesis's most
recent *passing* sighting is stored as
`_thesis_memory[thesis] = (timeframe, bar_index)`, and a thesis is aged
ONLY against the counter of the timeframe it was seen on. `thesis_ttl_bars`
therefore means "bars of the thesis's OWN timeframe" — a TTL of 12 is 12
H1 bars for an H1 thesis and 12 M5 bars for an M5 thesis.

This scoping is what makes mixed-timeframe operation correct (v15 Advisory
C). With a single global counter, an M5 strategy's ~12 closes per hour
would advance the same counter that ages H1 theses, expiring a 12-bar H1
thesis in one hour instead of twelve. `resolve()`'s `timeframe` keyword
defaults to `""`, so any caller that omits it lands in one shared bucket —
which is exactly the old single-counter behavior.

On each new bar_key for a timeframe, before any rule runs, that
timeframe's entries whose age (`current_index - stored_index`) have
reached `thesis_ttl_bars` are purged — this is the sole memory bound: the
dict can only ever hold theses seen within each timeframe's trailing TTL
window. Accepted edge: purging is driven by arrivals, so entries belonging
to a timeframe that STOPS arriving linger until that timeframe ticks
again. The set of live timeframes is small and fixed, so this is bounded
by (timeframes x theses-per-TTL-window), not unbounded growth.

A thesis that is *itself* blocked as a replay does NOT refresh its stored
index (otherwise a spam sequence could keep resetting its own clock and
the block would never expire).
"""
from collections import defaultdict

from src.arbiter.intent import grade_rank
from src.core.events import IntentEmitted, IntentBlocked

_UNSET = object()


class Arbiter:
    def __init__(self, config=None, publish=None):
        config = config or {}
        self.opposition_policy = config.get("opposition_policy", "higher_grade_wins")
        self.max_positions_per_symbol = config.get("max_positions_per_symbol", 1)
        self.max_total_positions = config.get("max_total_positions", 6)
        self.thesis_ttl_bars = config.get("thesis_ttl_bars", 12)
        self._publish = publish

        self._cycle = []
        # thesis -> (timeframe, bar_index_of_that_timeframe)
        self._thesis_memory = {}
        # timeframe -> monotonic bar counter / last seen bar_key
        self._bar_index = {}
        self._last_bar_key = {}

        self._submitted = 0
        self._approved = 0
        self._blocked_by = {}

    # -- publication -------------------------------------------------

    def _emit(self, event):
        if self._publish is not None:
            self._publish(event)

    def _block(self, intent, rule, detail):
        self._blocked_by[rule] = self._blocked_by.get(rule, 0) + 1
        self._emit(IntentBlocked(
            strategy_id=intent.strategy_id,
            symbol=intent.symbol,
            direction=intent.direction,
            rule=rule,
            detail=detail,
        ))

    # -- API -----------------------------------------------------------

    def submit(self, intent):
        self._submitted += 1
        self._emit(IntentEmitted(
            strategy_id=intent.strategy_id,
            symbol=intent.symbol,
            direction=intent.direction,
            kind=intent.kind,
            grade=intent.grade,
            thesis=intent.effective_thesis(),
        ))
        self._cycle.append(intent)

    def resolve(self, open_positions, bar_key="", timeframe=""):
        submissions, self._cycle = self._cycle, []
        open_positions = open_positions or []

        submissions.sort(
            key=lambda i: (-grade_rank(i.grade), i.priority, i.strategy_id, i.symbol)
        )

        self._advance_bar(bar_key, timeframe)

        survivors = self._apply_thesis_dedup(submissions, timeframe)
        survivors = self._apply_symbol_direction_dedup(survivors)
        survivors = self._apply_opposition(survivors)
        approved = self._apply_caps(survivors, open_positions)

        self._approved += len(approved)
        return approved

    def stats(self):
        return {
            "submitted": self._submitted,
            "approved": self._approved,
            "blocked_by": dict(self._blocked_by),
        }

    # -- pipeline rules --------------------------------------------------

    def _advance_bar(self, bar_key, timeframe):
        """Advance ONLY this timeframe's counter, and purge only the theses
        aged out on it — see "Thesis aging" in the module docstring."""
        if self._last_bar_key.get(timeframe, _UNSET) == bar_key:
            return
        current = self._bar_index.get(timeframe, -1) + 1
        self._bar_index[timeframe] = current
        self._last_bar_key[timeframe] = bar_key
        stale = [
            thesis for thesis, (tf, idx) in self._thesis_memory.items()
            if tf == timeframe and current - idx >= self.thesis_ttl_bars
        ]
        for thesis in stale:
            del self._thesis_memory[thesis]

    def _apply_thesis_dedup(self, submissions, timeframe):
        current = self._bar_index[timeframe]
        survivors = []
        for intent in submissions:
            thesis = intent.effective_thesis()
            seen = self._thesis_memory.get(thesis)
            if seen is not None:
                # Age against the counter of the timeframe the thesis was
                # SEEN on, not the one resolving now — a TTL is always
                # denominated in the thesis's own bars.
                seen_tf, last_idx = seen
                age = self._bar_index[seen_tf] - last_idx
                if age < self.thesis_ttl_bars:
                    self._block(
                        intent, "thesis_dedup",
                        f"thesis '{thesis}' replayed within {self.thesis_ttl_bars} bars "
                        f"(last seen {age} bar(s) ago)",
                    )
                    continue
            self._thesis_memory[thesis] = (timeframe, current)
            survivors.append(intent)
        return survivors

    def _apply_symbol_direction_dedup(self, survivors):
        kept = {}
        result = []
        for intent in survivors:
            key = (intent.symbol, intent.direction)
            winner = kept.get(key)
            if winner is None:
                kept[key] = intent
                result.append(intent)
            else:
                self._block(
                    intent, "dedup",
                    f"same-symbol-same-direction: kept {winner.strategy_id} "
                    f"(grade {winner.grade}) over {intent.strategy_id} (grade {intent.grade})",
                )
        return result

    def _apply_opposition(self, survivors):
        by_symbol = defaultdict(list)
        for intent in survivors:
            by_symbol[intent.symbol].append(intent)

        result = []
        for symbol, intents in by_symbol.items():
            if len(intents) < 2:
                result.extend(intents)
                continue
            # At most one survivor per direction reaches here (rule 2
            # already collapsed same-symbol-same-direction groups).
            best, other = intents[0], intents[1]
            if self.opposition_policy == "block_both":
                self._block(best, "opposition", f"block_both policy: opposing directions on {symbol}")
                self._block(other, "opposition", f"block_both policy: opposing directions on {symbol}")
                continue
            if grade_rank(best.grade) == grade_rank(other.grade):
                self._block(best, "opposition", f"equal-grade opposition on {symbol}: both blocked")
                self._block(other, "opposition", f"equal-grade opposition on {symbol}: both blocked")
                continue
            result.append(best)
            self._block(
                other, "opposition",
                f"opposing direction on {symbol}: lost to higher grade {best.grade} ({best.strategy_id})",
            )
        return result

    def _apply_caps(self, survivors, open_positions):
        open_by_symbol = defaultdict(int)
        for pos in open_positions:
            symbol = pos.get("s")
            if symbol:
                open_by_symbol[symbol] += 1
        total_open = len(open_positions)

        approved = []
        approved_by_symbol = defaultdict(int)
        for intent in survivors:
            symbol = intent.symbol
            symbol_total = open_by_symbol[symbol] + approved_by_symbol[symbol]
            if symbol_total >= self.max_positions_per_symbol:
                self._block(
                    intent, "symbol_cap",
                    f"{symbol} at cap (max={self.max_positions_per_symbol}, "
                    f"open={open_by_symbol[symbol]}, approved_this_cycle={approved_by_symbol[symbol]})",
                )
                continue
            total_now = total_open + len(approved)
            if total_now >= self.max_total_positions:
                self._block(
                    intent, "total_cap",
                    f"total positions at cap (max={self.max_total_positions}, "
                    f"open={total_open}, approved_this_cycle={len(approved)})",
                )
                continue
            approved.append(intent)
            approved_by_symbol[symbol] += 1
        return approved
