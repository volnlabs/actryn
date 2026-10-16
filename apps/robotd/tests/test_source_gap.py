import copy
import signal
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import omit_kernel_event as omit
from source_gap import Campaign, validate_capture, wire


class OmissionTests(unittest.TestCase):
    def test_action_failure_and_stop_failure_both_attempt_resume_once(self):
        for fail_stop in (False, True):
            calls = []
            def send(fd, sig):
                calls.append((fd, sig))
                if fail_stop and sig == signal.SIGSTOP:
                    raise OSError('stop rejected')
            result = omit.paused_once(7, Mock(side_effect=RuntimeError('read failed')), send=send)
            self.assertEqual(calls, [(7, signal.SIGSTOP), (7, signal.SIGCONT)])
            self.assertTrue(result['resumed'])
            self.assertIn('error', result)

    def test_resume_failure_is_explicit_and_never_retried(self):
        send = Mock(side_effect=[None, OSError('resume unavailable')])
        result = omit.paused_once(7, lambda: {'event_hex': 'abcd'}, send=send)
        self.assertEqual(send.call_count, 2)
        self.assertFalse(result['resumed'])
        self.assertIn('resume_error', result)
        self.assertEqual(result['event_hex'], 'abcd')

    def test_read_is_consumed_at_most_once_and_not_retried(self):
        poll = Mock()
        poll.poll.return_value = [(9, omit.select.POLLIN)]
        read = Mock(return_value=b'raw retained before validation')
        self.assertEqual(omit.consume_one(9, 100, now=lambda: 1,
                         poll_factory=lambda: poll, read=read), read.return_value)
        read.assert_called_once_with(9, 216)
        read.reset_mock(side_effect=True)
        read.side_effect = BlockingIOError('raced event')
        with self.assertRaises(BlockingIOError):
            omit.consume_one(9, 100, now=lambda: 1, poll_factory=lambda: poll, read=read)
        self.assertEqual(read.call_count, 1)
        read.reset_mock(side_effect=True)
        poll.poll.return_value = []
        with self.assertRaises(AssertionError):
            omit.consume_one(9, 100, now=lambda: 1, poll_factory=lambda: poll, read=read)
        read.assert_not_called()

    def test_exact_uapi_layout_rejects_malformed_fields(self):
        raw = bytearray(216)
        struct.pack_into('<QQII', raw, 0, 100, 1, 0x2000c, 0)
        struct.pack_into('<I', raw, 24, 1)
        event = omit.decode_event(raw)
        self.assertEqual(event['sequence'], 100)
        self.assertEqual(len(event['status']['runtime_nonce']), 16)
        for index in (20, 36, 212):
            bad = bytearray(raw)
            bad[index] = 1
            with self.assertRaises(AssertionError):
                omit.decode_event(bad)
        with self.assertRaises(AssertionError):
            omit.decode_event(raw[:-1])


class CaptureChecks(unittest.TestCase):
    def fixture(self):
        status = {'runtime_nonce': [7]*16, 'events_lost': 4, 'grant': 0, 'state': 1,
                  'operation': 0, 'operation_state': 0, 'flags': 1,
                  'left_permille': 0, 'right_permille': 0}
        omitted = {'event': {'sequence': 101, 'status': status}}
        decoded = {'attempt': [1]*16, 'policy': 'MetadataOnly', 'issues': [], 'raw_remnants': [],
            'volatile_tail_unknown': True, 'execution_replay_eligible': False,
            'replay_missing': ['retained external source fault'],
            'source_faults': [{'producer': 1, 'origin': 'Kernel', 'metadata': True,
                'record_ordinal': 9, 'source_time_ns': 42,
                'previous_kernel_record': {'record_ordinal': 8, 'metadata_value': {'sequence': 100}},
                'metadata_value': {'fault': {'source': 'kernel.event', 'epoch': [7]*16,
                    'previous_sequence': 100, 'observed_sequence': 102,
                    'sequence_discontinuity': True, 'loss_baseline': 4, 'observed_loss': 4,
                    'loss_counter_changed': False},
                    'event': {'sequence': 102, 'captured_ns': 42, 'status': status}}}],
            'sources': [{}, {'producer': 1, 'missing_record_ordinals': [],
                        'source_gap_record_ordinals': [9], 'durable_frontier': 9}],
            'frontiers': [{}, {'gap_count': 1}]}
        return decoded, omitted

    def test_external_jump_and_contiguous_local_ordinals_are_distinct(self):
        decoded, omitted = self.fixture()
        self.assertEqual(validate_capture(decoded, omitted, bytes([1]*16), 4)['record_ordinal'], 9)

    def test_incomplete_wrong_loss_or_replayable_evidence_fails(self):
        changes = [lambda d: d.update(execution_replay_eligible=True),
                   lambda d: d['frontiers'][1].update(gap_count=0),
                   lambda d: d['sources'][1].update(missing_record_ordinals=[[9, 10]]),
                   lambda d: d['source_faults'][0]['metadata_value']['fault'].update(observed_loss=5),
                   lambda d: d['source_faults'][0]['metadata_value']['fault'].update(previous_sequence=99),
                   lambda d: d['source_faults'][0].update(source_time_ns=43),
                   lambda d: d['source_faults'][0]['metadata_value']['event']['status'].update(grant=1)]
        for change in changes:
            decoded, omitted = self.fixture()
            decoded = copy.deepcopy(decoded)
            change(decoded)
            with self.assertRaises(AssertionError):
                validate_capture(decoded, omitted, bytes([1]*16), 4)


class MutationReplyTests(unittest.TestCase):
    def test_unknown_reply_or_lost_reply_stays_unknown_without_retry(self):
        request_id = bytes([1]*16)
        response = wire.Response(version=1, request_id=request_id, robot_epoch=bytes([2]*16),
                                 failure=wire.Failure(code=wire.Failure.OUTCOME_UNKNOWN, message='uncertain'))
        for reply in (response.SerializeToString(deterministic=True), TimeoutError('reply lost')):
            campaign = Campaign(SimpleNamespace(ssh_key='unused', ssh_port=26221, known_hosts='unused'))
            campaign.run = Mock(side_effect=reply) if isinstance(reply, Exception) else Mock(return_value=reply)
            with patch('source_gap.secrets.token_bytes', return_value=request_id), patch('source_gap.write_json') as save:
                with self.assertRaises((RuntimeError, TimeoutError)):
                    campaign.local('recover', label='once')
                campaign.run.assert_called_once()
                filename, document = save.call_args.args
                self.assertEqual(filename, 'once-unknown.json')
                self.assertTrue(document['mutation_outcome_unknown'])
                self.assertFalse(document['automatic_retry'])


if __name__ == '__main__':
    unittest.main()
