"""Registry lifecycle for the GUI. The promote-gate stays server-side in the
registry (enable(allow_research=...)); this module only decides whether the
typed-id confirmation was supplied — it can never bypass the gate."""


def registry_report(controller) -> list:
    return controller.registry.report()


def execute_registry_action(controller, strategy_id: str, action: str, payload: dict) -> dict:
    if action == "enable":
        return {"status": "ok", "result": controller.enable_strategy(strategy_id)}
    if action == "disable":
        return {"status": "ok", "result": controller.disable_strategy(strategy_id)}
    if action == "promote":
        if payload.get("confirm") != strategy_id:
            return {"status": "needs_confirm", "expect": strategy_id,
                    "detail": "promote requires body {'confirm': '<strategy_id>'}"}
        return {"status": "ok",
                "result": controller.enable_strategy(strategy_id, allow_research=True)}
    return {"status": "error", "detail": f"unknown registry action '{action}'"}
