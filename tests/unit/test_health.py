import asyncio, json, os, socket, tempfile, unittest
from unittest.mock import patch
from src.ops.health import HealthProbe, sd_notify

async def _http_get(port, path):
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(f"GET {path} HTTP/1.0\r\n\r\n".encode())
    await w.drain()
    data = await r.read()
    w.close()
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split()[1])
    return status, json.loads(body) if body else {}

class TestHealthProbe(unittest.TestCase):
    def _run(self, coro):
        return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)

    def test_healthz_readyz_and_404(self):
        async def scenario():
            state = {"ready": True, "reasons": []}
            probe = HealthProbe(lambda: (state["ready"], state["reasons"]),
                                bind="127.0.0.1", port=0)
            port = await probe.start()
            s, b = await _http_get(port, "/healthz")
            assert (s, b["ok"]) == (200, True)
            s, b = await _http_get(port, "/readyz")
            assert (s, b["ready"]) == (200, True)
            state["ready"], state["reasons"] = False, ["no heartbeat"]
            s, b = await _http_get(port, "/readyz")
            assert (s, b["reasons"]) == (503, ["no heartbeat"])
            s, _ = await _http_get(port, "/nope")
            assert s == 404
            await probe.stop()
        self._run(scenario())

    def test_readiness_fn_exception_returns_503_not_crash(self):
        async def scenario():
            def bad(): raise RuntimeError("boom")
            probe = HealthProbe(bad, bind="127.0.0.1", port=0)
            port = await probe.start()
            s, b = await _http_get(port, "/readyz")
            assert s == 503 and b["ready"] is False
            await probe.stop()
        self._run(scenario())

    def test_sd_notify_noop_without_socket_and_sends_with(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOTIFY_SOCKET", None)
            sd_notify("READY=1")  # must not raise
        with tempfile.TemporaryDirectory() as d:
            sock_path = os.path.join(d, "notify.sock")
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            srv.bind(sock_path)
            srv.settimeout(2)
            with patch.dict(os.environ, {"NOTIFY_SOCKET": sock_path}):
                sd_notify("WATCHDOG=1")
            self.assertEqual(srv.recv(64), b"WATCHDOG=1")
            srv.close()

if __name__ == "__main__":
    unittest.main()
