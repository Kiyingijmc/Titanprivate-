"""Structural exit adapter for the same executable OHLC path engine.

Idealized immediate confirmations and continuous volume; shared live policy.
Context is evaluated at the current M5 OPEN, before any bar extrema are used.
"""
from src.analysis.structure_management import StructurePolicy, management_plan, m15_context
from src.research.sb_execution import Position
import pandas as pd


class ContextCache:
    def __init__(self, bars):
        self.frame = pd.DataFrame(bars)
        self.cache = {}

    def __call__(self, k):
        now = pd.Timestamp(self.frame.time.iloc[k])
        bucket = now.floor('15min')
        if bucket not in self.cache:
            # At most 500 M5 bars, matching the live rolling history buffer.
            end = self.frame.time.searchsorted(bucket)
            self.cache[bucket] = m15_context(self.frame.iloc[max(0, end-500):end], bucket)
        return self.cache[bucket]


class StructurePosition(Position):
    def __init__(self, entry, risk, side, spread, tick, since, context):
        super().__init__('structure')
        self.entry, self.risk, self.side = entry, risk, side
        self.spread, self.tick, self.since = spread, tick, since
        self.context = context
        self.policy = StructurePolicy()
        self.released = False

    @property
    def running(self):
        return self.released

    def manage(self, y):
        plan = management_plan(
            context=self.context, policy=self.policy, entry=self.entry,
            original_tp=self.entry+self.side*2*self.risk,
            current_sl=self.entry+self.side*self.stop*self.risk,
            current_tp=0 if self.released else self.entry+self.side*2*self.risk,
            price=self.entry+self.side*y*self.risk, is_long=self.side == 1,
            spread=self.spread, tick_size=self.tick, since=self.since, level=self.stage)
        if plan is None:
            return
        self.realized += self.volume*plan['fraction']*y
        self.volume *= 1-plan['fraction']
        self.stage = plan['level']
        stop = round(plan['sl']/self.tick)*self.tick
        self.stop = max(self.stop, self.side*(stop-self.entry)/self.risk)
        self.released = plan['tp'] == 0

    def segment(self, start, end):
        if self.outcome:
            return
        if end > start:
            if self.context:
                levels = [(2, 1.), (3, max(1.5, 1.+.75*self.context['atr']/self.risk))]
                for stage, level in levels:
                    if not self.running and level >= 2 and end >= 2:
                        break
                    if self.stage < stage and start <= level <= end:
                        self.manage(level)
            if not self.running and end >= 2:
                self.finish(2., 'TP')
            else:
                self.manage(end)
        elif end <= self.stop:
            self.finish(self.stop, 'STOP')
        else:
            self.manage(end)
