import copy
import unittest

import test_failure_paths
from gateway_campaign import validate_gateway_capture


class GatewayCaptureTests(unittest.TestCase):
    def test_cancel_requires_closure_inside_reserved_endpoint_interval(self):
        decoded, handle, prepared, operation, _, _ = test_failure_paths.CapturePredicateTests().fixture('a02')
        interval = {'started_ns': 120, 'finished_ns': 140}
        proof = validate_gateway_capture(decoded, handle, prepared, operation, 'traffic', interval)
        self.assertEqual(proof['closure_sequence'], 102)
        with self.assertRaises(AssertionError):
            validate_gateway_capture(decoded, handle, prepared, operation, 'traffic',
                                     {'started_ns': 131, 'finished_ns': 140})

    def test_gateway_death_requires_actual_revoke_not_expiry(self):
        decoded, handle, prepared, operation, _, _ = test_failure_paths.CapturePredicateTests().fixture('a02')
        for record in decoded['records'][3:]:
            record['value']['status']['reason'] = 3
        interval = {'started_ns': 120, 'finished_ns': 140}
        validate_gateway_capture(decoded, handle, prepared, operation, 'lifetime', interval)
        decoded['records'][3]['value']['status']['reason'] = 4
        with self.assertRaises(AssertionError):
            validate_gateway_capture(decoded, handle, prepared, operation, 'lifetime', interval)

    def test_unrelated_second_allocation_or_missing_prefix_cannot_pass(self):
        decoded, handle, prepared, operation, _, _ = test_failure_paths.CapturePredicateTests().fixture('a02')
        interval = {'started_ns': 120, 'finished_ns': 140}
        other = copy.deepcopy(decoded['records'][1])
        other['value']['sequence'] = 104
        other['value']['status']['operation'] += 1
        decoded['records'].append(other)
        with self.assertRaises(AssertionError):
            validate_gateway_capture(decoded, handle, prepared, operation, 'traffic', interval)
        decoded['records'].pop()
        decoded['frontiers'][1]['durable'] -= 1
        with self.assertRaises(AssertionError):
            validate_gateway_capture(decoded, handle, prepared, operation, 'traffic', interval)


if __name__ == '__main__':
    unittest.main()
