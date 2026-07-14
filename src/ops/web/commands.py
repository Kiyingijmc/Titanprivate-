"""Map GUI command payloads onto existing controller methods. No new trade logic."""

_DESTRUCTIVE = {"closeall", "panic"}


async def execute_command(controller, payload: dict) -> dict:
    command = payload.get("command")
    if command in _DESTRUCTIVE and payload.get("confirm") is not True:
        return {"status": "needs_confirm", "command": command}

    if command == "pause":
        return {"status": "ok", "result": controller.set_system_pause(True)}
    if command == "resume":
        return {"status": "ok", "result": controller.set_system_pause(False)}
    if command == "close":
        ticket = payload.get("ticket")
        if not isinstance(ticket, int) or isinstance(ticket, bool):
            return {"status": "error", "detail": "close requires integer 'ticket'"}
        return {"status": "ok", "result": await controller.close_specific_market_order(ticket)}
    if command == "closeall":
        return {"status": "ok", "result": await controller.close_all_market_orders()}
    if command == "panic":
        await controller.trigger_panic()
        return {"status": "ok", "result": "panic_executed"}
    if command == "cancel":
        return {"status": "ok", "result": await controller.cancel_pending_orders(
            payload.get("ticket", "all"))}

    return {"status": "error", "detail": "unknown command"}
