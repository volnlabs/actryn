import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_failure_paths
from gateway_lifetime import check_retirement, LifetimeCampaign, RemoteRetainer


class LifetimeTests(unittest.TestCase):
    def test_secondary_writer_stop_allowed_but_clock_storage_or_source_fault_not_hidden(self):
        _, _, _, operation, _, _ = test_failure_paths.CapturePredicateTests().fixture()
        kernel = {'device_identity': operation['device'], 'controller_boot': operation['boot'],
            'controller_session': operation['session'], **{k: operation[k] for k in ('runtime_nonce', 'grant', 'operation', 'stream')},
            'reason': 3, 'flags': 0, 'operation_state': 4, 'left_permille': 0, 'right_permille': 0}
        good = {'clock_healthy': True, 'runtime': {'kernel': kernel, 'event_stream_healthy': True,
            'health': {'registry_fault': None, 'evidence_issues': ['WriterStopped']}}}
        check_retirement(good, operation)
        for change in (lambda d: d.update(clock_healthy=False),
                       lambda d: d['runtime'].update(event_stream_healthy=False),
                       lambda d: d['runtime']['health']['evidence_issues'].append('PendingAge'),
                       lambda d: d['runtime']['health'].update(registry_fault='Storage'),
                       lambda d: d['runtime']['kernel'].update(reason=4)):
            value = copy.deepcopy(good); change(value)
            with self.assertRaises(AssertionError):
                check_retirement(value, operation)

    def test_kill_line_failure_never_resends_command(self):
        campaign = SimpleNamespace(pins={'gateway_pid': 42})
        retained = RemoteRetainer(campaign)
        retained.process = Mock()
        retained.line = Mock(side_effect=TimeoutError('lost death response'))
        with patch('gateway_lifetime.write_json'):
            with self.assertRaises(TimeoutError):
                retained.kill_once()
            with self.assertRaises(AssertionError):
                retained.kill_once()
        retained.process.stdin.write.assert_called_once_with(b'kill\n')

    def test_start_outcome_unknown_cannot_trigger_second_start(self):
        campaign = LifetimeCampaign(SimpleNamespace(ssh_key='unused', ssh_port=1, known_hosts='unused'))
        with patch('gateway_lifetime.write_json'), patch('gateway_lifetime.subprocess.run',
                side_effect=TimeoutError('lost service result')) as run:
            with self.assertRaises(TimeoutError):
                campaign.service_once('start')
            with self.assertRaises(AssertionError):
                campaign.service_once('start')
            run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
