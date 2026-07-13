"""Arbiter: the deterministic conflict-resolution stage between Intent
submission and execution.

Strategies never execute; they call `submit(intent)`. Once per bar cycle the
controller calls `resolve(open_positions, bar_key)`, which runs a fixed,
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

Thesis aging (bounded memory, no clock)
----------------------------------------
The Arbiter tracks a monotonic `_bar_index`: it increments once per
resolve() call in which `bar_key` differs from the previous call's
`bar_key` (so re-resolving the same bar never ages anything). Each
thesis's most recent *passing* sighting is stored as
`_thesis_memory[thesis] = bar_index`. On the next new bar_key, before any
rule runs, every entry whose age (`current_index - stored_index`) has
reached `thesis_ttl_bars` is purged — this is the sole memory bound: the
dict can only ever hold theses seen within the trailing TTL window. A
thesis that is *itself* blocked as a replay does NOT refresh its stored
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
        self._thesis_memory = {}
        self._bar_index = -1
        self._last_bar_key = _UNSET

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

    def resolve(self, open_positions, bar_key=""):
        submissions, self._cycle = self._cycle, []
        open_positions = open_positions or []

        submissions.sort(
            key=lambda i: (-grade_rank(i.grade), i.priority, i.strategy_id, i.symbol)
        )

        self._advance_bar(bar_key)

        survivors = self._apply_thesis_dedup(submissions)
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

    def _advance_bar(self, bar_key):
        if bar_key == self._last_bar_key:
            return
        self._bar_index += 1
        self._last_bar_key = bar_key
        stale = [
            thesis for thesis, idx in self._thesis_memory.items()
            if self._bar_index - idx >= self.thesis_ttl_bars
        ]
        for thesis in stale:
            del self._thesis_memory[thesis]

    def _apply_thesis_dedup(self, submissions):
        survivors = []
        for intent in submissions:
            thesis = intent.effective_thesis()
            last_idx = self._thesis_memory.get(thesis)
            if last_idx is not None and (self._bar_index - last_idx) < self.thesis_ttl_bars:
                age = self._bar_index - last_idx
                self._block(
                    intent, "thesis_dedup",
                    f"thesis '{thesis}' replayed within {self.thesis_ttl_bars} bars "
                    f"(last seen {age} bar(s) ago)",
                )
                continue
            self._thesis_memory[thesis] = self._bar_index
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
