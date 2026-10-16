# SPDX-License-Identifier: GPL-2.0-only
import json
import pathlib
import shutil
import sys
import unittest
import uuid
from unittest import mock

import capture_guest


class CaptureGuestTests(unittest.TestCase):
    def test_host_guard_prevents_any_module_command(self):
        with mock.patch.object(sys, 'argv', ['capture_guest.py', 'start', '/var/tmp/actryn-a16-capture-test']), \
                mock.patch.object(capture_guest, 'guard', side_effect=ValueError('wrong guest')), \
                mock.patch.object(capture_guest, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'wrong guest'):
                capture_guest.main()
            command.assert_not_called()

    def test_export_failure_still_attempts_unload_and_preserves_start_failure(self):
        output = pathlib.Path('/var/tmp') / ('actryn-a16-capture-' + uuid.uuid4().hex)
        output.mkdir(mode=0o700)
        try:
            (output / 'state.json').write_text(json.dumps({'boot_id': 'boot', 'instrumentation4_sha256': 'sha'}))
            (output / 'start-failure.json').write_text('original start failure\n')
            with mock.patch.object(sys, 'argv', ['capture_guest.py', 'stop', str(output)]), \
                    mock.patch.object(capture_guest, 'guard', return_value='boot'), \
                    mock.patch.object(capture_guest, 'verify_inputs', return_value='sha'), \
                    mock.patch.object(capture_guest.os, 'open', return_value=19), \
                    mock.patch.object(capture_guest.os, 'close'), \
                    mock.patch.object(capture_guest.fcntl, 'ioctl', side_effect=OSError('freeze failed')), \
                    mock.patch.object(capture_guest, 'command') as command:
                with self.assertRaises(RuntimeError):
                    capture_guest.main()
                command.assert_called_once_with(['rmmod', 'actryn_a16_capture'], output, 'rmmod')
            self.assertEqual((output / 'start-failure.json').read_text(), 'original start failure\n')
            self.assertTrue((output / 'stop-failure.json').exists())
            self.assertFalse((output / 'result.json').exists())
        finally:
            shutil.rmtree(output)


if __name__ == '__main__':
    unittest.main()
