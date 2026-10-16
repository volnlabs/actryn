#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Amendment 5: passive tracefs exclusivity guard for frozen capture 4."""
import argparse
import hashlib
import json
import pathlib
import tomllib

import capture_guest

HERE = pathlib.Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs():
    manifest = tomllib.loads((HERE / 'instrumentation5.toml').read_text())
    if manifest['revision'] != 5 or manifest['instrumentation4_sha256'] != sha(HERE / 'instrumentation4.toml'):
        raise ValueError('unchanged instrumentation 4 and amendment 5 required')
    for name, expected in manifest['sources'].items():
        if sha(HERE / name) != expected:
            raise ValueError('amendment 5 source changed: ' + name)
    return sha(HERE / 'instrumentation5.toml')


def passive_idle_state(trace):
    # This helper does not configure tracefs. Keep raw controls as evidence;
    # do not require a buffer-size string suitable for a later write/restore.
    names = ('current_tracer', 'events/enable', 'kprobe_events', 'dynamic_events',
             'set_event_pid', 'set_event_notrace_pid', 'trace', 'trace_clock',
             'buffer_size_kb', 'tracing_on', 'tracing_cpumask', 'trace_options')
    state = {name: trace.read(name) for name in names}
    if state['current_tracer'].strip() != 'nop' or state['events/enable'].strip() != '0':
        raise ValueError('exclusive idle tracefs required')
    for name in ('kprobe_events', 'dynamic_events', 'set_event_pid', 'set_event_notrace_pid'):
        if state[name].strip():
            raise ValueError('foreign trace control: ' + name)
    if any(line.strip() and not line.startswith('#') for line in state['trace'].splitlines()):
        raise ValueError('existing trace data must be retained by its owner first')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop'])
    parser.add_argument('output', type=pathlib.Path)
    args = parser.parse_args()
    amendment = verify_inputs()
    base = sha(HERE / 'instrumentation4.toml')
    metadata = args.output / 'instrumentation5.json'
    if args.action == 'stop':
        state = json.loads(metadata.read_text())
        if state.get('instrumentation5_sha256') != amendment or state.get('instrumentation4_sha256') != base:
            raise ValueError('capture amendment provenance changed')

    def passive_guard(trace):
        state = passive_idle_state(trace)
        # Frozen main creates the attempt directory before this callback and
        # issues no module command until it returns. Metadata is durable first.
        capture_guest.write_json(metadata, {'instrumentation5_sha256': amendment,
            'instrumentation4_sha256': base, 'passive_tracefs': state,
            'tracefs_mutated': False})
        return state

    original = capture_guest.idle_state
    capture_guest.idle_state = passive_guard
    try:
        capture_guest.main()  # Frozen target guard, input verification and lifecycle.
    finally:
        capture_guest.idle_state = original


if __name__ == '__main__':
    main()
