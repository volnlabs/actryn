import copy
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_failure_paths
from test_gateway_capture import negative_fixture
from gateway_lifetime import check_retirement, LifetimeCampaign, RemoteRetainer
from actryn import OutcomeUnknown, RequestHandle, RpcError


class LifetimeTests(unittest.TestCase):
    def negative_probe(self):
        campaign = LifetimeCampaign(SimpleNamespace(ssh_key='unused', ssh_port=1, known_hosts='unused'))
        campaign.handle = RequestHandle(b'a' * 16, b'n' * 16, b'k' * 32)
        denied = RequestHandle(b'a' * 16, b'n' * 16, b'd' * 32)
        campaign.prepared = {'binding': {'attempt': list(denied.attempt),
            'namespace': list(denied.namespace), 'principal': [7] * 32}, 'runtime_epoch': [8] * 16}
        operation = test_failure_paths.CapturePredicateTests().fixture()[3]
        proof = negative_fixture(campaign.handle, campaign.prepared, operation)
        campaign.local = Mock(side_effect=[proof['before'], proof['after']])
        rpc = Mock()
        rpc.propose.side_effect = OutcomeUnknown('principal mismatch')
        rpc.query.return_value = {'snapshot': None, 'live_authority': False,
                                  'prepared': copy.deepcopy(campaign.prepared)}
        return campaign, denied, rpc, operation

    def test_server_unknown_is_preserved_then_original_negative_key_queried_once(self):
        campaign, denied, rpc, operation = self.negative_probe()
        with patch('gateway_lifetime.write_json') as save:
            campaign.probe_old_binding(rpc, denied, {'id': 17}, operation)
        rpc.propose.assert_called_once()
        self.assertEqual(rpc.propose.call_args.args, (denied,))
        rpc.query.assert_called_once_with(denied)
        self.assertTrue(campaign.negative_binding['response']['outcome_unknown'])
        self.assertEqual(campaign.negative_binding['handle'], denied.json())
        self.assertEqual(save.call_args_list[1].args[0], 'old-binding-response.json')
        with self.assertRaises(AssertionError):
            campaign.probe_old_binding(rpc, denied, {'id': 17}, operation)
        rpc.propose.assert_called_once()

    def test_unrelated_unknown_transport_failure_or_success_never_proves_rejection(self):
        transport = OutcomeUnknown('principal mismatch')
        transport.__cause__ = EOFError('missing reply')
        for error in (transport, OutcomeUnknown('storage deadline'),
                      RpcError('REJECTED: stale observation'), OSError('closed'), None):
            campaign, denied, rpc, operation = self.negative_probe()
            rpc.propose.side_effect = error
            with patch('gateway_lifetime.write_json'), self.assertRaises((AssertionError, OSError)):
                campaign.probe_old_binding(rpc, denied, {'id': 17}, operation)
            rpc.propose.assert_called_once()
            rpc.query.assert_not_called()

    def test_absent_negative_key_requires_exact_binding_and_no_live_authority(self):
        for change in (lambda q: q.update(snapshot={}), lambda q: q.update(live_authority=True),
                       lambda q: q['prepared']['binding'].update(principal=[9] * 32),
                       lambda q: q['prepared']['binding'].update(namespace=[9] * 16),
                       lambda q: q['prepared'].update(runtime_epoch=[9] * 16)):
            campaign, denied, rpc, operation = self.negative_probe()
            change(rpc.query.return_value)
            with patch('gateway_lifetime.write_json'), self.assertRaises(AssertionError):
                campaign.probe_old_binding(rpc, denied, {'id': 17}, operation)
            rpc.propose.assert_called_once()
            rpc.query.assert_called_once_with(denied)

    def test_wrong_negative_handle_never_sends_and_explicit_rejection_still_needs_query(self):
        campaign, denied, rpc, operation = self.negative_probe()
        with self.assertRaises(AssertionError):
            campaign.probe_old_binding(rpc, campaign.handle, {'id': 17}, operation)
        rpc.propose.assert_not_called()
        campaign.local.assert_not_called()
        rpc.propose.side_effect = RpcError('REJECTED: principal mismatch')
        with patch('gateway_lifetime.write_json'):
            campaign.probe_old_binding(rpc, denied, {'id': 17}, operation)
        rpc.query.assert_called_once_with(denied)
        self.assertFalse(campaign.negative_binding['response']['outcome_unknown'])

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

    def test_registry_writer_stop_requires_completed_retirement(self):
        _, _, _, operation, _, _ = test_failure_paths.CapturePredicateTests().fixture()
        kernel = {'device_identity': operation['device'], 'controller_boot': operation['boot'],
            'controller_session': operation['session'], **{k: operation[k] for k in
            ('runtime_nonce', 'grant', 'operation', 'stream')}, 'reason': 3, 'flags': 1,
            'operation_state': 4, 'left_permille': 0, 'right_permille': 0}
        value = {'clock_healthy': True, 'runtime': {'kernel': kernel, 'event_stream_healthy': True,
            'retiring': True, 'retirement_ready': True,
            'health': {'registry_fault': 'WriterStopped', 'evidence_issues': ['WriterStopped']}}}
        check_retirement(value, operation)
        for field in ('retiring', 'retirement_ready'):
            bad = copy.deepcopy(value); bad['runtime'][field] = False
            with self.subTest(field=field), self.assertRaises(AssertionError):
                check_retirement(bad, operation)

    def test_start_outcome_unknown_cannot_trigger_second_start(self):
        campaign = LifetimeCampaign(SimpleNamespace(ssh_key='unused', ssh_port=1, known_hosts='unused'))
        with patch('gateway_lifetime.write_json'), patch('gateway_lifetime.subprocess.run',
                side_effect=TimeoutError('lost service result')) as run:
            with self.assertRaises(TimeoutError):
                campaign.service_once('start')
            with self.assertRaises(AssertionError):
                campaign.service_once('start')
            run.assert_called_once()

    def test_installed_replacement_can_finish_after_preflight_but_remains_bounded(self):
        for becomes_ready in (True, False):
            campaign = LifetimeCampaign(SimpleNamespace(ssh_key='unused', ssh_port=1, known_hosts='unused'))
            campaign.pins = {'gateway_pid': 42}
            clock = [0.0]
            def read_status():
                clock[0] += 6.5
                ready = becomes_ready and clock[0] >= 26
                return {'pid': 43 if ready else 0, 'active_state': 'active' if ready else 'activating',
                        'sub_state': 'running' if ready else 'start'}
            campaign.gateway_status = Mock(side_effect=read_status)
            with patch('failure_paths.time.monotonic', side_effect=lambda: clock[0]), \
                    patch('failure_paths.time.sleep'), patch('failure_paths.write_json'):
                if becomes_ready:
                    self.assertEqual(campaign.replacement_pid(), 43)
                    self.assertEqual(campaign.gateway_status.call_count, 4)
                else:
                    with self.assertRaises(AssertionError):
                        campaign.replacement_pid()
                    self.assertEqual(campaign.gateway_status.call_count, 7)

    def test_installed_start_budget_does_not_expand_stop_or_retry_mutations(self):
        for action, expected in [('start', 40), ('stop', 15)]:
            campaign = LifetimeCampaign(SimpleNamespace(ssh_key='unused', ssh_port=1, known_hosts='unused'))
            completed = SimpleNamespace(returncode=0, stdout=b'', stderr=b'', check_returncode=Mock())
            with patch('gateway_lifetime.write_json'), patch('gateway_lifetime.subprocess.run',
                    return_value=completed) as run:
                campaign.service_once(action)
                self.assertEqual(run.call_args.kwargs['timeout'], expected)
                with self.assertRaises(AssertionError):
                    campaign.service_once(action)
                run.assert_called_once()

    def test_replacement_pid_during_exec_setup_does_not_begin_authentication(self):
        campaign = LifetimeCampaign(SimpleNamespace(ssh_key='unused', ssh_port=1, known_hosts='unused'))
        campaign.pins = {'gateway_pid': 42}
        campaign.gateway_pid = Mock(return_value=43)
        campaign.gateway_status = Mock(side_effect=[
            {'pid': 42, 'active_state': 'active', 'sub_state': 'running'},
            {'pid': 43, 'active_state': 'activating', 'sub_state': 'start'},
            {'pid': 43, 'active_state': 'active', 'sub_state': 'exited'},
            {'pid': 43, 'active_state': 'active', 'sub_state': 'running'}])
        with patch('failure_paths.time.sleep'), patch('failure_paths.write_json'):
            self.assertEqual(campaign.replacement_pid(), 43)
        self.assertEqual(campaign.gateway_status.call_count, 4)

    def test_gateway_status_requires_complete_unit_state(self):
        campaign = LifetimeCampaign(SimpleNamespace(ssh_key='unused', ssh_port=1, known_hosts='unused'))
        campaign.run = Mock(return_value=b'MainPID=43\nActiveState=activating\nSubState=start\n')
        self.assertEqual(campaign.gateway_status(),
            {'pid': 43, 'active_state': 'activating', 'sub_state': 'start'})
        campaign.run.return_value = b'MainPID=43\n'
        with self.assertRaises(AssertionError):
            campaign.gateway_status()


if __name__ == '__main__':
    unittest.main()
