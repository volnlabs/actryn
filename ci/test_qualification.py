# SPDX-License-Identifier: Apache-2.0
import copy
import json
from pathlib import Path
import tempfile
import unittest

import qualification

ROOT = Path(__file__).resolve().parents[1]


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.packet = json.loads((ROOT / 'docs/development/final-qualification.json').read_text())

    def test_offline_check_explicitly_does_not_verify_absent_receipts(self):
        result = qualification.validate(self.packet)
        self.assertEqual(result['receipt_files_verified'], 0)
        self.assertFalse(result['release_qualified'])
        self.assertEqual(result['acceptance_rows'], 16)

    def test_lost_gate_false_promotion_unknown_reference_and_unsafe_path_reject(self):
        edits = [
            lambda p: p['acceptance_cases'].pop(),
            lambda p: p.update(promotable=True),
            lambda p: p['D2_predicates'][0].update(later_scoped_inputs=['unknown']),
            lambda p: next(iter(p['public_receipts'].values())).update(path='../private-key'),
            lambda p: p['A16']['original_comparison'].update(passed=80),
        ]
        for edit in edits:
            packet = copy.deepcopy(self.packet)
            edit(packet)
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                qualification.validate(packet)

    def test_missing_and_tampered_receipts_fail_local_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises((ValueError, OSError)):
                qualification.validate(self.packet, root)
            receipt = next(iter(self.packet['public_receipts'].values()))
            target = root / receipt['path']
            target.parent.mkdir(parents=True)
            target.write_text('tampered')
            with self.assertRaises(ValueError):
                qualification.validate(self.packet, root)


if __name__ == '__main__':
    unittest.main()
