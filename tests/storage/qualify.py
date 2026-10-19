#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded host-only SQLite sync regression; fake authority, no guest access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

REPO = Path(__file__).resolve().parents[2]
TEST = 'tests::actual_sqlite_sync_fault_preserves_urgent_closure_and_restart_fences'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = {'status': 'FAIL', 'host_only': True, 'real_kernel_authority': False,
              'physical_acceptance': False, 'release_qualification': False,
              'automatic_retries': False, 'cases': []}

    def run(label, command, env=None, timeout=120):
        (output / (label + '.command.json')).write_text(json.dumps(command) + '\n')
        with (output / (label + '.stdout')).open('wb') as stdout, \
                (output / (label + '.stderr')).open('wb') as stderr:
            process = subprocess.run(command, cwd=REPO, env=env, stdout=stdout,
                                     stderr=stderr, timeout=timeout, check=False)
        if process.returncode:
            raise RuntimeError(f'{label} failed with exit {process.returncode}; logs preserved')

    try:
        if os.environ.get('LD_PRELOAD'):
            raise RuntimeError('inherited LD_PRELOAD must be absent')
        run('compile-interceptor', ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                   '-shared', '-fPIC', '-O2', str(REPO / 'tests/storage/sync_fault.c'),
                                   '-o', str(output / 'sync_fault.so'), '-ldl'])
        run('build-test', ['cargo', 'test', '--locked', '--offline', '-p', 'robot-intent',
                           '--lib', '--no-run', '--message-format=json'])
        executables = [json.loads(line)['executable'] for line in
                       (output / 'build-test.stdout').read_text().splitlines()
                       if line.startswith('{') and json.loads(line).get('executable')]
        if len(executables) != 1:
            raise RuntimeError('expected exactly one robot-intent test executable')
        result['test_executable_sha256'] = hashlib.sha256(Path(executables[0]).read_bytes()).hexdigest()
        result['interceptor_sha256'] = hashlib.sha256((output / 'sync_fault.so').read_bytes()).hexdigest()
        for mode in ('stall', 'eio'):
            root = output / mode
            root.mkdir(mode=0o700)
            env = dict(os.environ, LD_PRELOAD=str(output / 'sync_fault.so'),
                       ACTRYN_SYNC_ROOT=str(root), ACTRYN_SYNC_MODE=mode)
            started = time.monotonic()
            run(mode, [executables[0], TEST, '--exact', '--ignored', '--nocapture',
                       '--test-threads=1'], env=env, timeout=20)
            entered = (root / 'sync-entered').read_text().splitlines()
            if entered[0] not in ('fsync', 'fdatasync') or entered[1] not in (
                    str(root / 'intent.sqlite'), str(root / 'intent.sqlite-journal')):
                raise RuntimeError('intercepted sync identity mismatch')
            returned = (root / 'sync-returned').read_text()
            if returned != ('-1 EIO\n' if mode == 'eio' else '0\n'):
                raise RuntimeError('sync result mismatch')
            if not (root / 'closure-before-release').is_file():
                raise RuntimeError('missing pre-release closure receipt')
            result['cases'].append({'mode': mode, 'status': 'PASS', 'sync': entered,
                                    'returned': returned.strip(),
                                    'elapsed_s': time.monotonic() - started})
        result['status'] = 'PASS_HOST_SQLITE_SYNC_BOUNDARY'
    except Exception as error:
        result['error'] = str(error)
        raise
    finally:
        sources = ['crates/robot-intent/src/lib.rs', 'crates/robot-intent/src/store.rs',
                   'crates/robot-intent/src/writer.rs', 'crates/robot-intent/src/tests.rs',
                   'tests/storage/sync_fault.c', 'tests/storage/qualify.py', 'Cargo.lock']
        result['source_sha256'] = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
                                   for name in sources}
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))


if __name__ == '__main__':
    main()
