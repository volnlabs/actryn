# SPDX-License-Identifier: GPL-2.0-only
import copy
import pathlib
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

import campaign6
import campaign


def elf(note):
    names = b'\0.shstrtab\0.note.gnu.build-id\0'
    header = bytearray(64)
    header[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HH', header, 16, 1, 183)
    struct.pack_into('<Q', header, 40, 64)
    struct.pack_into('<HHH', header, 58, 64, 3, 1)
    sections = bytearray(192)
    struct.pack_into('<IIQQQQIIQQ', sections, 64, 1, 3, 0, 0, 256, len(names), 0, 0, 1, 0)
    struct.pack_into('<IIQQQQIIQQ', sections, 128, 11, 7, 0, 0, 256 + len(names), len(note), 0, 0, 4, 0)
    return bytes(header + sections + names + note)


class AmendmentTests(unittest.TestCase):
    def test_exact_note_and_malformed_elf(self):
        note = struct.pack('<III', 4, 20, 3) + b'GNU\0' + bytes(range(20))
        self.assertEqual(campaign6.build_note(elf(note)), note)
        for data in (b'', elf(note)[:-1], elf(note).replace(b'GNU\0', b'BAD\0'),
                     elf(note + note), elf(note)[:18] + b'\x3e\0' + elf(note)[20:]):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                campaign6.build_note(data)

    def test_only_selected_module_and_wrapper_inputs_may_change(self):
        base, amended = campaign6.read_manifests()
        campaign6.only_module_change(base, amended)
        for section, key, value in (('guest_binaries', 'a16-gateway', 'changed'),
                                    ('guest_binaries', 'a16-workload', 'changed'),
                                    ('sources', 'instrumentation4.toml', 'changed')):
            bad = copy.deepcopy(amended); bad[section][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                campaign6.only_module_change(base, bad)
        for key, value in [('arms', ['userspace'] * 4), ('runs_per_boot', 3), ('automatic_retries', True)]:
            bad = copy.deepcopy(amended); bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                campaign6.only_module_change(base, bad)

    def test_owner_evidence_requires_real_equal_pid_and_live_sibling(self):
        leader = ('leader before exit tgid=41 retained_fd=4\n'
                  'leader exited; surviving tgid=41 tid=42\n'
                  'retained HEALTH result=-1 errno=1 tgid=41 tid=42\n'
                  'retained ACTIVATE result=-1 errno=1\n'
                  'PASS authority owner lifetime leader-exit\n')
        reuse = ('original owner tgid=51 retained_fd=4\n'
                 'replacement owner tgid=51 equals reaped original\n'
                 'retained HEALTH result=-1 errno=1 tgid=51 tid=51\n'
                 'retained ACTIVATE result=-1 errno=1\n'
                 'PASS authority owner lifetime pid-reuse\n')
        campaign6.qualify_owner(leader, reuse)
        for left, right in ((leader.replace('tid=42', 'tid=41'), reuse),
                            (leader, reuse.replace('replacement owner tgid=51', 'replacement owner tgid=52')),
                            (leader, reuse.replace('errno=1', 'errno=22')),
                            (leader, reuse.replace('PASS', 'NOT_RUN'))):
            with self.assertRaises(ValueError):
                campaign6.qualify_owner(left, right)

    def test_loaded_note_check_rejects_wrong_or_missing_object(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory); module = root / 'module'; note = root / 'note'
            module.write_bytes(b'object'); note.write_bytes(b'expected')
            command = campaign6.loaded_command(campaign6.sha(module), b'expected', str(module), str(note))
            self.assertEqual(subprocess.run(['sh', '-c', command], capture_output=True).returncode, 0)
            note.write_bytes(b'previous-module')
            self.assertNotEqual(subprocess.run(['sh', '-c', command], capture_output=True).returncode, 0)
            note.write_bytes(b'expected'); module.write_bytes(b'other object')
            self.assertNotEqual(subprocess.run(['sh', '-c', command], capture_output=True).returncode, 0)
            note.unlink()
            self.assertNotEqual(subprocess.run(['sh', '-c', command], capture_output=True).returncode, 0)

    def test_missing_actual_evidence_blocks_execution_and_preserves_attempt(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(campaign6, 'verify', side_effect=ValueError('missing actual evidence')), \
                mock.patch.object(campaign6.importlib, 'import_module') as load:
            root = pathlib.Path(directory) / '.cache/qemu/a16'; root.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'missing actual evidence'):
                campaign6.execute(root, 'tracekernel01', 'kernel', 0)
            load.assert_not_called()
            output = root / 'amendment6/attempts/tracekernel01'
            self.assertTrue((output / 'FAILED').exists())
            self.assertTrue((output / 'started.json').exists())
            self.assertFalse((output / 'PASS').exists())
            with self.assertRaises(FileExistsError):
                campaign6.execute(root, 'tracekernel01', 'kernel', 0)

    def test_hash_inventory_rejects_missing_changed_or_escaping_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory); log = root / 'case.log'
            log.write_text('PASS'); pins = {'case.log': campaign6.sha(log)}
            campaign6.verify_hashes(root, pins)
            log.write_text('FAIL')
            with self.assertRaises(ValueError):
                campaign6.verify_hashes(root, pins)
            log.unlink()
            with self.assertRaises(FileNotFoundError):
                campaign6.verify_hashes(root, pins)
            for name in ('../case.log', '/case.log'):
                with self.assertRaises(ValueError):
                    campaign6.verify_hashes(root, {name: 'sha'})

    def test_remote_note_check_runs_after_insmod_and_blocks_on_mismatch(self):
        calls = []
        class Remote:
            def __init__(self, root):
                self.argv = []
            def run(self, command, output, name, **kwargs):
                calls.append(name)
                if name == 'module16-loaded.log':
                    raise RuntimeError('wrong loaded note')
                return 'original-result'
        wrapped = campaign6.remote_with_note(Remote, 'sha', b'note', 'manifest')
        remote = wrapped(pathlib.Path('/unused'))
        self.assertEqual(remote.run('raw', None, 'raw-preflight.log'), 'original-result')
        self.assertEqual(calls, ['raw-preflight.log'])
        with self.assertRaisesRegex(RuntimeError, 'wrong loaded note'):
            remote.run('insmod', None, 'authority-load.log')
        self.assertEqual(calls, ['raw-preflight.log', 'authority-load.log', 'module16-loaded.log'])

    def test_staging_never_replaces_a_previous_input_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            amended = campaign6.read_manifests()[1]
            stage = campaign6.stage(root, amended)
            self.assertEqual((stage / 'campaign.py').read_bytes(), (campaign6.HERE / 'campaign.py').read_bytes())
            self.assertEqual((stage / 'campaign.toml').read_bytes(), (campaign6.HERE / 'amendment6.toml').read_bytes())
            campaign6.verify_stage(root, amended)
            with mock.patch.object(campaign, 'HERE', stage):
                self.assertEqual(campaign.verify_campaign_inputs(), amended)
            with self.assertRaises(FileExistsError):
                campaign6.stage(root, amended)
            (stage / 'campaign.py').write_text('changed')
            with self.assertRaises(ValueError):
                campaign6.verify_stage(root, amended)


if __name__ == '__main__':
    unittest.main()
