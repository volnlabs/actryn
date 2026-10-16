#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify amendment 3, then wrap the unchanged amendment-2 userspace pilot."""
import argparse
import hashlib
import json
import pathlib
import struct
import subprocess
import sys
import tomllib

HERE = pathlib.Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_bootable(data):
    if len(data) < 40:
        raise ValueError('truncated FDT header')
    magic, total = struct.unpack('>II', data[:8])
    if magic != 0xd00dfeed or total != len(data):
        raise ValueError('FDT header/file size mismatch')
    expanded = (len(data) + 10000) * 2  # QEMU v11.1.1 load_device_tree.
    if expanded > 2 * 1024 * 1024:
        raise ValueError('QEMU-expanded FDT exceeds Linux arm64 MAX_FDT_SIZE')
    return expanded


def validate_command(original, amended, root):
    from prepare import qemu_command
    if original != qemu_command(root, 'raw', 'pilot01'):
        raise ValueError('original command differs from frozen revision 1')
    expected = list(original)
    expected[expected.index('-dtb') + 1] = str(root / 'boot/raw-compact-amendment3.dtb')
    expected[expected.index('-serial') + 1] = 'file:' + str(root / 'serial-rawboot02.log')
    if amended != expected:
        raise ValueError('only the compact DT and fresh serial log may change')


def validate_running(actual, expected):
    if actual != expected:
        raise ValueError('running A16 QEMU arguments differ from amendment 3')


def verify(root):
    amendment = tomllib.loads((HERE / 'amendment3.toml').read_text())
    if root.parts[-3:] != ('.cache', 'qemu', 'a16') or amendment['revision'] != 3:
        raise ValueError('dedicated A16 directory and amendment 3 required')
    for name, sha in amendment['files'].items():
        if digest(root / name) != sha:
            raise ValueError('amendment artifact changed: ' + name)
    am2 = tomllib.loads((HERE / 'amendment2.toml').read_text())
    if digest(HERE / 'amendment2.toml') != amendment['amendment2_sha256']:
        raise ValueError('amendment 2 changed')
    for name, sha in am2['sources'].items():
        if digest(HERE.parents[2] / name) != sha:
            raise ValueError('amendment-2 source changed: ' + name)
    if digest(root / 'manifest.toml') != am2['base_manifest_sha256']:
        raise ValueError('base manifest changed')
    prepared = json.loads((root / 'prepared.json').read_text())
    if (prepared['source_sha256'] != am2['base_source_archive_sha256']
            or digest(root / 'source.tar.gz') != am2['base_source_archive_sha256']):
        raise ValueError('base source provenance changed')
    original = json.loads((root / 'qemu-pilot01.json').read_text())
    command = json.loads((root / 'qemu-rawboot02.json').read_text())
    validate_command(original, command, root)
    expanded = require_bootable((root / 'boot/raw-compact-amendment3.dtb').read_bytes())
    left = (root / 'environment-amendment3/raw.normalized.dts').read_bytes()
    right = (root / 'environment-amendment3/compact.normalized.dts').read_bytes()
    if left != right:
        raise ValueError('normalized DTS differs')
    return {'environment_amendment': 3, 'amendment3_sha256': digest(HERE / 'amendment3.toml'),
            'qemu_loaded_totalsize_from_source': expanded, 'command': command,
            'comparison': 'NOT_RUN', 'physical_acceptance': False}


def running_snapshot(command):
    result = subprocess.run(['systemctl', '--user', 'show', '--property=MainPID', '--value',
                             'actryn-a16-robot.service'], capture_output=True, text=True,
                            check=True, timeout=5)
    pid = int(result.stdout.strip())
    if pid <= 0:
        raise ValueError('dedicated QEMU unit is not running')
    proc = pathlib.Path('/proc') / str(pid)
    actual = [arg.decode() for arg in (proc / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')]
    validate_running(actual, command)
    # Field 22, after the parenthesized comm (which may itself contain spaces).
    start_ticks = (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]
    return {'pid': pid, 'start_ticks': start_ticks, 'argv': actual}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['verify', 'pilot'])
    parser.add_argument('directory', type=pathlib.Path)
    args = parser.parse_args()
    root = args.directory.resolve()
    if args.action == 'verify':
        print(json.dumps(verify(root), indent=2))
        return
    output = root / 'qualification/environment3-userspace01'
    output.mkdir()  # One attempt, including setup failure; never overwritten.
    record = {'environment_amendment': 3, 'status': 'FAILED', 'comparison': 'NOT_RUN'}
    invoked = False
    try:
        if (root / 'qualification/userspace01').exists():
            raise ValueError('userspace01 already exists; no retry or amendment of old evidence')
        record.update(verify(root))
        record['process_before'] = running_snapshot(record['command'])
        (output / 'amendment3.toml').write_bytes((HERE / 'amendment3.toml').read_bytes())
        (output / 'environment.json').write_text(json.dumps(record, indent=2) + '\n')
        # The unchanged pilot bounds its own SSH, controller and workload calls.
        invoked = True
        subprocess.run([sys.executable, str(HERE / 'pilot.py'), 'userspace', str(root)], check=True)
        record['process_after'] = running_snapshot(record['command'])
        if record['process_before'] != record['process_after']:
            raise ValueError('QEMU process changed during pilot')
        if not (root / 'qualification/userspace01/PASS').is_file():
            raise ValueError('inner pilot did not produce PASS')
        record['status'] = 'PASS'
        (output / 'PASS').write_text('PASS amended-environment correctness pilot; not a comparison\n')
    except BaseException as error:
        record['error'] = repr(error)
        (output / 'FAILED').write_text(repr(error) + '\n')
        raise
    finally:
        (output / 'environment.json').write_text(json.dumps(record, indent=2) + '\n')
        pilot_output = root / 'qualification/userspace01'
        if invoked and pilot_output.is_dir():
            # Additional provenance only; never replace amendment-2 evidence.
            with (pilot_output / 'environment-amendment3.json').open('x') as stream:
                json.dump(record, stream, indent=2)
                stream.write('\n')


if __name__ == '__main__':
    main()
