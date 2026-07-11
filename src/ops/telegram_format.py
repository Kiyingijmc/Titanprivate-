"""Pure message builders + command tokenizer for the Telegram layer.

No network, no state, no ``self`` -- every function is a plain data->string
transform so it can be unit-tested in isolation. Dynamic values are
HTML-escaped via ``esc`` because the bot sends these with parse_mode="HTML".
"""

from __future__ import annotations


def esc(v) -> str:
    """HTML-escape a dynamic value for Telegram parse_mode="HTML"."""
    s = str(v)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def parse_command(text) -> tuple[str, list[str]]:
    """Tokenize an incoming message into (command, args).

    First token only: strips a leading '/', drops any '@botname' suffix, and
    lowercases. Everything after the first whitespace token is returned as args.
    """
    raw = str(text).strip().split()
    if not raw:
        return "", []
    cmd = raw[0].lstrip("/").split("@")[0].lower()
    return cmd, raw[1:]
