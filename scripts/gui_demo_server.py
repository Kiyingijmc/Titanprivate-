"""Demo launcher for the Titan Control GUI — seeds the fake controller with a
couple of open positions + non-zero arbiter stats, keeps the heartbeat fresh so
the health strip reads Connected, and streams blocked-intent events (opposition /
ttl-dedup / cap -> the violet rule chips) into the live event feed.

    TITAN_GUI_TOKEN=devtoken .venv/bin/python scripts/gui_demo_server.py

Dev/demo only (MT5 offline). Not part of the live path.
"""
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root, so `src` imports

os.environ.setdefault("TITAN_GUI_TOKEN", "devtoken")
os.environ.setdefault("TITAN_GUI_BIND", "127.0.0.1")

from src.core.events import IntentBlocked, IntentEmitted, SystemStateChanged
from src.ops.web import server as web_server
from src.ops.web.bus_bridge import BusBridge
from src.ops.web.config_layer import load_layered_config
from src.ops.web.fake_controller import build_fake_controller
from src.ops.web.settings import SettingsStore

_ROOT = Path(__file__).resolve().parents[1]

# Two open positions in HEARTBEAT shape (t/s/p/sl/tp/pf/vol/type/comment).
_POSITIONS = [
    {"t": 88101, "s": "EURUSD", "p": 1.08550, "sl": 1.08200, "tp": 1.09250,
     "pf": 42.50, "vol": 0.20, "type": 0, "comment": "SB"},   # BUY, in profit
    {"t": 88102, "s": "XAUUSD", "p": 2381.50, "sl": 2389.00, "tp": 2366.00,
     "pf": -18.30, "vol": 0.10, "type": 1, "comment": "SB"},   # SELL, in loss
]
_JOURNAL = {
    88101: {"grade": "A+", "strategy": "silver_bullet"},
    88102: {"grade": "B", "strategy": "silver_bullet"},
}

# Rotating blocked-intent events — each `rule` renders as a violet chip in the feed.
_BLOCKS = [
    ("gyroscope", "EURUSD", "SELL", "opposition", "higher-grade BUY holds the book"),
    ("aftershock", "GBPUSD", "BUY", "ttl-dedup", "same thesis already fired this bar"),
    ("rubicon", "XAUUSD", "BUY", "cap", "max_total_positions (6) reached"),
]
_EMITS = [
    ("silver_bullet", "EURUSD", "BUY", "MARKET", "A+", "SB London killzone displacement"),
    ("silver_bullet", "USDJPY", "SELL", "LIMIT", "B", "SB NY reversal at FVG"),
]


def _seed(controller):
    controller.current_open_positions = list(_POSITIONS)
    # plain callables assigned to instance attrs (not descriptor-bound → no self)
    controller.state_manager.get_order = lambda t: _JOURNAL.get(t)  # type: ignore
    controller.arbiter.stats = lambda: {  # type: ignore
        "submitted": 9, "approved": 6, "blocked_by": {"opposition": 2, "ttl-dedup": 1}}


async def _heartbeat(controller):
    """Keep last_heartbeat_time fresh so the health strip reads Connected."""
    while True:
        controller.last_heartbeat_time = datetime.now()
        await asyncio.sleep(3)


async def _feed(bridge):
    """Stream a lively mix of events so the feed + violet rule chips populate."""
    await asyncio.sleep(2)
    i = 0
    while True:
        bridge.handle(SystemStateChanged(state="ACTIVE"))
        e = _EMITS[i % len(_EMITS)]
        bridge.handle(IntentEmitted(strategy_id=e[0], symbol=e[1], direction=e[2],
                                    kind=e[3], grade=e[4], thesis=e[5]))
        b = _BLOCKS[i % len(_BLOCKS)]
        bridge.handle(IntentBlocked(strategy_id=b[0], symbol=b[1], direction=b[2],
                                    rule=b[3], detail=b[4]))
        i += 1
        await asyncio.sleep(4)


async def _main():
    controller = build_fake_controller()
    _seed(controller)
    cfg = _ROOT / "config" / "config.yaml"
    defaults = load_layered_config(cfg, _ROOT / "config" / "overrides.yaml") if cfg.exists() else {}
    settings_store = SettingsStore(defaults, _ROOT / "config" / "overrides.yaml")
    bridge = BusBridge()
    task = web_server.start(controller, settings_store, bridge)
    print("Titan Control GUI DEMO: http://127.0.0.1:8770 (token: "
          + os.environ["TITAN_GUI_TOKEN"] + ") — 2 positions + live blocked-intent feed")
    await asyncio.gather(task, _heartbeat(controller), _feed(bridge))


if __name__ == "__main__":
    asyncio.run(_main())
