#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Common UART diagnostic only; no immutable-frame dispatch measurement."""
import argparse
import hashlib
import json
import os
import pathlib
import platform
import re
import time

MAX_TEXT = 16 * 1024 * 1024
GROUP = 'actryn_a16_uart'
PROBES = [f'p:{GROUP}/enter uart_write tty=$arg1:x64 buffer=$arg2:x64 count=$arg3:u64',
          f'r64:{GROUP}/leave uart_write result=$retval:s64']
CONFIG_SHA256 = '0f442d89365ea22dc5169463634ee62903925200844558479666cbe3eeb7e555'


class TraceFS:
    def __init__(self, path):
        self.path = path

    def read(self, name, limit=MAX_TEXT):
        with (self.path / name).open() as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('trace text exceeds fixed cap: ' + name)
        return data

    def write(self, name, value, append=False):
        with (self.path / name).open('a' if append else 'w') as stream:
            stream.write(value)


def save(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def idle_state(trace):
    if trace.read('current_tracer').strip() != 'nop' or trace.read('events/enable').strip() != '0':
        raise ValueError('exclusive idle tracefs required')
    for name in ('kprobe_events', 'dynamic_events', 'set_event_pid', 'set_event_notrace_pid'):
        if trace.read(name).strip():
            raise ValueError('foreign trace control: ' + name)
    if any(line.strip() and not line.startswith('#') for line in trace.read('trace').splitlines()):
        raise ValueError('existing trace data must be retained by its owner first')
    clock = trace.read('trace_clock')
    selected = re.findall(r'\[([^]]+)\]', clock)
    buffer = trace.read('buffer_size_kb').strip()
    tracing = trace.read('tracing_on').strip()
    if len(selected) != 1 or 'boot' not in clock.replace('[', '').replace(']', '').split():
        raise ValueError('current and boot trace clocks required')
    if not buffer.isdecimal() or tracing not in ('0', '1'):
        raise ValueError('uniform buffer and known tracing state required')
    if int(trace.read('tracing_cpumask').strip(), 16) != 3:
        raise ValueError('both fixed A16 CPUs must be included')
    options = trace.read('trace_options')
    if 'context-info' not in options.split():
        raise ValueError('task and CPU trace context required')
    return {'clock': selected[0], 'buffer_size_kb': buffer, 'tracing_on': tracing,
            'trace_options': options, 'tracing_cpumask': '3'}


def restore(trace, state, installed):
    failures = []
    actions = [('tracing_on', '0\n', False)]
    for name in reversed(installed):
        actions.extend([(f'events/{GROUP}/{name}/enable', '0\n', False),
                        ('kprobe_events', f'-:{GROUP}/{name}\n', True)])
    actions.extend([('trace_clock', state['clock'] + '\n', False),
                    ('buffer_size_kb', state['buffer_size_kb'] + '\n', False),
                    ('tracing_on', state['tracing_on'] + '\n', False)])
    for name, value, append in actions:
        try:
            trace.write(name, value, append=append)
        except BaseException as error:
            failures.append({'control': name, 'error': repr(error)})
    return failures


def start(trace, output, boot_id):
    state = idle_state(trace)  # No trace mutation before all preconditions pass.
    state.update({'boot_id': boot_id, 'start_boottime_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME),
                  'probes': PROBES, 'buffer_kib_per_cpu': 256, 'cpu_count': 2,
                  'max_text_bytes': MAX_TEXT, 'dispatch': 'NOT_RUN', 'frame_correlation': False,
                  'script_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()})
    save(output / 'state.json', state)  # Recoverable before touching controls.
    installed = []
    try:
        trace.write('tracing_on', '0\n')
        trace.write('trace_clock', 'boot\n')
        trace.write('buffer_size_kb', '256\n')
        trace.write('trace', '\n')
        for name, definition in zip(('enter', 'leave'), PROBES):
            trace.write('kprobe_events', definition + '\n', append=True)
            installed.append(name)
        for name in installed:
            trace.write(f'events/{GROUP}/{name}/enable', '1\n')
        trace.write('tracing_on', '1\n')
    except BaseException as error:
        failures = restore(trace, state, installed)
        save(output / 'failure.json', {'error': repr(error), 'restore_failures': failures})
        raise


def stop(trace, output, boot_id):
    state = json.loads((output / 'state.json').read_text())
    if state['boot_id'] != boot_id:
        raise ValueError('refusing controls from a different boot')
    if (output / 'result.json').exists() or (output / 'failure.json').exists():
        raise ValueError('attempt already ended; preserve it')
    expected = {f'{GROUP}/enter', f'{GROUP}/leave'}
    definitions = trace.read('dynamic_events').splitlines()
    actual = {line.split()[0].split(':', 1)[-1] for line in definitions if line.strip()}
    if actual != expected:
        raise ValueError('trace probe ownership changed; no controls modified')
    error = None
    capture_errors = []
    try:
        trace.write('tracing_on', '0\n')
        for source, filename in [('trace', 'trace.txt'), ('kprobe_profile', 'kprobe-profile.txt'),
                                 ('per_cpu/cpu0/stats', 'cpu0-stats.txt'),
                                 ('per_cpu/cpu1/stats', 'cpu1-stats.txt')]:
            try:
                with (output / filename).open('x') as stream:
                    stream.write(trace.read(source))
            except BaseException as caught:
                capture_errors.append({'source': source, 'error': repr(caught)})
        if capture_errors:
            raise RuntimeError('one or more trace exports failed')
        result = {'boot_id': boot_id, 'stop_boottime_ns': time.clock_gettime_ns(time.CLOCK_BOOTTIME),
                  'capture': 'RETAINED', 'dispatch': 'NOT_RUN', 'frame_correlation': False,
                  'loss_classification': 'REVIEW_RAW_STATS_AND_KPROBE_PROFILE',
                  'endpoint_filter': False, 'timing_claim': False}
    except BaseException as caught:
        error = caught
    finally:
        failures = restore(trace, state, ['enter', 'leave'])
    if error is not None or failures:
        save(output / 'failure.json', {'error': repr(error), 'capture_errors': capture_errors,
                                       'restore_failures': failures})
        raise RuntimeError('trace capture or restoration failed') from error
    result['restore_failures'] = failures
    save(output / 'result.json', result)


def guard():
    release = '6.12.111+deb13-arm64'
    if (os.geteuid() != 0 or platform.machine() != 'aarch64' or platform.release() != release
            or pathlib.Path('/etc/hostname').read_text().strip() != 'actryn-a16'):
        raise ValueError('only the dedicated pinned A16 guest is allowed')
    if b'linux,dummy-virt' not in pathlib.Path('/proc/device-tree/compatible').read_bytes().split(b'\0'):
        raise ValueError('QEMU virt required')
    if pathlib.Path('/sys/devices/system/cpu/online').read_text().strip() != '0-1':
        raise ValueError('exact two-CPU profile required')
    if hashlib.sha256(pathlib.Path('/boot/config-' + release).read_bytes()).hexdigest() != CONFIG_SHA256:
        raise ValueError('kernel config changed')
    return pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop'])
    parser.add_argument('output', type=pathlib.Path)
    args = parser.parse_args()
    boot_id = guard()
    if (args.output.parent != pathlib.Path('/var/tmp')
            or not re.fullmatch(r'actryn-a16-trace-[a-z0-9]+', args.output.name)):
        raise ValueError('new fixed /var/tmp/actryn-a16-trace-LABEL directory required')
    if args.action == 'start':
        args.output.mkdir(mode=0o700)
    trace = TraceFS(pathlib.Path('/sys/kernel/tracing'))
    (start if args.action == 'start' else stop)(trace, args.output, boot_id)


if __name__ == '__main__':
    main()
