# tests/unit/test_gui_auth.py
import unittest
import os
from fastapi import HTTPException
from src.ops.web import auth


class _Req:
    """Minimal stand-in for fastapi.Request in dependency-level tests."""
    def __init__(self, token=None, ip="1.2.3.4"):
        self.headers = {"authorization": f"Bearer {token}"} if token else {}
        self.client = type("C", (), {"host": ip})()


class TokenEnv(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get("TITAN_GUI_TOKEN")
        os.environ["TITAN_GUI_TOKEN"] = "sekret"
        auth.THROTTLE.reset()

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("TITAN_GUI_TOKEN", None)
        else:
            os.environ["TITAN_GUI_TOKEN"] = self._prev
        os.environ.pop("TITAN_GUI_READONLY", None)
        auth.THROTTLE.reset()


class TestTokenOk(TokenEnv):
    def test_correct_token_passes(self):
        self.assertTrue(auth.token_ok("sekret"))

    def test_wrong_missing_or_unset_fails(self):
        self.assertFalse(auth.token_ok("nope"))
        self.assertFalse(auth.token_ok(None))
        os.environ.pop("TITAN_GUI_TOKEN", None)
        self.assertFalse(auth.token_ok("sekret"))  # fail closed


class TestRequireToken(TokenEnv):
    def test_valid_header_passes(self):
        auth.require_token(_Req(token="sekret"))  # no raise

    def test_bad_token_401_and_recorded(self):
        with self.assertRaises(HTTPException) as ctx:
            auth.require_token(_Req(token="wrong"))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_throttle_429_after_limit(self):
        for _ in range(5):
            with self.assertRaises(HTTPException):
                auth.require_token(_Req(token="wrong", ip="9.9.9.9"))
        with self.assertRaises(HTTPException) as ctx:
            auth.require_token(_Req(token="sekret", ip="9.9.9.9"))  # even correct token
        self.assertEqual(ctx.exception.status_code, 429)

    def test_other_ip_unaffected_by_throttle(self):
        for _ in range(5):
            with self.assertRaises(HTTPException):
                auth.require_token(_Req(token="wrong", ip="9.9.9.9"))
        auth.require_token(_Req(token="sekret", ip="8.8.8.8"))  # no raise


class TestReadOnly(TokenEnv):
    def test_readonly_env_blocks_writes(self):
        os.environ["TITAN_GUI_READONLY"] = "1"
        with self.assertRaises(HTTPException) as ctx:
            auth.require_writable()
        self.assertEqual(ctx.exception.status_code, 403)

    def test_default_is_writable(self):
        auth.require_writable()  # no raise


if __name__ == "__main__":
    unittest.main()
