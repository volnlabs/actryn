# SPDX-License-Identifier: GPL-2.0-only
import json
import pathlib
import shutil
import sys
import tempfile
import types
import unittest
import uuid
from unittest import mock
import amendment7
import capture_guest7
from uart_trace_test import FakeTrace


def derived_lifecycle():
    module = types.ModuleType('capture7_base')
    module.__file__ = str(amendment7.HERE / 'capture_guest.py')
    exec(compile(amendment7.transform('capture_guest.py', pathlib.Path(module.__file__).read_bytes()),
                 module.__file__, 'exec'), module.__dict__)
    return module


class Capture7Tests(unittest.TestCase):
    def frozen_inputs(self, target):
        def document(path, values, sections):
            lines = [key + ' = ' + json.dumps(value) for key, value in values.items()]
            for section, entries in sections.items():
                lines += ['', '[' + section + ']']
                lines += [json.dumps(key) + ' = ' + json.dumps(value) for key, value in entries.items()]
            path.write_text('\n'.join(lines) + '\n')
        capture = {name: capture_guest7.sha(target / name) for name in capture_guest7.CAPTURE_SOURCES}
        document(target / 'instrumentation7.toml', {'revision': 7, 'max_prefix_bytes': 159,
            'record_capacity': 4096, 'record_bytes': 256, 'header_bytes': 128,
            'kretprobe_maxactive': 64, 'module_sha256': '2' * 64}, {'sources': capture})
        document(target / 'amendment7.toml', {'revision': 7,
            'instrumentation7_sha256': capture_guest7.sha(target / 'instrumentation7.toml'),
            'workload_sha256': '1' * 64}, {'sources': capture, 'workload_sources':
            {name: capture_guest7.sha(target / name) for name in capture_guest7.WORKLOAD_SOURCES}})
        return {'sources': {name: capture_guest7.sha(target / name) for name in capture_guest7.EXECUTION_SOURCES},
                'guest_binaries': {'kernel/actryn_authority.ko': 'a49fd1a48bbdc39447a78fc0b0714e2e713c34f4fe25c11e989a790778291112',
                    'a16-gateway': '305f5e1d15df9d2037b7ecc8246825a791a18d92c5f1408fed8de5b1062c9720', 'a16-workload': '1' * 64}}

    def start(self, busy):
        base = derived_lifecycle()
        output = pathlib.Path('/var/tmp') / ('actryn-a16-capture-' + uuid.uuid4().hex)
        trace = FakeTrace(); trace.data['buffer_size_kb'] = '7 (expanded: 1408)\n'
        if busy:
            trace.data['dynamic_events'] = 'foreign'
        original = base.idle_state
        def command(argv, directory, label):
            self.assertEqual((argv[0], label), ('insmod', 'insmod'))
            metadata = json.loads((directory / 'amendment7.json').read_text())
            state = json.loads((directory / 'state.json').read_text())
            self.assertEqual(metadata['amendment7_sha256'], 'amend7')
            self.assertEqual(metadata['instrumentation7_sha256'], 'inst7')
            self.assertEqual(state['instrumentation7_sha256'], 'inst7')
            self.assertNotIn('instrumentation4_sha256', state)
            (directory / 'fake-device').touch()
        try:
            with mock.patch.object(sys, 'argv', ['capture_guest7.py', 'start', str(output)]), \
                    mock.patch.object(capture_guest7, 'capture_guest', base), \
                    mock.patch.object(capture_guest7, 'verify_inputs', return_value='amend7'), \
                    mock.patch.object(capture_guest7, 'sha', return_value='inst7'), \
                    mock.patch.object(base, 'guard', return_value='boot'), \
                    mock.patch.object(base, 'verify_inputs', return_value='inst7'), \
                    mock.patch.object(base, 'TraceFS', return_value=trace), \
                    mock.patch.object(base, 'MODULE', pathlib.Path(__file__)), \
                    mock.patch.object(base, 'DEVICE', output / 'fake-device'), \
                    mock.patch.object(base, 'command', side_effect=command) as commands:
                if busy:
                    with self.assertRaises(ValueError):
                        capture_guest7.main()
                    commands.assert_not_called()
                    self.assertTrue((output / 'start-failure.json').exists())
                    self.assertFalse((output / 'state.json').exists())
                else:
                    capture_guest7.main(); self.assertEqual(commands.call_count, 1)
            self.assertIs(base.idle_state, original)
            self.assertEqual(trace.writes, [])
        finally:
            if output.exists():
                shutil.rmtree(output)

    def test_metadata_and_passive_guard_precede_mocked_load(self):
        self.start(False)

    def test_foreign_trace_rejects_before_mocked_load_and_retains_failure(self):
        self.start(True)

    def test_changed_amendment_blocks_stop_before_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory)
            (output / 'amendment7.json').write_text(json.dumps({'amendment7_sha256': 'old'}))
            with mock.patch.object(sys, 'argv', ['capture_guest7.py', 'stop', str(output)]), \
                    mock.patch.object(capture_guest7, 'verify_inputs', return_value='amend7'), \
                    mock.patch.object(capture_guest7, 'sha', return_value='inst7'), \
                    mock.patch.object(capture_guest7.capture_guest, 'main') as main:
                with self.assertRaises(ValueError):
                    capture_guest7.main()
                main.assert_not_called()

    def test_unfrozen_package_fails_before_module_action(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(capture_guest7, 'HERE', pathlib.Path(directory)):
            with self.assertRaises(FileNotFoundError):
                capture_guest7.verify_inputs()

    def test_complete_new_hashes_required_independently_of_original_baseline(self):
        import copy
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / 'source7'; amendment7.derive(output)
            target = output / 'kernel/tests/a16'; manifest = self.frozen_inputs(target)
            with mock.patch.object(capture_guest7, 'HERE', target):
                capture_guest7.verify_campaign(manifest, target)
                for name in ('first_sample7.h', 'first_sample7.py', 'workload.c', 'dispatch.py', 'capture_guest7.py'):
                    missing = copy.deepcopy(manifest); missing['sources'].pop(name)
                    wrong = copy.deepcopy(manifest); wrong['sources'][name] = '0' * 64
                    for bad in (missing, wrong):
                        with self.subTest(name=name), self.assertRaises(ValueError):
                            capture_guest7.verify_campaign(bad, target)
                for name in ('kernel/actryn_authority.ko', 'a16-gateway', 'a16-workload'):
                    bad = copy.deepcopy(manifest); bad['guest_binaries'][name] = '3' * 64
                    with self.subTest(binary=name), self.assertRaises(ValueError):
                        capture_guest7.verify_campaign(bad, target)
                (target / 'capture/prefix.h').write_text('wrong derived source')
                with self.assertRaises(ValueError):
                    capture_guest7.verify_campaign(manifest, target)


if __name__ == '__main__':
    unittest.main()
