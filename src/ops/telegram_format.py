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


_RULE = "➖➖➖➖➖➖➖➖"


def signal(symbol, strategy, side, size, price, sl, tp) -> str:
    icon = "🟢" if "BUY" in str(side).upper() else "🔴"
    return (
        "📨 <b>SMC SIGNAL GENERATED</b>\n"
        f"{_RULE}\n"
        f"🧠 <b>Model:</b> <code>{esc(strategy)}</code>\n"
        f"{icon} <b>{esc(symbol)}</b> {esc(side)}\n"
        f"⚖️ <b>Size:</b> <code>{esc(size)} Lots</code>\n"
        f"📍 <b>Entry:</b> <code>{esc(price)}</code>\n"
        f"🛡️ <b>SL:</b> <code>{esc(sl)}</code>\n"
        f"🎯 <b>TP:</b> <code>{esc(tp)}</code>"
    )


def execution(ticket, symbol, order_type, price, sl, strategy) -> str:
    # Phase 1: mirror the legacy fields exactly -- ticket/pair/type/logic.
    # price/sl are accepted but NOT rendered (still fed sl=0). SL/TP is Phase 2.
    return (
        "⚡ <b>EXECUTION CONFIRMED</b>\n"
        f"{_RULE}\n"
        f"🎫 <b>Ticket:</b> <code>#{esc(ticket)}</code>\n"
        f"💱 <b>Pair:</b> {esc(symbol)}\n"
        f"🕹️ <b>Type:</b> {esc(order_type)}\n"
        f"⚙️ <b>Logic:</b> <i>{esc(strategy)}</i>"
    )


def close(ticket, pnl, symbol="???", strategy="Unknown") -> str:
    pnl = float(pnl)
    if pnl > 500:
        icon = "🚀🔥"
    elif pnl > 0:
        icon = "💰"
    elif pnl > -50:
        icon = "📉"
    else:
        icon = "🩸"
    return (
        f"{icon} <b>POSITION CLOSED</b>\n"
        f"{_RULE}\n"
        f"🎫 <code>#{esc(ticket)}</code> <b>{esc(symbol)}</b>\n"
        f"🧠 Strat: <code>{esc(strategy)}</code>\n"
        f"💵 <b>PnL:</b> <code>${pnl:,.2f}</code>"
    )


def management(action_comment, ticket) -> str:
    comment = str(action_comment)
    icon, desc = "⚙️", comment
    if "L1" in comment:
        icon, desc = "🔒", "Ratchet L1 (Break-Even)"
    elif "L2" in comment:
        icon, desc = "💸", "Ratchet L2 (Bank 30%)"
    elif "L3" in comment:
        icon, desc = "🥂", "Ratchet L3 (Bank 50%)"
    elif "Risk" in comment:
        icon, desc = "👮", "RISK GUARD KILL"
    return f"{icon} <b>Auto-Pilot:</b> {esc(desc)}\n🎫 Trade <code>#{esc(ticket)}</code>"


def help_menu() -> str:
    return (
        "🤖 <b>TITAN SMC COMMANDER v14.4</b>\n"
        f"{_RULE}\n"
        "📊 <code>/status</code>   - Strategy Dashboard\n"
        "💰 <code>/balance</code>  - Account Equity\n"
        "📋 <code>/pending</code>  - View Pending Orders\n"
        "🛑 <code>/pause</code>    - Freeze Execution\n"
        "▶️ <code>/resume</code>   - Resume Trading\n"
        "🗑️ <code>/cancel ID</code> - Cancel Pending Order\n"
        "✂️ <code>/close ID</code> - Close Active Trade\n"
        "☠️ <code>/closeall</code> - Close All (needs /confirm)\n"
        "✅ <code>/confirm</code>  - Confirm pending action\n"
        "🚨 <code>/panic</code>    - EMERGENCY FLATTEN"
    )
