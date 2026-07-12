"""Structured JSONL logging (Trading OS B0).

One JSON object per line; date-partitioned files; never raises into the
caller (a logging failure must not touch the trading loop).
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path


class _Writer:
    def __init__(self, dir_path, name):
        self.dir = Path(dir_path)
        self.name = name
        self.dir.mkdir(parents=True, exist_ok=True)
        self._fh = None
        self._day = None
        self.drops = 0

    def write(self, rec: dict):
        try:
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            if self._fh is None or day != self._day:
                if self._fh:
                    self._fh.close()
                self._fh = open(self.dir / f"{self.name}-{day}.jsonl", "a",
                                encoding="utf-8")
                self._day = day
            self._fh.write(json.dumps(rec, default=str) + "\n")
            self._fh.flush()
        except Exception:
            self.drops += 1

    def close(self):
        try:
            if self._fh:
                self._fh.close()
        except Exception:
            pass


class JsonLogger:
    def __init__(self, dir_path, name="titan"):
        self._w = _Writer(dir_path, name)
        self._ctx = {}

    @property
    def drops(self):
        return self._w.drops

    def bind(self, **ctx) -> "JsonLogger":
        child = JsonLogger.__new__(JsonLogger)
        child._w = self._w
        child._ctx = {**self._ctx, **ctx}
        return child

    def log(self, level, domain, event, msg="", **fields):
        rec = {"ts": time.time(), "level": level, "domain": domain,
               "event": event, "msg": msg, **self._ctx, **fields}
        self._w.write(rec)

    def close(self):
        self._w.close()
