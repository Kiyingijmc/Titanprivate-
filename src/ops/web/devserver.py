# src/ops/web/devserver.py
"""Dev-only entrypoint: run the Control GUI server against a fake in-memory
controller, so the SPA can be built and driven with MT5/the bridge offline.

    .venv/bin/python -m src.ops.web.devserver

NOT imported by the live SystemController — see system_controller.py's own
`web_server.start(self, ...)` call for the production wiring. Reads the
checked-in config/config.yaml + config/overrides.yaml the same way the live
controller does, purely so SettingsStore has realistic defaults to describe;
no trading logic runs.
"""
import asyncio
from pathlib import Path

from .bus_bridge import BusBridge
from .config_layer import load_layered_config
from .fake_controller import build_fake_controller
from .settings import SettingsStore
from . import server as web_server

_ROOT_DIR = Path(__file__).resolve().parents[3]


def _build_settings_store() -> SettingsStore:
    cfg_path = _ROOT_DIR / "config" / "config.yaml"
    overrides_path = _ROOT_DIR / "config" / "overrides.yaml"
    defaults = load_layered_config(cfg_path, overrides_path) if cfg_path.exists() else {}
    return SettingsStore(defaults, overrides_path)


async def _main() -> None:
    controller = build_fake_controller()
    settings_store = _build_settings_store()
    bridge = BusBridge()
    task = web_server.start(controller, settings_store, bridge)
    print("Titan Control GUI devserver: http://127.0.0.1:8770 (fake controller, MT5 offline)")
    await task


if __name__ == "__main__":
    asyncio.run(_main())
