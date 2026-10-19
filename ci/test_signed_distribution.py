# SPDX-License-Identifier: Apache-2.0
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import signed_distribution as signed


class SignedDistributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        paths = (
            "docs/development/solo-preview-qualification-v5.json",
            "docs/development/solo-maintainer-review-v5.json",
            "docs/development/release-key-custody.json",
            "docs/development/v0.0.1-signed-metadata/release-public.pem",
            "docs/development/v0.0.1-signed-metadata/server/manifest.json",
            "docs/development/v0.0.1-signed-metadata/server/signature.ed25519",
            "docs/development/v0.0.1-signed-metadata/robot/manifest.json",
            "docs/development/v0.0.1-signed-metadata/robot/signature.ed25519",
            "docs/development/signed-distribution-verification.json",
            "docs/development/final-distribution-archive-restore.json",
            "docs/development/v0.0.1-release-qualification.json",
        )
        for name in paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(signed.ROOT / name, target)
        self.receipt = json.loads((signed.ROOT / signed.DEFAULT_RECEIPT).read_text())

    def tearDown(self):
        self.temporary.cleanup()

    def test_exact_signed_metadata_and_bounded_receipt_pass(self):
        result = signed.validate(self.receipt, self.root)
        self.assertTrue(result["signed_distribution_verified"])
        self.assertTrue(result["release_qualified"])
        self.assertEqual(result["remaining"], [])
        self.assertEqual(result["metadata_signatures_verified"], 2)
        self.assertEqual(result["evidence_files_verified"], 0)

    def test_signature_or_trust_tampering_is_rejected(self):
        signature = self.root / "docs/development/v0.0.1-signed-metadata/server/signature.ed25519"
        signature.write_bytes(b"0" * 64)
        with self.assertRaises(ValueError):
            signed.validate(self.receipt, self.root)

    def test_scope_claims_cannot_be_widened(self):
        for field, value in (("physical_acceptance", True),
                             ("independent_installation", True),
                             ("release_qualified", True),
                             ("remaining", [])):
            with self.subTest(field=field):
                altered = copy.deepcopy(self.receipt)
                altered[field] = value
                with self.assertRaises(ValueError):
                    signed.validate(altered, self.root)

    def test_payload_or_qualification_identity_change_is_rejected(self):
        altered = copy.deepcopy(self.receipt)
        altered["roles"]["robot"]["payload_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            signed.validate(altered, self.root)

    def test_final_scope_or_archive_binding_cannot_be_widened(self):
        path = self.root / signed.FINAL_RECEIPT
        original = json.loads(path.read_text())
        for field, value in (("physical_acceptance", True),
                             ("independent_installation", True),
                             ("remaining_release_checks", ["hidden-check"])):
            with self.subTest(field=field):
                altered = copy.deepcopy(original)
                altered[field] = value
                path.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):
                    signed.validate(self.receipt, self.root)
        altered = copy.deepcopy(original)
        altered["archive_restore"]["sha256"] = "0" * 64
        path.write_text(json.dumps(altered))
        with self.assertRaises(ValueError):
            signed.validate(self.receipt, self.root)
        altered = copy.deepcopy(self.receipt)
        altered["qualification"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            signed.validate(altered, self.root)


if __name__ == "__main__":
    unittest.main()
