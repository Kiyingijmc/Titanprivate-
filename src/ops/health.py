"""Health probes + systemd notification (Trading OS B0).

Stdlib-only HTTP: /healthz (liveness) and /readyz (readiness via injected
callable). Replaced by the FastAPI control plane in backend phase B2; the
readiness_fn contract survives that migration.
"""
import asyncio
import json
import os
import socket


def sd_notify(msg: str):
    """Send a systemd notify datagram; silent no-op outside systemd."""
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    try:
        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            s.connect(addr)
            s.send(msg.encode())
        finally:
            s.close()
    except Exception:
        pass


class HealthProbe:
    def __init__(self, readiness_fn, bind="127.0.0.1", port=8787):
        self._readiness_fn = readiness_fn
        self._bind = bind
        self._port = port
        self._server = None

    async def start(self) -> int:
        self._server = await asyncio.start_server(
            self._handle, self._bind, self._port)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            path = line.split()[1].decode() if len(line.split()) > 1 else "/"
            if path == "/healthz":
                status, body = 200, {"ok": True}
            elif path == "/readyz":
                try:
                    ready, reasons = self._readiness_fn()
                except Exception as e:
                    ready, reasons = False, [f"readiness_fn error: {e}"]
                status = 200 if ready else 503
                body = {"ready": bool(ready)}
                if not ready:
                    body["reasons"] = list(reasons)
            else:
                status, body = 404, {"error": "not found"}
            payload = json.dumps(body).encode()
            writer.write(
                f"HTTP/1.0 {status} X\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)
            await writer.drain()
        except Exception:
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass
