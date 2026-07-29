"""FastAPI app + uvicorn task for the embedded control API (port 8770)."""
import asyncio
import json
import os
import socket
from pathlib import Path

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from src.core.events import GuiActionExecuted

from . import auth
from .commands import execute_command
from .registry_view import execute_registry_action, registry_report
from .state_view import build_snapshot, history_rows

_WS_AUTH_TIMEOUT_S = 3.0
_DEFAULT_DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def _audit(controller, request, action: str, payload, outcome: str) -> None:
    try:
        controller._publish(GuiActionExecuted(
            action=action, args=json.dumps(payload, default=str)[:500],
            outcome=outcome, client=getattr(getattr(request, "client", None), "host", "?") or "?"))
    except Exception:
        pass  # audit must never break the request path


def create_app(controller, settings_store, bridge, dist_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Titan Control API")
    app.state.controller = controller

    read = [Depends(auth.require_token)]
    write = [Depends(auth.require_token), Depends(auth.require_writable)]

    @app.get("/api/state", dependencies=read)
    def get_state():
        return build_snapshot(controller)

    @app.get("/api/events", dependencies=read)
    def get_events(limit: int = 200):
        return {"events": bridge.recent(limit=limit)}

    @app.get("/api/history", dependencies=read)
    def get_history(limit: int = 50):
        return {"history": history_rows(controller.state_manager.conn, limit=limit)}

    @app.post("/api/command", dependencies=write)
    async def post_command(payload: dict, request: Request):
        result = await execute_command(controller, payload)
        if result.get("status") == "ok":
            _audit(controller, request, f"command:{payload.get('command')}", payload, "ok")
        return result

    @app.get("/api/settings", dependencies=read)
    def get_settings():
        return {"settings": settings_store.describe()}

    @app.patch("/api/settings", dependencies=write)
    def patch_settings(payload: dict, request: Request):
        key, value = payload.get("key"), payload.get("value")
        try:
            result = settings_store.set(key, value)
        except ValueError as e:
            return JSONResponse(status_code=422, content={"detail": str(e)})
        if settings_store.is_safe(key):
            controller.apply_runtime_setting(key, value)
        _audit(controller, request, f"settings:{key}", payload, "ok")
        return result

    @app.get("/api/registry", dependencies=read)
    def get_registry():
        return {"registry": registry_report(controller)}

    @app.post("/api/registry/{sid}/{action}", dependencies=write)
    def post_registry(sid: str, action: str, request: Request, payload: dict = None):
        payload = payload or {}
        result = execute_registry_action(controller, sid, action, payload)
        if result.get("status") == "ok":
            _audit(controller, request, f"registry:{action}:{sid}", payload, "ok")
        return result

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        token = websocket.headers.get("sec-websocket-protocol")
        if not auth.token_ok(token):
            try:
                token = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_WS_AUTH_TIMEOUT_S)
            except Exception:
                token = None
        if not auth.token_ok(token):
            await websocket.close(code=1008)
            return
        await websocket.send_json({"type": "state", **build_snapshot(controller)})
        queue = bridge.attach()
        try:
            while True:
                event = await queue.get()
                await websocket.send_json({"type": "event", **event})
        except WebSocketDisconnect:
            pass
        finally:
            bridge.detach(queue)

    # --- Static SPA mount (added last so /api/* and /ws above always win) ---
    spa_dir = Path(dist_dir) if dist_dir is not None else _DEFAULT_DIST_DIR
    index_file = spa_dir / "index.html"
    if index_file.is_file():
        spa_root = spa_dir.resolve()

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            candidate = (spa_dir / full_path).resolve()
            try:
                candidate.relative_to(spa_root)
            except ValueError:
                candidate = None  # path traversal attempt: fall through to index.html
            if candidate is not None and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index_file)
    # else: no dist/ built yet -> backend stays headless, no mount, no raise.

    return app


def _bind_socket(host: str, port: int) -> socket.socket:
    """Bind+listen synchronously so a port-in-use OSError raises here — a
    plain, catchable exception — instead of only surfacing later as an
    uncaught SystemExit from uvicorn's own Config.bind_socket(), which calls
    sys.exit(1) on OSError. SystemExit raised inside an asyncio.Task bypasses
    normal Task exception handling and crashes the event loop, so it must
    never be allowed to originate inside the fire-and-forget serve() task."""
    family = socket.AF_INET6 if host and ":" in host else socket.AF_INET
    sock = socket.socket(family=family)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        sock.listen()
    except OSError:
        sock.close()
        raise
    sock.set_inheritable(True)
    return sock


DEFAULT_GUI_PORT = 8770


def gui_port() -> int:
    """The port start() will bind. Single-sourced so callers that only need to
    REPORT it (e.g. the controller's boot log) cannot drift from the bind."""
    return int(os.environ.get("TITAN_GUI_PORT", DEFAULT_GUI_PORT))


def start(controller, settings_store, bridge) -> "asyncio.Task":
    """uvicorn Server on the controller's loop; returns the serve() task."""
    import uvicorn  # local import keeps unit-test imports light

    app = create_app(controller, settings_store, bridge)
    host = os.environ.get("TITAN_GUI_BIND", "127.0.0.1")
    port = gui_port()
    sock = _bind_socket(host, port)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    return asyncio.create_task(server.serve(sockets=[sock]))
