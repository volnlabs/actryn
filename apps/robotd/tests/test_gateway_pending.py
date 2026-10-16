import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gateway_campaign import GatewayCampaign, acknowledged_running
from guest import RequestHandle


class PendingTests(unittest.TestCase):
    def fixture(self):
        handle = RequestHandle(b'a' * 16, b'n' * 16, b'k' * 32)
        snapshot = dict(namespace=list(handle.namespace), key=list(handle.key), phase='PendingIntent',
                        revision=1, durable_revision=0, operation=None, terminal=False,
                        persistence_failed=False, cancellation_durable=False)
        result = {'calls': 1, 'automatic_retries': 0, 'reply': copy.deepcopy(snapshot)}
        kernel = dict(device_identity=[1]*16, controller_boot=2, controller_session=3,
                      runtime_nonce=[4]*16, grant=5, instance=6, operation=7, stream=8,
                      state=2, operation_state=2, flags=9)
        description = {'clock_healthy': True, 'runtime': {'kernel': kernel,
            'health': {'healthy': True}, 'event_stream_healthy': True,
            'prepared': {'binding': {'attempt': list(handle.attempt), 'namespace': list(handle.namespace)}}}}
        return handle, result, {'live_authority': True, 'snapshot': snapshot}, description

    def test_pending_reply_waits_for_original_handle_without_proposal_retry(self):
        handle, result, query, description = self.fixture()
        self.assertIsNone(acknowledged_running(handle, result, query, description))
        from failure_paths import operation_id
        operation = operation_id(description['runtime']['kernel'])
        query['snapshot'].update(operation=operation, phase='Submitted', durable_revision=1)
        self.assertEqual(acknowledged_running(handle, result, query, description), operation)
        campaign = GatewayCampaign(SimpleNamespace(ssh_key='unused', ssh_port=1, known_hosts='unused'))
        campaign.handle = handle
        rpc = Mock(_timeout=5, query=Mock(return_value=query), describe=Mock(return_value=description))
        with patch('gateway_campaign.write_json'):
            self.assertEqual(campaign.confirm_running(rpc, result), operation)
        rpc.propose.assert_not_called()
        self.assertEqual(rpc._timeout, 5)

    def test_unknown_cancelled_or_mismatched_identity_cannot_pass(self):
        from failure_paths import operation_id
        for corrupt in ('unknown', 'terminal', 'key', 'instance', 'ack-operation'):
            handle, result, query, description = self.fixture()
            operation = operation_id(description['runtime']['kernel'])
            query['snapshot'].update(operation=operation, phase='Submitted')
            if corrupt == 'unknown': result = {'calls': 1, 'outcome_unknown': True}
            if corrupt == 'terminal': query['snapshot'].update(terminal=True)
            if corrupt == 'key': query['snapshot']['key'][0] += 1
            if corrupt == 'instance': query['snapshot']['operation']['instance'] += 1
            if corrupt == 'ack-operation': result['reply']['operation'] = dict(operation, stream=99)
            with self.subTest(corrupt=corrupt), self.assertRaises(AssertionError):
                acknowledged_running(handle, result, query, description)

    def test_deadline_stops_readonly_polling_and_restores_rpc_timeout(self):
        handle, result, query, description = self.fixture()
        campaign = GatewayCampaign(SimpleNamespace(ssh_key='unused', ssh_port=1, known_hosts='unused'))
        campaign.handle = handle
        rpc = Mock(_timeout=5, query=Mock(return_value=query), describe=Mock(return_value=description))
        with patch('gateway_campaign.time.monotonic', side_effect=[0, .1, .2, 1.1]), \
                patch('gateway_campaign.time.sleep'), patch('gateway_campaign.write_json'):
            with self.assertRaises(AssertionError): campaign.confirm_running(rpc, result)
        rpc.query.assert_called_once_with(handle)
        rpc.propose.assert_not_called()
        self.assertEqual(rpc._timeout, 5)


if __name__ == '__main__':
    unittest.main()
