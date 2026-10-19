# SPDX-License-Identifier: GPL-2.0-only
import pathlib
import subprocess
import tempfile
import unittest
import hashlib

import passcred10

HERE = pathlib.Path(__file__).resolve().parent


class Passcred10Tests(unittest.TestCase):
    def test_derivative_requires_the_exact_frozen_gateway(self):
        source = (HERE / 'gateway.c').read_text()
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), passcred10.BASE_SHA256)
        self.assertEqual(passcred10.render(source), passcred10.render(source))
        for changed in (source + '\n', source.replace('CLIENTS 8', 'CLIENTS 7')):
            with self.assertRaises(ValueError):
                passcred10.render(changed)

    def test_queued_bind_keeps_sender_credentials(self):
        with tempfile.TemporaryDirectory(prefix='actryn-passcred10-') as directory:
            root = pathlib.Path(directory)
            (root / 'passcred10-gateway.c').write_text(passcred10.render((HERE / 'gateway.c').read_text()))
            binary = root / 'race'
            command = ['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                       '-I', str(root), '-I', str(HERE), str(HERE / 'passcred10_test.c'),
                       str(HERE / 'engine.c'), str(HERE.parent.parent / 'actryn_wire.c'), '-o', str(binary)]
            built = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('all four BIND roles', result.stdout)


if __name__ == '__main__':
    unittest.main()
