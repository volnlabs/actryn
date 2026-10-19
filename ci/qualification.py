#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check the historical incomplete packet, never certify release acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

CAP = 2 * 1024**2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_receipt(root, item):
    path = root / item['path']
    require(path.resolve().is_relative_to(root.resolve()), 'receipt escapes root')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= CAP, 'receipt type/size')
        raw = stream.read(CAP + 1)
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        for after in (os.fstat(stream.fileno()), path.lstat()):
            require(all(getattr(before, k) == getattr(after, k) for k in fields), 'receipt changed')
    require(len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256'],
            'receipt size/hash: ' + item['path'])
    return raw


def validate(packet, root=None):
    require(packet['qualification'] == 'incomplete' and packet['custodian_attestation'] is None,
            'historical packet must remain incomplete')
    for key in ('promotable', 'signature_verified', 'whole_D2_pass', 'whole_release_pass', 'physical_acceptance'):
        require(packet[key] is False, 'unsupported historical claim: ' + key)
    refs = packet['public_receipts']
    for item in refs.values():
        path = PurePosixPath(item['path'])
        require(not path.is_absolute() and '..' not in path.parts and bool(path.parts)
                and (path.parts[0] == 'artifacts' or str(path) == 'packaging/release/README.md'),
                'unsafe receipt path')
        require(re.fullmatch('[0-9a-f]{64}', item['sha256']) is not None, 'receipt digest')
        require(type(item['bytes']) is int and 0 <= item['bytes'] <= CAP, 'receipt size')
    require(not packet['missing_selected_receipts'], 'missing selected receipts')
    for key, prefix, count, claim, evidence in (
        ('acceptance_cases', 'A', 16, 'whole_row_pass', 'existing_scoped_evidence'),
        ('D2_predicates', 'D2-', 17, 'whole_predicate_qualified', 'later_scoped_inputs'),
    ):
        rows = packet[key]
        require([row['id'] for row in rows] == [f'{prefix}{i:02}' for i in range(1, count + 1)],
                'missing, duplicate or reordered gates: ' + key)
        for row in rows:
            require(row[claim] is False, 'historical gate unexpectedly closed')
            require(all(ref in refs for ref in row[evidence]), 'unbound evidence reference')
    original = packet['A16']['original_comparison']
    require(original['status'] == 'FAILED_PRESERVED' and
            [original[k] for k in ('planned', 'begun', 'ended', 'passed', 'failed')] == [80, 80, 80, 79, 1],
            'original A16 denominator/result changed')
    require(packet['A16']['separate_diagnostic02']['pooled_with_comparison'] is False,
            'diagnostic pooled into original comparison')
    require(set(packet['candidate_roles']) == {'server', 'robot'}, 'candidate roles')
    for role, candidate in packet['candidate_roles'].items():
        require(candidate['qualification'] == 'incomplete' and candidate['promotable'] is False
                and candidate['custodian_attestation'] is None, 'candidate approval invented')
        require(len(candidate['components']) == (27 if role == 'server' else 17), 'payload entry count')
        for key in ('manifest', 'assembly', 'component_map', 'independent_byte_review'):
            require(candidate[key] in refs, 'candidate receipt unbound')
        for component in candidate['components']:
            require(component['complete_origin_record']['receipt'] in refs, 'origin receipt unbound')
    checked = {}
    if root is not None:
        checked = {name: read_receipt(root, item) for name, item in refs.items()}
        for candidate in packet['candidate_roles'].values():
            manifest = json.loads(checked[candidate['manifest']])
            require(candidate['selected_provenance'] == manifest['provenance'], 'manifest provenance differs')
            projected = [{k: row[k] for k in ('path', 'size', 'mode', 'license', 'sha256')}
                         for row in candidate['components']]
            require(projected == manifest['files'], 'manifest payload projection differs')
    return {'check': 'historical-incomplete-packet-integrity', 'release_qualified': False,
            'receipt_references': len(refs), 'receipt_files_verified': len(checked),
            'acceptance_rows': 16, 'D2_predicates': 17, 'payload_entries': 44}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, default=Path('docs/development/final-qualification.json'))
    parser.add_argument('--receipt-root', type=Path, help='verify local receipt bytes and manifest projections')
    args = parser.parse_args()
    print(json.dumps(validate(json.loads(args.packet.read_text()), args.receipt_root), sort_keys=True))
