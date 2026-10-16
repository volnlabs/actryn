#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Amendment7 uses the derived capture lifecycle and unchanged passive guard."""
import argparse
import hashlib
import json
import pathlib
import tomllib
import capture_guest
from capture_guest5 import passive_idle_state

HERE = pathlib.Path(__file__).resolve().parent
CAPTURE_SOURCES = frozenset(('capture_guest.py', 'capture_guest5.py', 'capture_guest7.py',
    'uart_trace.py', 'dispatch.py', 'capture/Makefile', 'capture/prefix.h', 'capture/actryn_a16_capture.c'))
WORKLOAD_SOURCES = frozenset(('workload.c', 'first_sample7.h', 'protocol.h', 'common.h', 'engine.h',
    '../../actryn_wire.h', '../../actryn_control.h', '../../include/uapi/linux/actryn_authority.h'))
EXECUTION_SOURCES = CAPTURE_SOURCES | WORKLOAD_SOURCES | frozenset(('campaign.py', 'campaign6.py',
    'first_sample7.py', 'analyze.py', 'prepare.py', 'environment3.py', '../fixture_bridge.py',
    'manifest.toml', 'amendment2.toml', 'amendment3.toml', 'amendment6.toml',
    'instrumentation7.toml', 'amendment7.toml'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs():
    manifest = tomllib.loads((HERE / 'amendment7.toml').read_text())
    instrument = tomllib.loads((HERE / 'instrumentation7.toml').read_text())
    if manifest['revision'] != 7 or manifest['instrumentation7_sha256'] != sha(HERE / 'instrumentation7.toml'):
        raise ValueError('frozen amendment7 instrumentation required')
    fixed = {'revision': 7, 'max_prefix_bytes': 159, 'record_capacity': 4096,
             'record_bytes': 256, 'header_bytes': 128, 'kretprobe_maxactive': 64}
    if any(instrument.get(key) != value for key, value in fixed.items()):
        raise ValueError('exact ABI7 instrumentation limits required')
    for document in (manifest, instrument):
        if set(document.get('sources', {})) != CAPTURE_SOURCES:
            raise ValueError('complete exact capture source inventory required')
        for name, expected in document['sources'].items():
            if sha(HERE / name) != expected:
                raise ValueError('amendment7 capture source changed: ' + name)
    module = instrument.get('module_sha256', '')
    if len(module) != 64 or any(c not in '0123456789abcdef' for c in module):
        raise ValueError('exact compiled capture-module hash required')
    return sha(HERE / 'amendment7.toml')


def verify_campaign(manifest, here):
    if here != HERE:
        raise ValueError('campaign and capture must use the same frozen derived inputs')
    verify_inputs()
    amendment = tomllib.loads((HERE / 'amendment7.toml').read_text())
    if set(amendment.get('workload_sources', {})) != WORKLOAD_SOURCES:
        raise ValueError('complete derived workload source inventory required')
    if not EXECUTION_SOURCES <= set(manifest.get('sources', {})):
        raise ValueError('new executed/transitive source pin missing')
    for name, expected in manifest['sources'].items():
        if sha(HERE / name) != expected:
            raise ValueError('derived executed source changed: ' + name)
    for name, expected in amendment['workload_sources'].items():
        if sha(HERE / name) != expected or manifest['sources'][name] != expected:
            raise ValueError('derived workload source mismatch: ' + name)
    workload = amendment.get('workload_sha256', '')
    if len(workload) != 64 or any(c not in '0123456789abcdef' for c in workload):
        raise ValueError('exact compiled common workload hash required')
    if manifest.get('guest_binaries') != {
            'kernel/actryn_authority.ko': 'a49fd1a48bbdc39447a78fc0b0714e2e713c34f4fe25c11e989a790778291112',
            'a16-gateway': '305f5e1d15df9d2037b7ecc8246825a791a18d92c5f1408fed8de5b1062c9720',
            'a16-workload': workload}:
        raise ValueError('only the common workload binary may change from module6 selection')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop'])
    parser.add_argument('output', type=pathlib.Path)
    args = parser.parse_args()
    amendment = verify_inputs(); instrument = sha(HERE / 'instrumentation7.toml')
    metadata = args.output / 'amendment7.json'
    if args.action == 'stop':
        state = json.loads(metadata.read_text())
        if state.get('amendment7_sha256') != amendment or state.get('instrumentation7_sha256') != instrument:
            raise ValueError('capture amendment provenance changed')

    def passive_guard(trace):
        state = passive_idle_state(trace)
        capture_guest.write_json(metadata, {'amendment7_sha256': amendment,
            'instrumentation7_sha256': instrument, 'passive_tracefs': state, 'tracefs_mutated': False})
        return state

    original = capture_guest.idle_state
    capture_guest.idle_state = passive_guard
    try:
        capture_guest.main()
    finally:
        capture_guest.idle_state = original


if __name__ == '__main__':
    main()
