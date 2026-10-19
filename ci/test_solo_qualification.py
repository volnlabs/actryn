# SPDX-License-Identifier: Apache-2.0
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import solo_qualification as solo


class SoloQualificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.raw = b'{"test_only":true}\n'
        (self.root / 'receipt.json').write_bytes(self.raw)
        self.reference = {'path': 'receipt.json', 'bytes': len(self.raw),
                          'sha256': hashlib.sha256(self.raw).hexdigest()}
        self.packet = {
            'format': 'actryn-solo-qualification-1', 'maintainer': solo.OWNER,
            'physical_acceptance': False, 'independent_installation': False,
            'historical_packet': 'history', 'evidence': {'history': self.reference},
            'subjects': {role: {'manifest': 'history', 'payload_sha256': 'a' * 64}
                         for role in ('server', 'robot')},
            'maintainer_review': None,
            'gates': [{'id': name, 'required': name != 'A14',
                       'status': 'DEFERRED' if name == 'A14' else 'NOT_RUN',
                       'evidence': [], 'association': None,
                       'remaining': 'Not performed.'} for name in solo.GATES],
        }

    def test_structure_does_not_verify_receipts_or_qualify_release(self):
        result = solo.validate(self.packet)
        self.assertEqual(result['receipt_files_verified'], 0)
        self.assertFalse(result['ready_for_attestation'])
        self.assertFalse(result['release_qualified'])
        self.assertIn('A13', result['open_required_gates'])
        self.assertNotIn('A14', result['open_required_gates'])

    def test_gates_deferrals_and_claims_fail_closed(self):
        edits = [lambda p: p['gates'].pop(),
                 lambda p: p['gates'].append(p['gates'][0]),
                 lambda p: p['gates'][0].update(required=False),
                 lambda p: p['gates'][0].update(status='DEFERRED'),
                 lambda p: p['gates'][13].update(status='PASS'),
                 lambda p: p.update(independent_installation=True),
                 lambda p: p.update(physical_acceptance=True),
                 lambda p: p['gates'][0].update(status='PASS'),
                 lambda p: p['gates'][0].update(evidence=['absent']),
                 lambda p: p['subjects'].pop('robot')]
        for edit in edits:
            packet = copy.deepcopy(self.packet)
            edit(packet)
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                solo.validate(packet)

    def test_pass_requires_exact_subject_association_and_evidence(self):
        gate = self.packet['gates'][0]
        gate.update(status='PASS', evidence=['history'], remaining='', association={
            'subjects': copy.deepcopy(self.packet['subjects']),
            'basis': 'Test-only source association; not a real approval.'})
        solo.validate(self.packet)
        gate['association']['subjects']['server']['payload_sha256'] = 'b' * 64
        with self.assertRaises(ValueError):
            solo.validate(self.packet)

    def test_receipts_reject_tamper_missing_escape_symlink_and_duplicate_json(self):
        self.assertEqual(solo.read_evidence(self.root, self.reference), self.raw)
        (self.root / 'receipt.json').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            solo.read_evidence(self.root, self.reference)
        (self.root / 'receipt.json').unlink()
        with self.assertRaises(OSError):
            solo.read_evidence(self.root, self.reference)
        (self.root / 'receipt.json').symlink_to('/etc/passwd')
        with self.assertRaises((ValueError, OSError)):
            solo.read_evidence(self.root, self.reference)
        for path in ('../outside', '/etc/passwd'):
            with self.assertRaises(ValueError):
                solo.validate(dict(self.packet, evidence={'history': dict(self.reference, path=path)}))
        with self.assertRaises(ValueError):
            solo.decode(b'{"status":"PASS","status":"FAIL"}')

    def test_complete_structure_still_requires_local_bytes_and_human_review(self):
        for gate in self.packet['gates']:
            if gate['required']:
                gate.update(status='PASS', evidence=['history'], remaining='', association={
                    'subjects': copy.deepcopy(self.packet['subjects']), 'basis': 'Test fixture association.'})
        result = solo.validate(self.packet)
        self.assertEqual(result['open_required_gates'], [])
        self.assertFalse(result['ready_for_attestation'])
        self.packet['evidence']['review'] = self.reference
        self.packet['maintainer_review'] = {'owner': solo.OWNER, 'evidence': 'review'}
        self.assertFalse(solo.validate(self.packet)['ready_for_attestation'])
        # A complete-looking packet cannot bypass historical and manifest verification.
        with self.assertRaises((ValueError, KeyError)):
            solo.validate(self.packet, self.root)

    def test_payload_stream_verification_rejects_changed_archive(self):
        solo.verify_payload(self.root, self.reference)
        (self.root / 'receipt.json').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            solo.verify_payload(self.root, self.reference)

    def test_unrelated_history_cannot_fabricate_human_live_custody_or_review(self):
        def save(name, value):
            raw = json.dumps(value).encode()
            (self.root / name).write_bytes(raw)
            return {'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        history = {'candidate_roles': {}, 'public_receipts': {}}
        for role in ('server', 'robot'):
            ref = save(role + '.json', {'role': role, 'files': []})
            self.packet['evidence'][role] = ref
            history['public_receipts'][role] = ref
            history['candidate_roles'][role] = {'manifest': role, 'components': [], 'payload': self.reference}
            self.packet['subjects'][role] = {'manifest': role, 'payload_sha256': self.reference['sha256']}
        self.packet['evidence']['history'] = save('history.json', history)
        for gate in self.packet['gates']:
            if gate['required']:
                gate.update(status='PASS', evidence=['history'], remaining='', association={
                    'subjects': copy.deepcopy(self.packet['subjects']), 'basis': 'arbitrary'})
        self.packet['evidence']['review'] = self.packet['evidence']['history']
        self.packet['maintainer_review'] = {'owner': solo.OWNER, 'evidence': 'review'}
        # Isolate successor validation from the separately tested legacy packet checker.
        with patch.object(solo.qualification, 'validate', return_value={'receipt_files_verified': 0}):
            with self.assertRaises(ValueError):
                solo.validate(self.packet, self.root)
            # Even if gate evidence was separately reviewed, history is not a human approval.
            with patch.object(solo, 'verify_special_gate'), self.assertRaises(ValueError):
                solo.validate(self.packet, self.root)

    def test_dedicated_human_report_and_review_digest_bind_exact_subjects(self):
        gate = next(g for g in self.packet['gates'] if g['id'] == 'MAINTAINER-INSTALL')
        gate['evidence'] = ['human']
        report = {'format': 'actryn-solo-check-1', 'gate': gate['id'], 'owner': solo.OWNER,
                  'subjects': self.packet['subjects'], 'status': 'PASS', 'execution': 'human',
                  'operator': solo.OWNER, 'independent': False,
                  'completed_checks': ['install', 'diagnose', 'pair', 'offline-two-operations',
                                       'cancel', 'restart-recover', 'export']}
        solo.verify_special_gate(gate, self.packet, {'human': json.dumps(report).encode()})
        for change in ({'execution': 'agent'}, {'independent': True}, {'completed_checks': []}, {'subjects': {}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                solo.verify_special_gate(gate, self.packet, {'human': json.dumps(dict(report, **change)).encode()})
        first = solo.review_input_digest(self.packet)
        self.packet['gates'][0]['remaining'] = 'Changed evidence assessment'
        self.assertNotEqual(first, solo.review_input_digest(self.packet))

    def test_key_archive_and_live_reports_require_actual_scoped_checks(self):
        additions = {
            'KEY-RECOVERY': {'public_key_spki_sha256': 'a' * 64, 'restored_spki_sha256': 'a' * 64,
                             'encrypted_key': True, 'challenge_verified': True, 'tamper_rejected': True},
            'ARCHIVE-RESTORE': {'off_host': True, 'all_entries_verified': True, 'filesystem_uuid': 'test-drive',
                                'archive_sha256': 'a' * 64, 'restored_inventory_sha256': 'b' * 64},
            'A13': {'standalone_receipt': 'single', 'combined_receipt': 'bound'},
        }
        for name, checks in additions.items():
            gate = next(g for g in self.packet['gates'] if g['id'] == name)
            gate['evidence'] = ['report', 'single', 'bound']
            report = dict(format='actryn-solo-check-1', gate=name, owner=solo.OWNER,
                          status='PASS', subjects=self.packet['subjects'], **checks)
            receipts = {'single': json.dumps({'status': 'PASS', 'test': 'verified-oci-live-preview',
                        'expect': 'completed', 'output': {'value': {'model': 'gpt-5.4-mini-2026-03-17'}}}).encode(),
                        'bound': json.dumps({'status': 'PASS', 'test': 'isolated-live-agent-trusted-robot',
                        'live_provider_calls': True, 'provider_calls': 1, 'physical_acceptance': False}).encode()}
            receipts['report'] = json.dumps(report).encode()
            solo.verify_special_gate(gate, self.packet, receipts)
            bad = dict(report)
            bad.pop(next(iter(checks)))
            with self.subTest(name=name), self.assertRaises(ValueError):
                solo.verify_special_gate(gate, self.packet, dict(receipts, report=json.dumps(bad).encode()))


if __name__ == '__main__':
    unittest.main()
