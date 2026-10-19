#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate solo-preview evidence readiness; never sign or approve a release."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

import qualification

OWNER = 'Utkarsh Maurya'
GATES = ([f'A{i:02}' for i in range(1, 17)]
         + [f'D2-{i:02}' for i in range(1, 18)] + ['MAINTAINER-INSTALL', 'KEY-RECOVERY', 'ARCHIVE-RESTORE'])
CAP = 2 * 1024**2
require = qualification.require
SPECIAL = {'A13', 'MAINTAINER-INSTALL', 'KEY-RECOVERY', 'ARCHIVE-RESTORE'}


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def decode(raw):
    return json.loads(raw, object_pairs_hook=unique)


def reference_valid(item, cap=CAP):
    require(set(item) == {'path', 'bytes', 'sha256'}, 'receipt fields')
    path = PurePosixPath(item['path'])
    require(not path.is_absolute() and '..' not in path.parts and bool(path.parts), 'unsafe receipt path')
    require(type(item['bytes']) is int and 0 <= item['bytes'] <= cap, 'receipt byte bound')
    require(isinstance(item['sha256'], str) and re.fullmatch('[0-9a-f]{64}', item['sha256']), 'receipt digest')


def checked_path(root, item):
    root = root.resolve()
    path = root / item['path']
    require(path.resolve().is_relative_to(root), 'receipt escapes root')
    require(not any(p.is_symlink() for p in (path, *path.parents) if p != root and p.is_relative_to(root)),
            'receipt symlink')
    return path


def read_evidence(root, item):
    reference_valid(item)
    path = checked_path(root, item)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= CAP, 'receipt type/size')
        raw = stream.read(CAP + 1)
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        for after in (os.fstat(stream.fileno()), path.lstat()):
            require(all(getattr(before, k) == getattr(after, k) for k in fields), 'receipt changed')
    require(len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256'], 'receipt size/hash')
    return raw


def verify_payload(root, item):
    reference_valid(item, cap=512 * 1024**2)
    path = checked_path(root, item)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size == item['bytes'], 'payload type/size')
        digest = hashlib.sha256()
        remaining = item['bytes']
        while remaining:
            block = stream.read(min(1024**2, remaining))
            require(bool(block), 'short payload')
            digest.update(block)
            remaining -= len(block)
        require(not stream.read(1), 'payload grew')
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        for after in (os.fstat(stream.fileno()), path.lstat()):
            require(all(getattr(before, k) == getattr(after, k) for k in fields), 'payload changed')
    require(digest.hexdigest() == item['sha256'], 'payload digest')


def validate_live_composition(receipt, subjects, refs):
    server = subjects['server']
    require(receipt.get('format') == 'actryn-live-observation-qualification-1'
            and receipt.get('status') == 'PASS_LIVE_OPERATION_AND_EXACT_PACKAGE_BY_BOUNDED_COMPOSITION',
            'live composition receipt')
    package = receipt.get('package', {})
    require(package.get('manifest_sha256') == refs[server['manifest']]['sha256']
            and package.get('payload_sha256') == server['payload_sha256']
            and package.get('changed_entries') == ['bin/actryn', 'bin/actryn-serverd']
            and package.get('qualification') == 'incomplete' and package.get('signed') is False,
            'live composition package identity')
    operation = receipt.get('live_operation', {})
    require(operation.get('reconciled') is True and operation.get('outstanding_debit') is False
            and operation.get('publication_closed') is True and operation.get('verdict') == 'TargetReached'
            and operation.get('provider_calls_during_cleanup') == 0,
            'live composition operation closure')
    provider = receipt.get('provider', {})
    require(provider.get('model') == 'gpt-5.4-mini-2026-03-17'
            and provider.get('authorized_calls') == 1 and provider.get('calls') == 1
            and provider.get('automatic_retry') is False,
            'live composition provider budget')
    target = receipt.get('exact_target', {})
    require(all(target.get(key) is True for key in ('fresh_install', 'installation_fixture_passed',
                                                     'bootstrap_passed', 'two_offline_attempts_passed',
                                                     'restart_recovery_export_passed', 'stopped_custody'))
            and receipt.get('physical_acceptance') is False
            and receipt.get('independent_installation') is False
            and receipt.get('release_promotion') is False
            and receipt.get('release_signature_verified') is False,
            'live composition qualification boundary')


def verify_subject_update(role, subject, update, history, refs, checked, root):
    require(set(update) == {'predecessor_manifest', 'qualification', 'payload'}, 'subject update fields')
    predecessor = history['candidate_roles'][role]
    require(update['predecessor_manifest'] in refs and update['qualification'] in refs,
            'subject update references')
    require(refs[update['predecessor_manifest']] == history['public_receipts'][predecessor['manifest']],
            'subject predecessor changed')
    manifest = decode(checked[subject['manifest']])
    previous = decode(checked[update['predecessor_manifest']])
    require(manifest['role'] == role and previous['role'] == role, 'manifest role mismatch')
    qualification = decode(checked[update['qualification']])
    validate_live_composition(qualification, {'server': subject}, refs)
    changed = qualification['package']['changed_entries']
    before = {row['path']: row for row in previous['files']}
    after = {row['path']: row for row in manifest['files']}
    require(len(before) == len(previous['files']) and len(after) == len(manifest['files'])
            and set(before) == set(after), 'subject payload paths changed')
    actual = [path for path in after if after[path] != before[path]]
    require(actual == changed, 'subject payload delta differs')
    payload = update['payload']
    reference_valid(payload, cap=512 * 1024**2)
    require(payload['sha256'] == subject['payload_sha256'], 'updated payload pin changed')
    verify_payload(root, payload)


def review_input_digest(packet):
    """Bind every input except the review's own receipt, avoiding a hash cycle."""
    value = {k: v for k, v in packet.items() if k != 'maintainer_review'}
    review = packet['maintainer_review']
    value['evidence'] = {k: v for k, v in packet['evidence'].items()
                         if review is None or k != review['evidence']}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()


def verify_special_gate(gate, packet, checked):
    reports = []
    for ref in gate['evidence']:
        try:
            report = decode(checked[ref])
        except (ValueError, UnicodeError):
            continue
        if (isinstance(report, dict) and report.get('format') == 'actryn-solo-check-1'
                and report.get('gate') == gate['id'] and report.get('status') == 'PASS'):
            reports.append(report)
    require(len(reports) == 1, 'dedicated gate report required: ' + gate['id'])
    report = reports[0]
    require(report.get('status') == 'PASS' and report.get('owner') == OWNER
            and report.get('subjects') == packet['subjects'], 'gate report identity/subjects')
    if gate['id'] == 'MAINTAINER-INSTALL':
        require(report.get('execution') == 'human' and report.get('operator') == OWNER
                and report.get('independent') is False, 'human maintainer report required')
        require(report.get('completed_checks') == ['install', 'diagnose', 'pair', 'offline-two-operations',
                                                  'cancel', 'restart-recover', 'export'], 'manual rehearsal incomplete')
    elif gate['id'] == 'KEY-RECOVERY':
        fingerprint = report.get('public_key_spki_sha256')
        require(isinstance(fingerprint, str) and re.fullmatch('[0-9a-f]{64}', fingerprint), 'public key fingerprint')
        require(report.get('restored_spki_sha256') == fingerprint and report.get('encrypted_key') is True
                and report.get('challenge_verified') is True and report.get('tamper_rejected') is True,
                'key recovery checks incomplete')
    elif gate['id'] == 'ARCHIVE-RESTORE':
        require(report.get('off_host') is True and report.get('all_entries_verified') is True
                and isinstance(report.get('filesystem_uuid'), str) and report['filesystem_uuid'].strip(),
                'off-host restoration required')
        for field in ('archive_sha256', 'restored_inventory_sha256'):
            require(isinstance(report.get(field), str) and re.fullmatch('[0-9a-f]{64}', report[field]), 'archive digest')
    else:
        standalone = report.get('standalone_receipt')
        composition = report.get('composition_receipt')
        require(standalone in checked and composition in checked and standalone != composition
                and standalone in gate['evidence'] and composition in gate['evidence'],
                'actual live receipts required')
        single, bound = decode(checked[standalone]), decode(checked[composition])
        require(single.get('status') == 'PASS' and single.get('test') == 'verified-oci-live-preview'
                and single.get('expect') == 'completed'
                and single.get('output', {}).get('value', {}).get('model') == 'gpt-5.4-mini-2026-03-17',
                'standalone live acceptance missing')
        validate_live_composition(bound, packet['subjects'], packet['evidence'])


def validate(packet, root=None):
    version = packet.get('format')
    fields = {'format', 'maintainer', 'physical_acceptance', 'independent_installation',
              'historical_packet', 'evidence', 'subjects', 'maintainer_review', 'gates'}
    if version == 'actryn-solo-qualification-2':
        fields.add('subject_updates')
    require(set(packet) == fields, 'packet fields')
    require(version in ('actryn-solo-qualification-1', 'actryn-solo-qualification-2')
            and packet['maintainer'] == OWNER, 'packet identity')
    require(packet['physical_acceptance'] is False and packet['independent_installation'] is False,
            'solo preview cannot claim physical or independent acceptance')
    refs = packet['evidence']
    require(isinstance(refs, dict) and 1 <= len(refs) <= 256, 'evidence count')
    for name, item in refs.items():
        require(re.fullmatch('[A-Za-z0-9_.-]{1,80}', name), 'reference name')
        reference_valid(item)
    require(packet['historical_packet'] in refs, 'historical packet missing')
    subjects = packet['subjects']
    require(set(subjects) == {'server', 'robot'}, 'both exact roles required')
    for subject in subjects.values():
        require(set(subject) == {'manifest', 'payload_sha256'} and subject['manifest'] in refs, 'subject fields')
        require(re.fullmatch('[0-9a-f]{64}', subject['payload_sha256']), 'payload pin')
    updates = packet.get('subject_updates', {})
    require((version == 'actryn-solo-qualification-2') == bool(updates)
            and isinstance(updates, dict)
            and (not updates or set(updates) == {'server'}), 'subject updates')
    for role, update in updates.items():
        require(set(update) == {'predecessor_manifest', 'qualification', 'payload'}
                and update['predecessor_manifest'] in refs and update['qualification'] in refs,
                'subject update fields/references')
        reference_valid(update['payload'], cap=512 * 1024**2)
        require(update['payload']['sha256'] == subjects[role]['payload_sha256'], 'subject update payload pin')
    gates = packet['gates']
    require([g['id'] for g in gates] == GATES, 'missing, duplicate or reordered gates')
    for gate in gates:
        require(set(gate) == {'id', 'required', 'status', 'evidence', 'association', 'remaining'}, 'gate fields')
        require(gate['required'] is (gate['id'] != 'A14'), 'only independent A14 may be deferred')
        require(gate['status'] in ('PASS', 'FAIL', 'NOT_RUN', 'DEFERRED'), 'gate status')
        require((gate['status'] == 'DEFERRED') == (gate['id'] == 'A14'), 'A14 must remain deferred')
        require(isinstance(gate['evidence'], list) and len(set(gate['evidence'])) == len(gate['evidence'])
                and all(ref in refs for ref in gate['evidence']), 'unbound/duplicate gate evidence')
        require(isinstance(gate['remaining'], str), 'remaining work')
        if gate['status'] == 'PASS':
            association = gate['association']
            require(gate['evidence'] and gate['remaining'] == '' and isinstance(association, dict),
                    'PASS needs evidence, exact association and no remaining work')
            require(set(association) == {'subjects', 'basis'} and association['subjects'] == subjects
                    and isinstance(association['basis'], str) and association['basis'].strip(), 'subject association')
        else:
            require(gate['association'] is None and gate['remaining'].strip(), 'open gate needs explicit remaining work')
    review = packet['maintainer_review']
    if review is not None:
        require(set(review) == {'owner', 'evidence'} and review['owner'] == OWNER
                and review['evidence'] in refs, 'maintainer review evidence')
        require(all(review['evidence'] not in g['evidence'] for g in gates), 'review cannot be its own gate evidence')
    checked = {}
    historical_count = 0
    if root is not None:
        checked = {name: read_evidence(root, item) for name, item in refs.items()}
        history = decode(checked[packet['historical_packet']])
        historical_count = qualification.validate(history, root)['receipt_files_verified']
        for role, subject in subjects.items():
            if role in updates:
                verify_subject_update(role, subject, updates[role], history, refs, checked, root)
                continue
            manifest = decode(checked[subject['manifest']])
            require(manifest['role'] == role, 'manifest role mismatch')
            historical = history['candidate_roles'][role]
            require(refs[subject['manifest']] == history['public_receipts'][historical['manifest']],
                    'selected manifest changed; revise historical association before qualification')
            require(manifest['files'] == [{k: c[k] for k in ('path', 'size', 'mode', 'license', 'sha256')}
                                         for c in historical['components']], 'selected payload projection')
            require(subject['payload_sha256'] == historical['payload']['sha256'], 'selected payload pin changed')
            verify_payload(root, {k: historical['payload'][k] for k in ('path', 'bytes', 'sha256')})
        for gate in gates:
            if gate['id'] in SPECIAL and gate['status'] == 'PASS':
                verify_special_gate(gate, packet, checked)
        if review is not None:
            receipt = decode(checked[review['evidence']])
            require(receipt.get('format') == 'actryn-solo-maintainer-review-1'
                    and receipt.get('owner') == OWNER and receipt.get('subjects') == subjects
                    and receipt.get('decision') == 'approve-for-attestation'
                    and receipt.get('dispositions') == {g['id']: g['status'] for g in gates}
                    and receipt.get('inputs_sha256') == review_input_digest(packet),
                    'maintainer review must bind exact inputs and gate dispositions')
    pending = [gate['id'] for gate in gates if gate['required'] and gate['status'] != 'PASS']
    return {'check': 'solo-preview-readiness-not-approval', 'release_qualified': False,
            'ready_for_attestation': root is not None and not pending and review is not None,
            'open_required_gates': pending, 'deferred_gates': ['A14'],
            'receipt_files_verified': len(checked), 'historical_receipts_verified': historical_count,
            'payload_archives_verified': 2 if root is not None else 0, 'maintainer_review_recorded': review is not None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', type=Path, default=Path('docs/development/solo-preview-qualification-v2.json'))
    parser.add_argument('--receipt-root', type=Path)
    parser.add_argument('--require-ready', action='store_true', help='fail unless local evidence and review are complete')
    args = parser.parse_args()
    result = validate(decode(args.packet.read_bytes()), args.receipt_root)
    print(json.dumps(result, sort_keys=True))
    if args.require_ready and not result['ready_for_attestation']:
        raise SystemExit(1)
