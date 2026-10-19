# SPDX-License-Identifier: Apache-2.0
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import check


class CheckTests(unittest.TestCase):
    def test_failure_is_retained_and_later_check_still_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / 'results'
            status = check.run([
                [sys.executable, '-c', "print('failed assertion'); raise SystemExit(7)"],
                [sys.executable, '-c', "print('later check')"],
            ], output)
            self.assertEqual(status, 1)
            result = json.loads((output / 'result.json').read_text())
            self.assertEqual([row['returncode'] for row in result['checks']], [7, 0])
            self.assertIn('failed assertion', (output / '01.log').read_text())
            self.assertIn('later check', (output / '02.log').read_text())
            with self.assertRaises(FileExistsError):
                check.run([], output)

    def test_missing_command_is_failure_not_pass_or_abandoned_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory) / 'results'
            self.assertEqual(check.run([['/actryn/nonexistent-command']], output), 1)
            result = json.loads((output / 'result.json').read_text())
            self.assertFalse(result['passed'])
            self.assertEqual(result['checks'][0]['returncode'], 127)


if __name__ == '__main__':
    unittest.main()
