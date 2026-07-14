import unittest


class TestWsBackendPresent(unittest.TestCase):
    """Regression guard for the WS-backend dependency.

    The live Control GUI serves /ws through a REAL uvicorn server, which needs a
    WebSocket library (`websockets` or `wsproto`). A bare `uvicorn` install has
    none, so ws="auto" resolves nothing and every /ws upgrade fails with
    "Unsupported upgrade request" (HTTP 200 instead of 101) — the whole live feed
    goes dead in production while only the GET /api/state polling fallback works.

    This is INVISIBLE to the TestClient-based WS tests (test_gui_server.py) because
    Starlette's TestClient implements WebSockets in-process, bypassing uvicorn's
    protocol layer entirely. So this test guards the dependency directly: if the
    backend is ever dropped from requirements.txt, fail loudly here.
    """

    def test_a_websocket_backend_is_importable(self):
        try:
            import websockets  # noqa: F401
            return
        except ImportError:
            pass
        try:
            import wsproto  # noqa: F401
            return
        except ImportError:
            self.fail(
                "No WebSocket backend installed (need `websockets` or `wsproto`); "
                "uvicorn cannot upgrade /ws and the live GUI feed will be dead."
            )


if __name__ == "__main__":
    unittest.main()
