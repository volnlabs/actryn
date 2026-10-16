import copy
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_failure_paths
from gateway_lifetime import check_retirement, LifetimeCampaign, RemoteRetainer


class LifetimeTests(unittest.TestCase):
    def preload_order(self, preload_fails=False):
        events = []
        class Stopped(RuntimeError):
            pass
        campaign = LifetimeCampaign(SimpleNamespace(ssh_key='unused', ssh_port=1, known_hosts='unused'))
        campaign.handle = SimpleNamespace(attempt=bytes(16), namespace=bytes(16), json=lambda: {})
        campaign.setup = Mock(); campaign.activate = Mock(); campaign.save_other_handle = Mock()
        campaign.local = Mock()  # Planned cleanup cannot contact a real manager.
        rpc = SimpleNamespace(describe=lambda: events.append('describe') or {},
            observe=lambda *_: events.append('observe') or {'id': 1})
        @contextmanager
        def connection():
            events.append('connected')
            try: yield rpc
            finally: events.append('disconnected')
        campaign.connection = connection
        campaign.start_checked = lambda *_: events.append('propose')
        campaign.confirm_running = lambda *_: events.append('running') or {}
        def proposal(*_):
            events.append('proposal-created')
            return SimpleNamespace(finish=lambda: events.append('reply') or {})
        def kill():
            events.append('kill')
            raise Stopped('stop before closure polling')
        @contextmanager
        def retained(_):
            events.append('retained')
            if preload_fails:
                raise Stopped('preload unavailable')
            try: yield SimpleNamespace(kill_once=kill)
            finally: events.append('released')
        with patch('gateway_lifetime.RemoteRetainer', retained), \
                patch('gateway_lifetime.OneProposal', proposal), \
                patch('gateway_lifetime.write_json'), patch('gateway_lifetime.phase'):
            with self.assertRaises(Stopped):
                campaign.run_campaign()
        return events

    def test_retainer_ready_precedes_single_observation_proposal_running_and_kill(self):
        self.assertEqual(self.preload_order(), ['connected', 'describe', 'retained', 'observe',
            'proposal-created', 'propose', 'reply', 'running', 'kill', 'released', 'disconnected'])

    def test_failed_preload_never_observes_proposes_or_signals(self):
        self.assertEqual(self.preload_order(True), ['connected', 'describe', 'retained', 'disconnected'])

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
