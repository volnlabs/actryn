import copy
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

import guest_observer_gap as campaign
from test_guest_capacity import complete_export, rehash


def fixture(mode='loss'):
    original = complete_export(started=mode != 'prestart')
    bundle, attempt, artifact, binding, inspection, logs, summary = copy.deepcopy(original[:7])
    values = {item['name']: item['content'] for item in bundle['artifacts']}
    fault = copy.deepcopy(binding['observer'])
    fault.update(sequence=100, lost=7, ready=False)
    if mode in ('death', 'prestart'):
        fault = None
        summary = None
        values['runtime_facts']['observer'] = None
        values['runtime_facts']['observer_health_unavailable'] = True
    else:
        values['runtime_facts']['observer'] = copy.deepcopy(fault)
        summary.update(status=copy.deepcopy(fault), local_lost=7)
    if mode == 'prestart':
        inspection['attempt']['outcome'] = 'start_rejected'
        values['broker']['attempt_outcome'] = 'start_rejected'
    else:
        inspection['evidence_gaps'] = ['observer_unavailable']
        values['broker']['evidence_gaps'] = ['observer_unavailable']
        bundle['omissions'] = [{'artifact': 'runtime_facts', 'reason': 'observer_unavailable', 'omitted_records': 1}]
    rehash(bundle)
    return bundle, attempt, artifact, binding, inspection, logs, mode, fault, summary


class ObserverGapTests(unittest.TestCase):
    def test_actual_loss_and_death_shapes_preserve_diagnostic_uncertainty(self):
        for mode in ('prestart', 'death', 'loss'):
            campaign.validate_fault_export(*fixture(mode))

    def test_hash_valid_false_passes_are_rejected(self):
        for fault in ('empty', 'gap', 'durable_gap', 'omission', 'ready', 'loss', 'epoch', 'binding',
                      'raw', 'closed', 'unknown_attempt', 'replay'):
            args = list(fixture())
            bundle, _, _, _, inspection, _, _, health, _ = args
            values = {item['name']: item['content'] for item in bundle['artifacts']}
            if fault == 'empty': bundle['artifacts'] = []
            elif fault == 'gap': values['broker']['evidence_gaps'] = []
            elif fault == 'durable_gap': inspection['evidence_gaps'] = []
            elif fault == 'omission': bundle['omissions'] = []
            elif fault == 'ready': health['ready'] = True
            elif fault == 'loss': health['lost'] = 0
            elif fault == 'epoch': health['collector_epoch'] = 'wrong-epoch'
            elif fault == 'binding': values['runtime_binding']['cgroup_id'] += 1
            elif fault == 'raw': values['stdout']['retained_sha256'] = 'sha256:' + '0' * 64
            elif fault == 'closed': values['broker']['calls'][0]['publication_closed'] = False
            elif fault == 'unknown_attempt': inspection['attempt']['outcome'] = 'unknown'
            else: bundle['execution_replay_eligible'] = True
            rehash(bundle)
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                campaign.validate_fault_export(*args)

    def test_terminal_value_arriving_after_absolute_deadline_is_not_success(self):
        def slow_read():
            time.sleep(.03)
            return 'ready'
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            campaign.wait_until(slow_read, lambda value: value == 'ready', time.monotonic() + .005)

    def test_expired_deadline_does_not_invoke_the_reader(self):
        read = Mock(return_value=True)
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            campaign.wait_until(read, bool, time.monotonic() - 1)
        read.assert_not_called()

    def test_death_cannot_claim_an_old_summary_or_continuous_ready_observer(self):
        for fault in ('summary', 'healthy', 'same_epoch'):
            args = list(fixture('death'))
            facts = next(v['content'] for v in args[0]['artifacts'] if v['name'] == 'runtime_facts')
            if fault == 'summary': args[-1] = {'status': args[3]['observer']}
            else:
                facts['observer_health_unavailable'] = False
                facts['observer'] = copy.deepcopy(args[3]['observer'])
                if fault == 'same_epoch': facts['observer']['ready'] = False
            rehash(args[0])
            with self.subTest(fault=fault), self.assertRaises(AssertionError):
                campaign.validate_fault_export(*args)

    def test_created_task_is_not_claimed_absent_or_running(self):
        raw = b'TASK PID STATUS\n' + b'a' * 32 + b' 123 CREATED\n'
        rows = campaign.task_rows(raw)
        self.assertEqual(rows['a' * 32], {'pid': 123, 'status': 'CREATED'})
        with self.assertRaises(AssertionError): campaign.task_rows(raw + raw.splitlines(keepends=True)[1])
        with self.assertRaises(AssertionError): campaign.task_rows(raw.replace(b'a' * 32, b'wrong'))

    def test_exact_guest_and_boot_are_required(self):
        expected = {'debian': '13.7', 'kernel': '6.12.111+deb13-amd64', 'arch': 'x86_64',
                    'machine': 'a' * 32, 'boot': 'original'}
        campaign.check_guest(dict(expected), expected)
        for field in expected:
            actual = dict(expected); actual[field] = 'wrong'
            with self.subTest(field=field), self.assertRaises(AssertionError):
                campaign.check_guest(actual, expected)

    def test_readiness_socket_is_bound_to_actual_root_observer_process(self):
        for pid, uid in ((99, 0), (123, 1000)):
            socket = MagicMock()
            socket.__enter__.return_value.getsockopt.return_value = campaign.struct.pack('3i', pid, uid, 0)
            with patch.object(campaign.socket, 'socket', return_value=socket):
                with self.assertRaisesRegex(AssertionError, 'identity mismatch'):
                    campaign.observer_socket_ready(123)

    def test_wrong_loaded_pin_prevents_any_stop_or_signal(self):
        for mode in ('prestart', 'death'):
            run = object.__new__(campaign.Campaign)
            run.faults, run.systemctl = set(), Mock()
            run.loaded_pins = Mock(side_effect=AssertionError('wrong loaded executable'))
            with patch.object(campaign.os, 'pidfd_open') as opened:
                with self.subTest(mode=mode), self.assertRaisesRegex(AssertionError, 'wrong loaded'):
                    run.fault(mode, 'a' * 32)
                opened.assert_not_called()
                run.systemctl.assert_not_called()

    def test_unknown_cancel_ack_is_not_retried_and_needs_observed_reap(self):
        run = object.__new__(campaign.Campaign)
        run.cancel_sent, run.deadline = set(), time.monotonic() + 1
        run.cli = Mock(side_effect=ValueError('lost reply'))
        run.record = Mock()
        run.stores = Mock(return_value={'broker': {'a' * 32: 'reaped'}, 'launcher': {'a' * 32: 'reaped'}})
        run.tasks = Mock(return_value={})
        with patch.object(campaign.Path, 'exists', return_value=False):
            run.cancel_once('a' * 32)
            with self.assertRaisesRegex(AssertionError, 'retry forbidden'): run.cancel_once('a' * 32)
        run.cli.assert_called_once_with('cancel', '--attempt', 'a' * 32)

    def test_uncleared_cancel_cannot_be_reported_as_cleanup(self):
        run = object.__new__(campaign.Campaign)
        run.cancel_sent, run.deadline = set(), time.monotonic() + .005
        run.cli, run.record = Mock(), Mock()
        run.stores = Mock(return_value={'broker': {'a' * 32: 'retiring'}, 'launcher': {'a' * 32: 'retiring'}})
        with self.assertRaisesRegex(AssertionError, 'deadline'):
            run.cancel_once('a' * 32)
        self.assertEqual(run.cli.call_count, 1)

    def test_loss_helper_cleanup_has_bounded_wait_without_context_manager_join(self):
        run = object.__new__(campaign.Campaign)
        attempt = 'a' * 32
        run.bindings, run.deadline = {attempt: {'cgroup_id': 9}}, time.monotonic() + 1
        run.record = Mock()
        process = MagicMock(pid=123)
        process.communicate.side_effect = [campaign.subprocess.TimeoutExpired('helper', 1),
                                           campaign.subprocess.TimeoutExpired('helper', 2)]
        identity = {'pid': 123, 'start_ticks': 5, 'cgroup': '0::/actryn/' + attempt}
        with (patch.object(campaign.Path, 'stat', return_value=Mock(st_ino=9)),
              patch.object(campaign.subprocess, 'Popen', return_value=process),
              patch.object(campaign, 'process_identity', return_value=identity)):
            with self.assertRaises(campaign.subprocess.TimeoutExpired): run.loss_workload(attempt)
        process.kill.assert_called_once()
        self.assertEqual(process.communicate.call_count, 2)
        self.assertEqual(process.communicate.call_args.kwargs, {'timeout': 2})
        process.__enter__.assert_not_called()
        self.assertIn('loss-helper-cleanup-unknown', [call.args[0] for call in run.record.call_args_list])

    def test_replacement_privilege_verification_follows_actual_listener_readiness(self):
        run = object.__new__(campaign.Campaign)
        run.restored, run.deadline = set(), time.monotonic() + 1
        run.systemctl, run.record = Mock(return_value=b'456'), Mock()
        old = {'actryn-observer': {'pid': 123}, 'actryn-launcher': {}, 'actryn-serverd': {}}
        new = copy.deepcopy(old); new['actryn-observer']['pid'] = 456
        order = []
        run.loaded_pins = lambda: order.append('privileges_verified') or new
        def listener(pid):
            self.assertEqual(pid, 456)
            order.append('listener_ready')
            return True
        with patch.object(campaign, 'observer_socket_ready', side_effect=listener):
            run.restore_observer_once('death', old, 'a' * 32)
        self.assertEqual(order, ['listener_ready', 'privileges_verified'])


if __name__ == '__main__':
    unittest.main()
