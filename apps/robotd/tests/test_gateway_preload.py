import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gateway_closure import wait_for_trigger
from gateway_traffic import PreloadedCancel


HERE = Path(__file__).resolve().parent


def helper(extra='', timeout=.5):
    program = (f'import sys; sys.path.insert(0,{str(HERE)!r}); '
               'from gateway_closure import wait_for_trigger; '
               f'wait_for_trigger(0,1,{timeout}); ' + extra +
               'print(\'{"calls":1}\',flush=True)')
    return [sys.executable, '-u', '-c', program]


class PreloadedCancelTests(unittest.TestCase):
    def ready(self, process):
        self.assertTrue(select.select([process.stdout], [], [], 2)[0])
        self.assertEqual(os.read(process.stdout.fileno(), 64), b'READY\n')

    def test_ready_precedes_one_trigger_and_second_trigger_is_refused(self):
        with patch('gateway_traffic.write_json'), PreloadedCancel(helper()) as owned:
            process = owned.process
            self.assertIsNone(process.poll())
            self.assertEqual(owned.trigger(), {'calls': 1})
            self.assertEqual(process.returncode, 0)
            with self.assertRaises(AssertionError):
                owned.trigger()

    def test_eof_aborts_without_call_and_context_reaps_owned_process(self):
        with tempfile.TemporaryDirectory() as directory, patch('gateway_traffic.write_json'):
            marker = Path(directory) / 'called'
            with PreloadedCancel(helper(f'open({str(marker)!r},"w").write("called"); ')) as owned:
                process = owned.process
            self.assertIsNotNone(process.poll())
            self.assertFalse(marker.exists())

    def test_helper_wait_has_absolute_timeout_without_cancel(self):
        with subprocess.Popen(helper(timeout=.1), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0) as process:
            self.ready(process)
            self.assertNotEqual(process.wait(timeout=2), 0)
            stdout, stderr = process.communicate(timeout=1)
            self.assertNotIn(b'calls', stdout)
            self.assertIn(b'TimeoutError', stderr)

    def test_malformed_or_multiple_trigger_aborts_without_probe(self):
        for data in (b'wrong\n', b'run\nrun\n', b'ru\n'):
            with self.subTest(data=data), subprocess.Popen(helper(), stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0) as process:
                self.ready(process)
                stdout, _ = process.communicate(data, timeout=2)
                self.assertNotEqual(process.returncode, 0)
                self.assertNotIn(b'calls', stdout)

    def test_unknown_trigger_timeout_is_not_resent_and_only_owned_child_is_killed(self):
        records = []
        with tempfile.TemporaryDirectory() as directory, patch('gateway_traffic.write_json',
                side_effect=lambda name, value: records.append((name, value))), \
                patch('gateway_traffic.HELPER_REPLY_TIMEOUT', .1):
            marker = Path(directory) / 'called'
            with PreloadedCancel(helper(f'open({str(marker)!r},"w").write("once"); '
                                        'import time; time.sleep(30); ')) as owned:
                process = owned.process
                with self.assertRaises(subprocess.TimeoutExpired):
                    owned.trigger()
                self.assertIsNotNone(process.poll())
                with self.assertRaises(AssertionError):
                    owned.trigger()
            self.assertEqual(marker.read_text(), 'once')
            self.assertTrue(any(value.get('trigger_outcome_unknown') for _, value in records))
            self.assertEqual(sum(name == 'saturation-helper-trigger.json' for name, _ in records), 1)

    def test_bad_readiness_closes_owned_child_without_trigger(self):
        children = []
        original = subprocess.Popen
        def start(*args, **kwargs):
            child = original(*args, **kwargs); children.append(child); return child
        with patch('gateway_traffic.write_json'), patch('gateway_traffic.subprocess.Popen', side_effect=start):
            with self.assertRaises(AssertionError):
                with PreloadedCancel([sys.executable, '-u', '-c',
                                      'import sys; print("WRONG",flush=True); sys.stdin.read()']):
                    self.fail('invalid readiness admitted')
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_readiness_timeout_aborts_and_reaps_only_owned_child(self):
        children = []
        original = subprocess.Popen
        def start(*args, **kwargs):
            child = original(*args, **kwargs); children.append(child); return child
        with patch('gateway_traffic.write_json'), \
                patch('gateway_traffic.subprocess.Popen', side_effect=start), \
                patch('gateway_traffic.select.select', return_value=([], [], [])):
            with self.assertRaisesRegex(AssertionError, 'readiness timeout'):
                with PreloadedCancel([sys.executable, '-u', '-c',
                                      'import sys; sys.stdin.read()']):
                    self.fail('missing readiness admitted')
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].returncode, 0)

    def test_malformed_reply_records_unknown_without_resend(self):
        records = []
        with patch('gateway_traffic.write_json', side_effect=lambda name, value: records.append((name, value))):
            with PreloadedCancel(helper('print("not-json",flush=True); ')) as owned:
                with self.assertRaises(ValueError):
                    owned.trigger()
                with self.assertRaises(AssertionError):
                    owned.trigger()
        self.assertTrue(any(value.get('trigger_outcome_unknown') for _, value in records))
        self.assertEqual(sum(name == 'saturation-helper-trigger.json' for name, _ in records), 1)

    def test_wait_cannot_exceed_ten_seconds(self):
        with self.assertRaises(ValueError):
            wait_for_trigger(-1, -1, 10.01)


if __name__ == '__main__':
    unittest.main()
