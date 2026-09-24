"""Read-only, JSON-safe view of durable management state; never issues commands."""
import json
import math


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _object(value):
    if not value:
        return {}
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, dict):
        raise ValueError('Invalid management object')
    return result


def management_view(controller, position, row):
    if not row:
        return None
    try:
        profile = _object(row.get('management_profile'))
        intent = _object(row.get('management_intent'))
        level = int(row.get('ratchet_level') or 0)
        mode = profile.get('mode') or ('legacy' if level > 0 or intent else 'unassigned')
        if mode not in ('legacy', 'm15_structure_v1', 'unassigned'):
            return None
        entry = _number(row.get('initial_entry'))
        target = _number(row.get('initial_tp'))
        is_long = int(position.get('type', 0)) == 0
        direction = 1 if is_long else -1
        quotes = getattr(controller, 'live_prices' if is_long else 'live_asks', {}) or {}
        current = _number(quotes.get(position.get('s')))
        progress = None
        if entry and target and current and direction*(target-entry) > 0:
            progress = _number(100 * direction*(current-entry) / abs(target-entry))
        settings = profile.get('settings') or {}
        first = _number(settings.get('first_progress', .5))
        first = first * 100 if first is not None and 0 < first < 1 else None
        manager = getattr(controller, 'trade_manager', None)
        contexts = getattr(manager, '_structure_context', {}) or {}
        context = contexts.get(position.get('s')) if isinstance(contexts, dict) else None
        return {
            'mode': mode,
            'confirmed_level': level,
            'confirmed_partial_stage': int(row.get('partial_stage') or 0),
            'pending': bool(intent) or int(row.get('partial_stage_requested') or 0) > int(row.get('partial_stage') or 0),
            'requested_sl': _number(intent.get('sl')),
            'requested_tp': _number(intent.get('tp')),
            'target_volume': _number(intent.get('target_volume')) if intent.get('partial') else None,
            'original_tp': target,
            'progress_pct': round(progress, 2) if progress is not None else None,
            'first_partial_pct': first if mode == 'm15_structure_v1' else 61.8 if mode == 'legacy' else None,
            'context_ready': bool(context) if mode == 'm15_structure_v1' else None,
            'context_closed_at': str(context['closed_at']) if isinstance(context, dict) and context.get('closed_at') else None,
        }
    except (TypeError, ValueError, AttributeError, OverflowError):
        return None
