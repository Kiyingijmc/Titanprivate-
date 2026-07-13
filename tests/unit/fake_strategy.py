"""Tiny fake strategy class for registry tests (real importable dotted path)."""

import itertools

_counter = itertools.count()


class FakeStrat:
    def __init__(self, config, logger):
        self.config = config or {}
        self.logger = logger
        # Unique-per-instance default so multiple manifests instantiating this
        # same fixture class (a test-only artifact) don't spuriously collide
        # on `.name` -- real strategy classes each carry their own distinct
        # default name. Tests that want to exercise a name collision pass an
        # explicit "name" override that intentionally matches another's.
        self.name = self.config.get("name", f"FakeStrat-{next(_counter)}")
        self.timeframe = self.config.get("timeframe", "H1")
