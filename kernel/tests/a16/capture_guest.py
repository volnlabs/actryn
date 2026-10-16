#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""One-shot instrumentation-4 capture on the dedicated A16 guest only."""
import argparse
import fcntl
import hashlib
import json
import os
import pathlib
import re
import subprocess
import tomllib

from uart_trace import TraceFS, guard, idle_state

HERE = pathlib.Path(__file__).resolve().parent
MODULE = HERE / 'actryn_a16_capture.ko'
DEVICE = pathlib.Path('/dev/actryn-a16-capture')
STOP = 0x5541
MAX_BYTES = 128 + 4096 * 256


def write_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def verify_inputs():
    manifest = tomllib.loads((HERE / 'instrumentation4.toml').read_text())
    if manifest['revision'] != 4:
        raise ValueError('instrumentation amendment 4 required')
    for name, expected in manifest['sources'].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != expected:
            raise ValueError('instrumentation source changed: ' + name)
    if hashlib.sha256(MODULE.read_bytes()).hexdigest() != manifest['module_sha256']:
        raise ValueError('exact ARM capture module build required')
    return hashlib.sha256((HERE / 'instrumentation4.toml').read_bytes()).hexdigest()


def command(argv, output, label):
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
    except subprocess.TimeoutExpired as error:
        (output / (label + '.log')).write_bytes(error.stdout or b'')
        raise
    (output / (label + '.log')).write_bytes(result.stdout)
    (output / (label + '.exit')).write_text(str(result.returncode) + '\n')
    result.check_returncode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop'])
    parser.add_argument('output', type=pathlib.Path)
    args = parser.parse_args()
    boot = guard()
    amendment_sha = verify_inputs()
    output = args.output
    if output.parent != pathlib.Path('/var/tmp') or not re.fullmatch(r'actryn-a16-capture-[a-z0-9]+', output.name):
        raise ValueError('fixed new A16 capture directory required')
    if args.action == 'start':
        output.mkdir(mode=0o700)
        try:
            idle_state(TraceFS(pathlib.Path('/sys/kernel/tracing')))
            if DEVICE.exists() or pathlib.Path('/sys/module/actryn_a16_capture').exists():
                raise ValueError('capture module already present; no reuse/reset')
            write_json(output / 'state.json', {'boot_id': boot, 'instrumentation4_sha256': amendment_sha,
                                               'module_sha256': hashlib.sha256(MODULE.read_bytes()).hexdigest()})
            command(['insmod', str(MODULE)], output, 'insmod')
            if not DEVICE.exists():
                raise ValueError('capture device missing after module initialization')
        except BaseException as error:
            write_json(output / 'start-failure.json', {'phase': 'start', 'error': repr(error),
                         'module_present': pathlib.Path('/sys/module/actryn_a16_capture').exists()})
            raise
        return
    state = json.loads((output / 'state.json').read_text())
    if state['boot_id'] != boot or state['instrumentation4_sha256'] != amendment_sha:
        raise ValueError('boot or instrumentation changed')
    if (output / 'stop-failure.json').exists() or (output / 'result.json').exists():
        raise ValueError('capture attempt already ended; no overwrite')
    error = unload_error = None
    try:
        fd = os.open(DEVICE, os.O_RDONLY | os.O_CLOEXEC)
        try:
            fcntl.ioctl(fd, STOP)
            data = bytearray()
            while True:
                chunk = os.read(fd, min(65536, MAX_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data += chunk
                if len(data) > MAX_BYTES:
                    raise ValueError('capture exceeds fixed capacity')
        finally:
            os.close(fd)
        with (output / 'capture.bin').open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    except BaseException as caught:
        error = caught
    finally:
        try:
            command(['rmmod', 'actryn_a16_capture'], output, 'rmmod')
        except BaseException as caught:
            unload_error = caught
    if error is not None or unload_error is not None:
        write_json(output / 'stop-failure.json', {'phase': 'stop', 'error': repr(error),
                                            'unload_error': repr(unload_error)})
        raise RuntimeError('capture export or unload failed') from error
    write_json(output / 'result.json', {'boot_id': boot, 'capture_bytes': len(data),
               'capture_sha256': hashlib.sha256(data).hexdigest(), 'module_unloaded': True,
               'start_failed': (output / 'start-failure.json').exists(),
               'correlation': 'NOT_EVALUATED; host must validate complete capture and workload'})
    if (output / 'start-failure.json').exists():
        raise RuntimeError('failed start retired; attempt remains failed')


if __name__ == '__main__':
    main()
