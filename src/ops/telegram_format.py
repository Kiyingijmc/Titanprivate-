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


def _fmt_rr(entry, sl, tp) -> str:
    """Reward:risk as '1:2.5'; '—' when any leg is missing/zero."""
    try:
        entry, sl, tp = float(entry), float(sl), float(tp)
        risk, reward = abs(entry - sl), abs(tp - entry)
        if entry == 0 or sl == 0 or tp == 0 or risk <= 0 or reward <= 0:
            return "—"
        return f"1:{reward / risk:.1f}"
    except (TypeError, ValueError, ZeroDivisionError):
        return "—"


def _fmt_money(amount) -> str:
    """'$1,234.50'; '—' when unknown (0.0 sentinel from money_for_move)."""
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return "—"
    return "—" if amt == 0 else f"${amt:,.2f}"


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


def execution(ticket, symbol, order_type, entry, sl, tp, lots, grade, risk_money, strategy) -> str:
    return (
        "⚡ <b>EXECUTION CONFIRMED</b>\n"
        f"{_RULE}\n"
        f"🎫 <b>Ticket:</b> <code>#{esc(ticket)}</code>\n"
        f"💱 <b>Pair:</b> {esc(symbol)} · {esc(order_type)}\n"
        f"📍 <b>Entry:</b> <code>{esc(entry)}</code>\n"
        f"🛡️ <b>SL:</b> <code>{esc(sl)}</code>   🎯 <b>TP:</b> <code>{esc(tp)}</code>\n"
        f"⚖️ <b>RR:</b> <code>{_fmt_rr(entry, sl, tp)}</code>   📦 <b>Lots:</b> <code>{esc(lots)}</code>\n"
        f"🏅 <b>Grade:</b> <code>{esc(grade)}</code>   💵 <b>Risk:</b> <code>{_fmt_money(risk_money)}</code>\n"
        f"⚙️ <b>Logic:</b> <i>{esc(strategy)}</i>"
    )


def format_duration(seconds) -> str:
    """'2d 5h' / '3h 15m' / '2m' / '45s'. Negative clamps to 0s."""
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return ""
    if s < 0:
        s = 0
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m"
    return f"{s}s"


def close(ticket, pnl, symbol="???", strategy="Unknown", hold_seconds=None, r_multiple=None) -> str:
    pnl = float(pnl)
    if pnl > 500:
        icon = "🚀🔥"
    elif pnl > 0:
        icon = "💰"
    elif pnl > -50:
        icon = "📉"
    else:
        icon = "🩸"
    lines = [
        f"{icon} <b>POSITION CLOSED</b>",
        _RULE,
        f"🎫 <code>#{esc(ticket)}</code> <b>{esc(symbol)}</b>",
        f"🧠 Strat: <code>{esc(strategy)}</code>",
        f"💵 <b>PnL:</b> <code>${pnl:,.2f}</code>",
    ]
    if r_multiple is not None:
        lines.append(f"📐 <b>R:</b> <code>{r_multiple:+.1f}R</code>")
    if hold_seconds is not None:
        lines.append(f"⏱ <b>Hold:</b> <code>{format_duration(hold_seconds)}</code>")
    return "\n".join(lines)


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
