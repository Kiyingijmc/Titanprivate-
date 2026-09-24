import json
import unittest
from types import SimpleNamespace
from src.ops.web.management_view import management_view


class ManagementViewTests(unittest.TestCase):
    def setUp(self):
        self.controller = SimpleNamespace(live_prices={'EURUSD': 1.106}, live_asks={'EURUSD': 1.1062})
        self.position = {'s': 'EURUSD', 'type': 0}
        self.row = {'initial_entry': 1.1, 'initial_tp': 1.11, 'ratchet_level': 2,
                    'partial_stage': 1, 'management_profile': json.dumps({'mode': 'm15_structure_v1', 'settings': {}})}

    def test_pending_is_separate_from_confirmed_state(self):
        self.row['management_intent'] = json.dumps({'level': 3, 'sl': 1.104, 'tp': 0, 'partial': True, 'target_volume': .07})
        result = management_view(self.controller, self.position, self.row)
        self.assertEqual(result['confirmed_level'], 2)
        self.assertEqual(result['confirmed_partial_stage'], 1)
        self.assertTrue(result['pending'])
        self.assertEqual(result['target_volume'], .07)
        self.assertAlmostEqual(result['progress_pct'], 60)
        self.assertFalse(result['context_ready'])
        self.assertEqual(result['first_partial_pct'], 50)

    def test_short_uses_ask_and_never_falls_back_to_bid(self):
        self.position['type'] = 1
        self.row.update(initial_entry=1.11, initial_tp=1.1)
        result = management_view(self.controller, self.position, self.row)
        self.assertAlmostEqual(result['progress_pct'], 38)
        self.controller.live_asks = {}
        self.assertIsNone(management_view(self.controller, self.position, self.row)['progress_pct'])

    def test_corrupt_or_absent_state_does_not_claim_management(self):
        self.assertIsNone(management_view(self.controller, self.position, None))
        for profile in ['{bad', '[]', '{"mode":"future_version"}']:
            self.row['management_profile'] = profile
            self.assertIsNone(management_view(self.controller, self.position, self.row))

    def test_nonfinite_data_remains_json_safe(self):
        self.controller.live_prices['EURUSD'] = float('nan')
        self.row['management_profile'] = {'mode': 'm15_structure_v1', 'settings': {'first_progress': float('inf')}}
        result = management_view(self.controller, self.position, self.row)
        self.assertIsNone(result['progress_pct'])
        self.assertIsNone(result['first_partial_pct'])
        json.dumps(result, allow_nan=False)

    def test_view_does_not_assign_or_mutate_a_profile(self):
        row = {'initial_entry': 1.1, 'initial_tp': 1.11, 'ratchet_level': 0}
        before = row.copy()
        self.assertEqual(management_view(self.controller, self.position, row)['mode'], 'unassigned')
        self.assertEqual(before, row)
