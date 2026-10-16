import copy
import unittest

import test_failure_paths
from gateway_campaign import validate_gateway_capture


def fixture():
    decoded, handle, prepared, operation, _, _ = test_failure_paths.CapturePredicateTests().fixture('a02')
    decoded['records'][0]['value'][2] = {'left_ticks': 100, 'right_ticks': -100, 'duration_ms': 10000}
    return decoded, handle, prepared, operation


def sample(operation, sequence=1):
    # Canonical serialized authority_client::Request, independently specified.
    return {'version': 1, 'opcode': 8, 'flags': 0, 'role': 0,
            'runtime_nonce': operation['runtime_nonce'], 'grant': operation['grant'],
            'instance': 0, 'operation': operation['operation'], 'stream': operation['stream'],
            'sequence': sequence, 'transaction': 0, 'deadline_ns': 300, 'observation': 21,
            'acquired_earliest_ns': 0, 'acquired_latest_ns': 0, 'valid_until_ns': 0,
            'context_revision': 1, 'left_permille': 100, 'right_permille': -100,
            'reason': 0, 'reserved0': 0, 'digest': [9] * 32, 'reserved': [0] * 16}


def execution(value):
    return {'producer': 0, 'record_ordinal': 5, 'origin': 'Runtime', 'kind': 'Execution', 'value': value}


def negative_fixture(handle, prepared, operation):
    prepared['binding'] = {'attempt': list(handle.attempt), 'namespace': list(handle.namespace),
                           'principal': [7] * 32}
    kernel = {'device_identity': operation['device'], 'controller_boot': operation['boot'],
        'controller_session': operation['session'], **{k: operation[k] for k in
        ('runtime_nonce', 'instance', 'grant', 'operation', 'stream')},
        'deadline_ns': 500, 'now_ns': 300, 'state': 1, 'flags': 1, 'operation_state': 4,
        'reason': 3, 'left_permille': 0, 'right_permille': 0}
    before = {'clock_healthy': True, 'runtime': {'kernel': kernel, 'event_stream_healthy': True,
        'retiring': True, 'retirement_ready': True, 'prepared': copy.deepcopy(prepared),
        'health': {'registry_fault': 'WriterStopped', 'evidence_issues': ['WriterStopped']}}}
    after = copy.deepcopy(before); after['runtime']['kernel']['now_ns'] += 1
    return {'handle': dict(handle.json(), key=(b'd' * 32).hex()),
        'response': {'kind': 'OutcomeUnknown', 'message': 'principal mismatch',
                     'outcome_unknown': True, 'cause': None},
        'inspection': {'prepared': copy.deepcopy(prepared), 'snapshot': None, 'live_authority': False},
        'before': before, 'after': after}


class GatewayCaptureTests(unittest.TestCase):
    def test_cancel_requires_closure_inside_reserved_endpoint_interval(self):
        decoded, handle, prepared, operation = fixture()
        interval = {'started_ns': 120, 'finished_ns': 140}
        proof = validate_gateway_capture(decoded, handle, prepared, operation, 'traffic', interval)
        self.assertEqual(proof['closure_sequence'], 102)
        with self.assertRaises(AssertionError):
            validate_gateway_capture(decoded, handle, prepared, operation, 'traffic',
                                     {'started_ns': 131, 'finished_ns': 140})

    def test_gateway_death_requires_actual_revoke_not_expiry(self):
        decoded, handle, prepared, operation = fixture()
        for record in decoded['records'][3:]:
            record['value']['status']['reason'] = 3
        decoded['records'][3]['value']['kind'] = 0x30003
        interval = {'started_ns': 120, 'finished_ns': 140}
        validate_gateway_capture(decoded, handle, prepared, operation, 'lifetime', interval)
        decoded['records'][3]['value']['kind'] = 0x30002
        with self.assertRaises(AssertionError):
            validate_gateway_capture(decoded, handle, prepared, operation, 'lifetime', interval)
        decoded['records'][3]['value']['kind'] = 0x30003
        decoded['records'][3]['value']['status']['reason'] = 4
        with self.assertRaises(AssertionError):
            validate_gateway_capture(decoded, handle, prepared, operation, 'lifetime', interval)

    def test_unrelated_second_allocation_or_missing_prefix_cannot_pass(self):
        decoded, handle, prepared, operation = fixture()
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

    def test_unrelated_start_cannot_hide_outside_original_operation_filter(self):
        decoded, handle, prepared, operation = fixture()
        extra = copy.deepcopy(decoded['records'][2])
        extra['value']['sequence'] = 104
        extra['value']['status']['operation'] += 1
        decoded['records'].append(extra)
        with self.assertRaises(AssertionError):
            validate_gateway_capture(decoded, handle, prepared, operation, 'traffic',
                                     {'started_ns': 120, 'finished_ns': 140})

    def test_negative_key_proof_binds_absent_query_to_original_prepared_namespace(self):
        decoded, handle, prepared, operation = fixture()
        negative = negative_fixture(handle, prepared, operation)
        interval = {'started_ns': 120, 'finished_ns': 140}
        proof = validate_gateway_capture(decoded, handle, prepared, operation, 'traffic', interval, negative)
        self.assertEqual(proof['negative_binding']['handle'], negative['handle'])
        self.assertEqual(proof['start_count'], 1)
        self.assertTrue(proof['negative_binding']['response']['outcome_unknown'])
        self.assertTrue(proof['negative_capture_boundary']['kernel_prefix_ends_before_negative'])
        self.assertFalse(proof['negative_capture_boundary']['capture_alone_establishes_rejection'])
        for change in (lambda n: n['handle'].update(key=handle.key.hex()),
                       lambda n: n['handle'].update(namespace=(b'x' * 16).hex()),
                       lambda n: n['inspection'].update(snapshot={}),
                       lambda n: n['inspection']['prepared']['binding'].update(principal=[9] * 32),
                       lambda n: n['response'].update(cause='EOF'),
                       lambda n: n['response'].update(message='deadline'),
                       lambda n: n['after']['runtime']['kernel'].update(operation=999),
                       lambda n: n['after']['runtime']['kernel'].update(deadline_ns=999),
                       lambda n: n['after']['runtime']['kernel'].update(flags=9),
                       lambda n: n['after']['runtime']['kernel'].update(left_permille=1),
                       lambda n: n['after'].update(clock_healthy=False)):
            bad = copy.deepcopy(negative); change(bad)
            with self.subTest(value=bad), self.assertRaises(AssertionError):
                validate_gateway_capture(decoded, handle, prepared, operation, 'traffic', interval, bad)

    def test_samples_are_counted_separately_from_one_accepted_proposal(self):
        decoded, handle, prepared, operation = fixture()
        decoded['records'] += [execution(sample(operation, n)) for n in (1, 2, 3)]
        proof = validate_gateway_capture(decoded, handle, prepared, operation, 'traffic',
                                         {'started_ns': 120, 'finished_ns': 140})
        self.assertEqual(proof['accepted_proposal_count'], 1)
        self.assertEqual(proof['sample_request_count'], 3)

    def test_unrecognized_execution_or_noncanonical_sample_cannot_be_ignored(self):
        decoded, handle, prepared, operation = fixture()
        invalid = [None, 'unknown', [], {}, {'opcode': 8},
                   dict(sample(operation), extra=0)]
        for field, value in [('version', 2), ('opcode', 7), ('flags', 1), ('role', 2),
                             ('instance', operation['instance']), ('transaction', 1),
                             ('acquired_earliest_ns', 1), ('acquired_latest_ns', 1),
                             ('valid_until_ns', 1), ('context_revision', 2),
                             ('deadline_ns', 0), ('observation', 0), ('sequence', True),
                             ('left_permille', 201), ('right_permille', -201), ('reason', 1),
                             ('reserved0', 1), ('reserved', [0] * 15 + [1]),
                             ('digest', [256] * 32)]:
            invalid.append(dict(sample(operation), **{field: value}))
        for value in invalid:
            changed = copy.deepcopy(decoded); changed['records'].append(execution(value))
            with self.subTest(value=value), self.assertRaises(AssertionError):
                validate_gateway_capture(changed, handle, prepared, operation, 'traffic',
                                         {'started_ns': 120, 'finished_ns': 140})

    def test_sample_must_match_each_request_identity_field_and_sequence(self):
        decoded, handle, prepared, operation = fixture()
        for field in ('runtime_nonce', 'grant', 'operation', 'stream'):
            request = sample(operation)
            request[field] = [99] * 16 if field == 'runtime_nonce' else request[field] + 1
            changed = copy.deepcopy(decoded); changed['records'].append(execution(request))
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate_gateway_capture(changed, handle, prepared, operation, 'traffic',
                                         {'started_ns': 120, 'finished_ns': 140})
        for values in ([sample(operation, 2)], [sample(operation), sample(operation)]):
            changed = copy.deepcopy(decoded); changed['records'] += [execution(v) for v in values]
            with self.subTest(values=values), self.assertRaises(AssertionError):
                validate_gateway_capture(changed, handle, prepared, operation, 'traffic',
                                         {'started_ns': 120, 'finished_ns': 140})

    def test_samples_cannot_hide_missing_duplicate_or_malformed_proposal(self):
        decoded, handle, prepared, operation = fixture()
        duplicate = copy.deepcopy(decoded['records'][0]); duplicate['value'][0] = [99] * 32
        malformed = copy.deepcopy(decoded['records'][0]); malformed['value'][2] = {}
        for records in ([execution(sample(operation))] + decoded['records'][1:],
                        decoded['records'] + [duplicate, execution(sample(operation))],
                        [malformed] + decoded['records'][1:],
                        [execution(sample(operation))] + decoded['records']):
            changed = copy.deepcopy(decoded); changed['records'] = records
            with self.subTest(records=records), self.assertRaises(AssertionError):
                validate_gateway_capture(changed, handle, prepared, operation, 'traffic',
                                         {'started_ns': 120, 'finished_ns': 140})
if __name__ == '__main__':
    unittest.main()
