# Titan Control GUI — frontend

Vite + React + TS + Tailwind + shadcn/ui SPA for the v15 control server. It is served
**same-origin** by the embedded FastAPI server in `src/ops/web/server.py` (`:8770`), which
mounts `frontend/dist` and owns `/api` + `/ws`. There is no dev proxy — build the SPA, then
run a Python server that serves it.

```bash
npm install
npm run build      # tsc -b && vite build  -> frontend/dist  (the server mounts this)
npm test           # vitest run
```

## Driving the UI with MT5 offline

Both entrypoints below use `src/ops/web/fake_controller.py`, so neither touches the live path
or the ZMQ bridge. Run them from the repo root, and only when `main.py` is not running.

| Command | What you get |
| --- | --- |
| `TITAN_GUI_TOKEN=devtoken .venv/bin/python -m src.ops.web.devserver` | Bare fake controller — empty book, static state. Use for auth/routing/layout work. |
| `TITAN_GUI_TOKEN=devtoken .venv/bin/python scripts/gui_demo_server.py` | Seeded demo — 2 open positions (EURUSD in profit, XAUUSD in loss) with journal grades, a heartbeat kept fresh so the health strip reads Connected, and a rotating `IntentEmitted`/`IntentBlocked` stream so the live feed and its violet rule chips populate. Use for anything data-shaped: cockpit, feed, charts, design review. |

Both serve `http://127.0.0.1:8770` and gate on the token you export.

`TITAN_GUI_READONLY=1` greys out every mutating control — worth checking before shipping
changes to command buttons or the settings tab.

## Notes

- The server needs a real WebSocket implementation installed (`websockets`); uvicorn silently
  refuses `/ws` upgrades without one. `tests/unit/test_gui_ws_dependency.py` guards this — a
  `TestClient`-only test suite does **not** catch it.
- Settings are layered (`config/config.yaml` + `config/overrides.yaml`); only the 5-key live
  safe subset applies without a restart. Everything else is tagged `restart` in the UI.
