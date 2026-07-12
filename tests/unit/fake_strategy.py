"""Tiny fake strategy class for registry tests (real importable dotted path)."""


class FakeStrat:
    def __init__(self, config, logger):
        self.config = config or {}
        self.logger = logger
        self.name = self.config.get("name", "FakeStrat")
        self.timeframe = self.config.get("timeframe", "H1")
