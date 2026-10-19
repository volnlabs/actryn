# SPDX-License-Identifier: Apache-2.0
"""Validate shipped commands without executing any installation example."""
import ast
import contextlib
import io
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import release
import install


class InstallDocumentationTests(unittest.TestCase):
    def test_every_shell_fence_and_embedded_python_parses_without_execution(self):
        text = (ROOT / 'README.md').read_text()
        shells = re.findall(r'^```sh\n(.*?)^```$', text, re.M | re.S)
        self.assertGreaterEqual(len(shells), 7)
        embedded = []
        for script in shells:
            result = subprocess.run(['/usr/bin/bash', '-n'], input=script,
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            embedded.extend(re.findall(r"<<'([A-Z_]+)'\n(.*?)^\1$", script, re.M | re.S))
        self.assertEqual({name for name, _ in embedded}, {
            'CONFIG_PY', 'LAYOUT_PY', 'WAIT_PY', 'UNIT_WAIT_PY',
            'PEER_CONFIG_PY', 'ROBOT_CONFIG_PY',
        })
        for name, source in embedded:
            ast.parse(source, filename=name)

    def test_documented_resume_flags_reach_only_the_installer_test_double(self):
        # Real argument parsing, with the complete host-mutating boundary replaced.
        arguments = ['release.py', 'resume', '--role', 'server', '--bundle', '/candidate',
                     '--public-key', '/public.pem', '--key-sha256', 'a' * 64]
        with patch.object(sys, 'argv', arguments), patch.object(install, 'Installer') as installer, \
                patch.object(install, 'SystemPlatform') as platform, contextlib.redirect_stdout(io.StringIO()):
            installer.return_value.run.return_value = {'authority_issued': False}
            release.main()
        installer.assert_called_once_with(Path('/'), platform.return_value, 'server')
        installer.return_value.run.assert_called_once_with(
            'resume', Path('/candidate'), Path('/public.pem'), 'a' * 64)


if __name__ == '__main__':
    unittest.main()
