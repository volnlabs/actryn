#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Host checks only. A successful run is not target or release qualification."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIRS = (
    'ci', 'apps/server/tests', 'apps/robotd/tests', 'packaging/agent',
    'packaging/release', 'packaging/release/tests', 'sdk/python/tests',
    'tests/observer',
)
SUITES = {
    'rust': [
        ['cargo', 'fmt', '--all', '--check'],
        ['cargo', 'clippy', '--workspace', '--all-targets', '--locked', '--', '-D', 'warnings'],
        ['cargo', 'test', '--workspace', '--locked'],
    ],
    'python': [
        [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', path, '-p', 'test_*.py']
        for path in PYTHON_DIRS
    ] + [[sys.executable, '-B', 'ci/qualification.py']],
    'kernel-host': [
        ['make', '-C', 'kernel', 'test'],
        [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'kernel/tests', '-p', '*_test.py'],
        ['sh', 'kernel/tests/a16/run.sh'],
    ],
}


def run(commands, output):
    output.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONPATH'] = str(ROOT / 'sdk/python')
    result = {
        'scope': 'host-checks-not-release-qualification',
        'source_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'worktree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
        'checks': [], 'passed': False,
    }
    for number, command in enumerate(commands, 1):
        started = time.monotonic()
        log_name = f'{number:02}.log'
        print(f'RUN {command}', flush=True)
        with (output / log_name).open('w') as log:
            try:
                status = subprocess.run(command, cwd=ROOT, env=env, stdout=log,
                                        stderr=subprocess.STDOUT, check=False).returncode
            except OSError as error:
                log.write(str(error) + '\n')
                status = 127
        result['checks'].append({'command': command, 'returncode': status,
                                 'seconds': round(time.monotonic() - started, 3), 'log': log_name})
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(f'EXIT {status}: {output / log_name}', flush=True)
    result['passed'] = bool(commands) and all(row['returncode'] == 0 for row in result['checks'])
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite', choices=SUITES)
    parser.add_argument('--output', required=True, type=Path, help='new directory; never overwrite a run')
    args = parser.parse_args()
    raise SystemExit(run(SUITES[args.suite], args.output))
