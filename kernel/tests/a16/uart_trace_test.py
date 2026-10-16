# SPDX-License-Identifier: GPL-2.0-only
import pathlib
import tempfile
import unittest
from unittest import mock

import uart_trace


class FakeTrace:
    def __init__(self):
        self.data = {'current_tracer': 'nop\n', 'events/enable': '0\n', 'kprobe_events': '',
                     'dynamic_events': '', 'trace': '# tracer: nop\n', 'trace_clock': '[local] global boot\n',
                     'tracing_on': '1\n', 'buffer_size_kb': '1408\n', 'tracing_cpumask': '3\n',
                     'set_event_pid': '', 'set_event_notrace_pid': '', 'trace_options': 'context-info\n',
                     'kprobe_profile': 'enter 20 0\nleave 20 0\n',
                     'per_cpu/cpu0/stats': 'overrun: 0\ndropped events: 0\n',
                     'per_cpu/cpu1/stats': 'overrun: 2\ndropped events: 0\n'}
        self.writes = []
        self.fail_return_probe = False

    def read(self, name, limit=uart_trace.MAX_TEXT):
        return self.data[name]

    def write(self, name, value, append=False):
        self.writes.append((name, value, append))
        if name == 'kprobe_events':
            if value.startswith('r64:') and self.fail_return_probe:
                raise OSError('return probe rejected')
            if value.startswith('-:'):
                event = value[2:].strip()
                self.data[name] = ''.join(line + '\n' for line in self.data[name].splitlines()
                                          if line.split()[0].split(':', 1)[1] != event)
            else:
                self.data[name] += value
            self.data['dynamic_events'] = self.data[name]
        elif name == 'trace_clock':
            self.data[name] = '[' + value.strip() + ']\n'
        else:
            self.data[name] = value


class UartTraceTests(unittest.TestCase):
    def test_busy_trace_is_rejected_without_mutation(self):
        for name, value in [('events/enable', '1'), ('kprobe_events', 'foreign probe\n'),
                            ('trace', 'old measured event\n'), ('set_event_pid', '42\n')]:
            trace = FakeTrace(); trace.data[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                uart_trace.idle_state(trace)
            self.assertEqual(trace.writes, [])

    def test_partial_setup_restores_clock_buffer_and_tracing(self):
        trace = FakeTrace(); trace.fail_return_probe = True
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory)
            with self.assertRaises(OSError):
                uart_trace.start(trace, out, 'boot-1')
            self.assertTrue((out / 'failure.json').exists())
            self.assertEqual(trace.data['trace_clock'], '[local]\n')
            self.assertEqual(trace.data['buffer_size_kb'], '1408\n')
            self.assertEqual(trace.data['tracing_on'], '1\n')
            self.assertEqual(trace.data['kprobe_events'], '')

    def test_stop_retains_loss_and_miss_metadata_without_dispatch_claim(self):
        import json
        trace = FakeTrace()
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory)
            uart_trace.start(trace, out, 'boot-1')
            trace.data['trace'] = '# tracer: nop\nworker-1 [000] 1.0: enter: tty=1 count=158\n'
            trace.data['kprobe_profile'] = 'enter 20 0\nleave 20 3\n'
            uart_trace.stop(trace, out, 'boot-1')
            result = json.loads((out / 'result.json').read_text())
            self.assertEqual(result['dispatch'], 'NOT_RUN')
            self.assertEqual(result['frame_correlation'], False)
            self.assertIn('leave 20 3', (out / 'kprobe-profile.txt').read_text())
            self.assertIn('overrun: 2', (out / 'cpu1-stats.txt').read_text())
            self.assertEqual(trace.data['trace_clock'], '[local]\n')
            self.assertEqual(trace.data['buffer_size_kb'], '1408\n')
            self.assertEqual(trace.data['tracing_on'], '1\n')
            self.assertEqual(trace.data['kprobe_events'], '')

    def test_wrong_boot_cannot_restore_another_kernel(self):
        trace = FakeTrace()
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory)
            uart_trace.start(trace, out, 'boot-1')
            writes = list(trace.writes)
            with self.assertRaises(ValueError):
                uart_trace.stop(trace, out, 'boot-2')
            self.assertEqual(trace.writes, writes)

    def test_trace_export_failure_still_retains_loss_stats_and_restores(self):
        trace = FakeTrace()
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory)
            uart_trace.start(trace, out, 'boot-1')
            original_read = trace.read
            def read(name, limit=uart_trace.MAX_TEXT):
                if name == 'trace':
                    raise ValueError('text cap exceeded')
                return original_read(name, limit)
            with mock.patch.object(trace, 'read', side_effect=read), self.assertRaises(RuntimeError):
                uart_trace.stop(trace, out, 'boot-1')
            self.assertTrue((out / 'failure.json').is_file())
            self.assertTrue((out / 'kprobe-profile.txt').is_file())
            self.assertTrue((out / 'cpu1-stats.txt').is_file())
            self.assertEqual(trace.data['trace_clock'], '[local]\n')
            self.assertEqual(trace.data['kprobe_events'], '')

    def test_foreign_probe_on_stop_prevents_global_control_changes(self):
        trace = FakeTrace()
        with tempfile.TemporaryDirectory() as directory:
            out = pathlib.Path(directory)
            uart_trace.start(trace, out, 'boot-1')
            trace.data['dynamic_events'] += 'p:foreign/event another_function\n'
            writes = list(trace.writes)
            with self.assertRaises(ValueError):
                uart_trace.stop(trace, out, 'boot-1')
            self.assertEqual(trace.writes, writes)


if __name__ == '__main__':
    unittest.main()
