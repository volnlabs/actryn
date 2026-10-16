import errno
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

import overhead


def trials():
    return [{'index': i, 'mode': mode, 'status': 'complete', 'opens': 30000,
             'workload_sha256': overhead.WORKLOAD_SHA256, 'profile': 'fixed-standalone-30k',
             'boot_id': 'original-boot', 'manifest': 'b' * 64,
             'attempt': format(i + 1, '032x'), 'retired': True,
             'wall_ns': 120 if mode == 'ON' else 100,
             'user_cpu_ns': 20, 'system_cpu_ns': 30,
             'loss': {'lost': 7, 'sequence': 60000, 'ready': False} if mode == 'ON' else None}
            for i, mode in enumerate(overhead.ORDER)]


class AnalysisTests(unittest.TestCase):
    def test_balanced_pairs_retain_raw_measurements_and_actual_loss(self):
        raw = trials(); result = overhead.analyze(raw)
        self.assertEqual(result['planned'], 8)
        self.assertEqual(result['complete'], 8)
        self.assertEqual(len(result['pairs']), 4)
        self.assertEqual(result['trials'], raw)
        self.assertTrue(all(pair['wall_delta_ns'] == 20 and pair['wall_relative_delta'] == .2
                            for pair in result['pairs']))
        self.assertFalse(result['superiority_inference'])

    def test_every_failed_or_missing_trial_remains_in_denominator(self):
        raw = trials()
        raw[1] = {'index': 1, 'mode': 'ON', 'status': 'failed', 'error': 'deadline',
                  'timing_prefix': {'wall_ns': 123, 'not_a_complete_trial': True}}
        raw[5] = {'index': 5, 'mode': 'OFF', 'status': 'not_run', 'reason': 'prior failure'}
        result = overhead.analyze(raw)
        self.assertEqual(result['planned'], 8)
        self.assertEqual(result['complete'], 6)
        self.assertEqual(len(result['pairs']), 4)
        self.assertIsNone(result['pairs'][0]['wall_delta_ns'])
        self.assertIsNone(result['pairs'][2]['wall_delta_ns'])
        self.assertEqual(len(result['trials']), 8)
        self.assertEqual(result['trials'][1]['timing_prefix']['wall_ns'], 123)

    def test_negative_overhead_is_retained_without_inferred_superiority(self):
        raw = trials()
        for trial in raw:
            if trial['mode'] == 'ON': trial['wall_ns'] = 80
        result = overhead.analyze(raw)
        self.assertTrue(all(pair['wall_delta_ns'] == -20 for pair in result['pairs']))
        self.assertFalse(result['superiority_inference'])

    def test_malformed_and_mismatched_cohorts_cannot_pass(self):
        for fault in ('missing', 'order', 'duplicate', 'workload', 'boot', 'manifest',
                      'zero_wall', 'negative_cpu', 'bool_wall', 'off_loss', 'hidden_loss'):
            raw = trials()
            if fault == 'missing': raw.pop()
            elif fault == 'order': raw[0]['mode'] = 'ON'
            elif fault == 'duplicate': raw[1]['attempt'] = raw[0]['attempt']
            elif fault == 'workload': raw[1]['workload_sha256'] = 'c' * 64
            elif fault == 'boot': raw[1]['boot_id'] = 'new-boot'
            elif fault == 'manifest': raw[1]['manifest'] = 'c' * 64
            elif fault == 'zero_wall': raw[1]['wall_ns'] = 0
            elif fault == 'negative_cpu': raw[1]['system_cpu_ns'] = -1
            elif fault == 'bool_wall': raw[1]['wall_ns'] = True
            elif fault == 'off_loss': raw[0]['loss'] = {'lost': 0}
            else: raw[1]['loss']['ready'] = True
            with self.subTest(fault=fault), self.assertRaises(AssertionError): overhead.analyze(raw)

    def test_all_missing_trials_do_not_turn_into_zero_overhead(self):
        raw = [{'index': i, 'mode': mode, 'status': 'not_run'} for i, mode in enumerate(overhead.ORDER)]
        result = overhead.analyze(raw)
        self.assertEqual(result['complete'], 0)
        self.assertTrue(all(v['wall_delta_ns'] is None for v in result['pairs']))
        self.assertIsNone(result['distribution']['OFF']['wall_ns'])


class ControlTests(unittest.TestCase):
    def test_absence_lookup_is_read_only_exact_observer_id_and_closes_live_fd(self):
        libc = MagicMock(); libc.syscall.return_value = 42
        with patch.object(overhead.ctypes, 'CDLL', return_value=libc), patch.object(overhead.os, 'close') as close:
            self.assertFalse(overhead.observer_program_absent(123))
        close.assert_called_once_with(42)
        args = libc.syscall.call_args.args
        self.assertEqual(args[:2], (321, 13))
        self.assertEqual(overhead.struct.unpack('III', overhead.ctypes.string_at(args[2], 12)), (123, 0, 0))

    def test_only_enoent_establishes_absence_not_permission_or_other_error(self):
        libc = MagicMock(); libc.syscall.return_value = -1
        for error in (errno.ENOENT, errno.EPERM, errno.EINVAL):
            with (patch.object(overhead.ctypes, 'CDLL', return_value=libc),
                  patch.object(overhead.ctypes, 'get_errno', return_value=error)):
                if error == errno.ENOENT: self.assertTrue(overhead.observer_program_absent(123))
                else:
                    with self.assertRaises(AssertionError): overhead.observer_program_absent(123)

    def test_surviving_observer_program_cannot_establish_off_control(self):
        run = object.__new__(overhead.Campaign)
        run.deadline, run.observer_ids, run.record = time.monotonic() + .005, {123}, Mock()
        run.service_states = Mock(return_value={unit: {'ActiveState': 'inactive', 'MainPID': '0'}
                    for unit in ('actryn-serverd', 'actryn-launcher', 'actryn-observer')})
        with patch.object(overhead, 'observer_program_absent', return_value=False):
            with self.assertRaisesRegex(AssertionError, 'deadline'): run.set_mode('OFF')
        run.record.assert_not_called()

    def test_fd_inventory_uses_only_actual_observer_program_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i in range(5): (root / str(i)).write_text('prog_id:\t' + str(i + 100) + '\n')
            (root / 'map').write_text('map_id:\t999\n')
            with patch.object(overhead, 'Path', return_value=root):
                self.assertEqual(overhead.program_ids(123), list(range(100, 105)))
                (root / 'extra').write_text('prog_id:\t666\n')
                with self.assertRaises(AssertionError): overhead.program_ids(123)

    def test_workload_keeps_the_reviewed_fixed_loop_without_parameter_escalation(self):
        original = (overhead.ROOT / 'tests/observer/guest.py').read_text()
        self.assertIn('for _ in range(30000):', original)
        self.assertIn(" with open('/dev/null','rb'): pass", original)
        self.assertIn("for _ in range(30000):\n with open('/dev/null','rb'):pass", overhead.WORKLOAD)
        self.assertIn('signal.alarm(15)', overhead.WORKLOAD)

    def test_unresolved_robot_debit_prevents_any_service_stop(self):
        run = object.__new__(overhead.Campaign)
        run.record, run.loaded_pins, run.systemctl = Mock(), Mock(), Mock()
        run.observer_pin, run.observer_ids = Mock(return_value={'pid': 123}), set()
        run.service_states = Mock(return_value={unit: {'LoadState': 'loaded', 'ActiveState': 'active', 'MainPID': '123'}
                       for unit in ('actryn-serverd', 'actryn-launcher', 'actryn-observer')})
        run.stores = Mock(return_value={'broker': {'old': 'reaped'}, 'launcher': {'old': 'reaped'}})
        run.tasks = Mock(return_value={})
        run.accounting = Mock(return_value={'broker': {'robot_debits': 1, 'open_or_unresolved_calls': 0}})
        with patch.object(overhead, 'program_ids', return_value=[1, 2, 3, 4, 5]):
            with self.assertRaisesRegex(AssertionError, 'not quiescent'): run.run()
        run.systemctl.assert_not_called()

    def test_delayed_intent_record_cannot_issue_a_command_after_cutoff(self):
        run = object.__new__(overhead.Campaign)
        run.deadline = time.monotonic() + .005
        run.record = lambda *_: time.sleep(.02)
        with patch.object(overhead.subprocess, 'run') as command:
            with self.assertRaisesRegex(AssertionError, 'deadline'): run.command(['unused'])
        command.assert_not_called()

    def test_delayed_rpc_intent_cannot_register_after_cutoff(self):
        run = object.__new__(overhead.Campaign)
        run.deadline, run.record = 100, Mock()
        stream = MagicMock()
        with (patch.object(overhead.time, 'monotonic', side_effect=[0, 2]),
              patch.object(overhead.socket, 'socket', return_value=stream)):
            with self.assertRaisesRegex(AssertionError, 'deadline'): run.exchange({}, 'register')
        stream.__enter__.return_value.connect.assert_not_called()

    def test_partial_frame_and_eof_are_bounded(self):
        reader, writer = os.pipe()
        try:
            os.write(writer, b'{')
            with self.assertRaisesRegex(AssertionError, 'deadline'):
                overhead.read_line(reader, time.monotonic() + .02)
            os.close(writer)
            with self.assertRaisesRegex(AssertionError, 'EOF'):
                overhead.read_line(reader, time.monotonic() + .1)
        finally:
            os.close(reader)
            try: os.close(writer)
            except OSError: pass

    def test_late_completed_read_cannot_be_accepted_after_deadline(self):
        reader, writer = os.pipe()
        original = os.read
        try:
            os.write(writer, b'{}\n')
            def delayed(fd, count):
                time.sleep(.02)
                return original(fd, count)
            with patch.object(overhead.os, 'read', side_effect=delayed):
                with self.assertRaisesRegex(AssertionError, 'deadline'):
                    overhead.read_line(reader, time.monotonic() + .005)
        finally:
            os.close(reader); os.close(writer)

    def test_incremental_frames_complete_without_blocking_readline(self):
        reader, writer = os.pipe()
        complete = threading.Timer(.02, os.write, args=(writer, b'}\n'))
        try:
            os.write(writer, b'{'); complete.start()
            self.assertEqual(overhead.read_line(reader, time.monotonic() + .2), {})
        finally:
            complete.join(1); os.close(reader); os.close(writer)

    def test_lossy_or_failed_helper_cannot_cause_implicit_unbounded_join(self):
        run = object.__new__(overhead.Campaign)
        run.deadline, run.record = time.monotonic() + 1, Mock()
        child = MagicMock(pid=123)
        child.communicate.side_effect = overhead.subprocess.TimeoutExpired('child', 2)
        identity = {'cgroup_id': 9, 'cgroup_path': '/actryn/' + 'a' * 32}
        with (patch.object(overhead.subprocess, 'Popen', return_value=child),
              patch.object(overhead, 'read_line', side_effect=[{'phase': 'READY', 'pid': 123}, AssertionError('deadline')]),
              patch.object(overhead.gap, 'process_identity', return_value={
                  'pid': 123, 'start_ticks': 1, 'cgroup': '0::' + identity['cgroup_path']}),
              patch.object(overhead.common, 'read_bounded', side_effect=lambda p, _: b'123\n' if p.name == 'cgroup.procs' else b'')):
            with self.assertRaisesRegex(AssertionError, 'deadline'):
                run.helper(Path('/unused'), identity, False)
        child.kill.assert_called_once()
        child.communicate.assert_called_once_with(timeout=2)
        child.__enter__.assert_not_called()


if __name__ == '__main__':
    unittest.main()
