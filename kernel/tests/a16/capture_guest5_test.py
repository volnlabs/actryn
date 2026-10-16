# SPDX-License-Identifier: GPL-2.0-only
import json
import pathlib
import shutil
import sys
import unittest
import uuid
from unittest import mock

import capture_guest
import capture_guest5
from uart_trace_test import FakeTrace


class PassiveGuardTests(unittest.TestCase):
    def test_exact_lazy_default_is_preserved_without_control_writes(self):
        trace = FakeTrace()
        trace.data['buffer_size_kb'] = '7 (expanded: 1408)\n'
        trace.data['trace_clock'] = '[local] global counter uptime perf mono mono_raw boot tai\n'
        original = dict(trace.data)
        state = capture_guest5.passive_idle_state(trace)
        self.assertEqual(state['buffer_size_kb'], original['buffer_size_kb'])
        self.assertEqual(state['trace_clock'], original['trace_clock'])
        self.assertEqual(trace.data, original)
        self.assertEqual(trace.writes, [])

    def test_foreign_controls_or_events_still_reject_without_writes(self):
        for name, value in [('current_tracer', 'function'), ('events/enable', '1'),
                ('kprobe_events', 'p:foreign/event fn'), ('dynamic_events', 'f:other fn'),
                ('set_event_pid', '123'), ('set_event_notrace_pid', '456'), ('trace', 'retained event')]:
            trace = FakeTrace(); trace.data[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                capture_guest5.passive_idle_state(trace)
            self.assertEqual(trace.writes, [])

    def test_metadata_precedes_load_and_frozen_lifecycle_is_restored(self):
        self.start(False)

    def test_busy_trace_blocks_load_and_retains_start_failure(self):
        self.start(True)

    def start(self, busy):
        output = pathlib.Path('/var/tmp') / ('actryn-a16-capture-' + uuid.uuid4().hex)
        trace = FakeTrace(); trace.data['buffer_size_kb'] = '7 (expanded: 1408)\n'
        if busy:
            trace.data['dynamic_events'] = 'foreign'
        original = capture_guest.idle_state
        def command(argv, directory, label):
            self.assertEqual(argv[0], 'insmod')
            metadata = json.loads((directory / 'instrumentation5.json').read_text())
            self.assertEqual(metadata['instrumentation5_sha256'], 'five')
            self.assertTrue((directory / 'state.json').exists())
            (directory / 'fake-device').touch()
        try:
            with mock.patch.object(sys, 'argv', ['capture_guest5.py', 'start', str(output)]), \
                    mock.patch.object(capture_guest5, 'verify_inputs', return_value='five'), \
                    mock.patch.object(capture_guest, 'guard', return_value='boot'), \
                    mock.patch.object(capture_guest, 'verify_inputs', return_value='four'), \
                    mock.patch.object(capture_guest, 'TraceFS', return_value=trace), \
                    mock.patch.object(capture_guest, 'MODULE', pathlib.Path(__file__)), \
                    mock.patch.object(capture_guest, 'DEVICE', output / 'fake-device'), \
                    mock.patch.object(capture_guest, 'command', side_effect=command) as commands:
                if busy:
                    with self.assertRaises(ValueError):
                        capture_guest5.main()
                    commands.assert_not_called()
                    self.assertTrue((output / 'start-failure.json').exists())
                    self.assertFalse((output / 'state.json').exists())
                else:
                    capture_guest5.main()
                    self.assertEqual(commands.call_count, 1)
            self.assertIs(capture_guest.idle_state, original)
            self.assertEqual(trace.writes, [])
        finally:
            if output.exists():
                shutil.rmtree(output)

    def test_changed_amendment_blocks_stop_before_frozen_lifecycle(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory)
            (output / 'instrumentation5.json').write_text(json.dumps({'instrumentation5_sha256': 'old'}))
            with mock.patch.object(sys, 'argv', ['capture_guest5.py', 'stop', str(output)]), \
                    mock.patch.object(capture_guest5, 'verify_inputs', return_value='five'), \
                    mock.patch.object(capture_guest, 'main') as main:
                with self.assertRaises(ValueError):
                    capture_guest5.main()
                main.assert_not_called()


if __name__ == '__main__':
    unittest.main()
