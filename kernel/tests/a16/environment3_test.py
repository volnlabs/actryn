# SPDX-License-Identifier: GPL-2.0-only
import pathlib
import struct
import sys
import tempfile
import unittest
from unittest import mock

import environment3
from prepare import qemu_command


class EnvironmentAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path('/test/.cache/qemu/a16')
        self.original = qemu_command(self.root, 'raw', 'pilot01')
        self.correct = list(self.original)
        self.correct[self.correct.index('-dtb') + 1] = str(
            self.root / 'boot/raw-compact-amendment3.dtb')
        self.correct[self.correct.index('-serial') + 1] = 'file:' + str(
            self.root / 'serial-rawboot02.log')

    def test_only_dt_and_log_may_change(self):
        environment3.validate_command(self.original, self.correct, self.root)
        for option, value in [('-m', '4096'), ('-smp', '4'), ('-cpu', 'max'),
                              ('-append', 'root=/dev/vda1 rw')]:
            bad = list(self.correct)
            bad[bad.index(option) + 1] = value
            with self.subTest(option=option), self.assertRaises(ValueError):
                environment3.validate_command(self.original, bad, self.root)

    def test_original_blob_or_reused_log_rejected(self):
        for option in ('-dtb', '-serial'):
            bad = list(self.correct)
            index = bad.index(option) + 1
            bad[index] = self.original[index]
            with self.subTest(option=option), self.assertRaises(ValueError):
                environment3.validate_command(self.original, bad, self.root)

    def test_qemu_expansion_checked_not_just_input_header(self):
        data = struct.pack('>II', 0xd00dfeed, 1048576) + bytes(1048576 - 8)
        with self.assertRaises(ValueError):
            environment3.require_bootable(data)
        compact = struct.pack('>II', 0xd00dfeed, 8268) + bytes(8268 - 8)
        self.assertEqual(environment3.require_bootable(compact), 36536)
        with self.assertRaises(ValueError):
            environment3.require_bootable(compact + b'\0')

    def test_live_process_must_match_every_frozen_argument(self):
        environment3.validate_running(self.correct, self.correct)
        for actual in (self.original, ['qemu-system-aarch64'], self.correct + ['-S']):
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                environment3.validate_running(actual, self.correct)

    def test_existing_pilot_evidence_is_not_annotated_or_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / '.cache/qemu/a16'
            old = root / 'qualification/userspace01'
            old.mkdir(parents=True)
            (old / 'FAILED').write_text('original failure\n')
            with mock.patch.object(sys, 'argv', ['environment3.py', 'pilot', str(root)]), \
                    mock.patch.object(environment3, 'verify') as verify, \
                    mock.patch.object(environment3.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    environment3.main()
                verify.assert_not_called()
                run.assert_not_called()
            self.assertEqual([p.name for p in old.iterdir()], ['FAILED'])
            self.assertEqual((old / 'FAILED').read_text(), 'original failure\n')

    def test_wrong_live_environment_prevents_pilot_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / '.cache/qemu/a16'
            (root / 'qualification').mkdir(parents=True)
            with mock.patch.object(sys, 'argv', ['environment3.py', 'pilot', str(root)]), \
                    mock.patch.object(environment3, 'verify', return_value={'command': self.correct}), \
                    mock.patch.object(environment3, 'running_snapshot', side_effect=ValueError('wrong VM')), \
                    mock.patch.object(environment3.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'wrong VM'):
                    environment3.main()
                run.assert_not_called()
            self.assertTrue((root / 'qualification/environment3-userspace01/FAILED').is_file())
            self.assertFalse((root / 'qualification/userspace01').exists())


if __name__ == '__main__':
    unittest.main()
