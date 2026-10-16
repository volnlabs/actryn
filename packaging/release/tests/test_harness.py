# SPDX-License-Identifier: Apache-2.0
"""Host preparation/probe tests only: no SSH or guest installation."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import release
import test_release as fixtures


def harness():
    spec = importlib.util.spec_from_file_location('release_guest_harness', HERE / 'guest.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HarnessTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ReleaseTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.ReleaseTests.tearDownClass.__func__)
    setUp = fixtures.ReleaseTests.setUp
    spec = fixtures.ReleaseTests.spec

    def selected_spec(self):
        spec = self.spec('robot')
        spec['provenance']['qualification'] = 'incomplete'
        spec['provenance']['custodian_attestation'] = None
        spec['provenance']['evidence'] = {}
        for name in ('release.py', 'install.py'):
            source = Path(spec['files']['tools/' + name]['source'])
            source.write_bytes((HERE.parent / name).read_bytes())
            spec['files']['tools/' + name]['sha256'] = release.digest(source.read_bytes())
        path = self.root / 'selected-inputs.json'
        path.write_bytes(release.canonical(spec))
        return path, spec

    def test_fixture_preparation_preserves_pins_and_stores_one_payload(self):
        module = harness()
        selected, spec = self.selected_spec()
        output = self.root / 'prepared'
        job = module.prepare(selected, output)
        self.assertEqual(job['purpose'], 'integration-fixture-NOT-A-RELEASE')
        self.assertFalse(job['release_qualification'])
        self.assertEqual(job['input_spec_sha256'], release.digest(selected.read_bytes()))
        payloads = list(output.rglob('payload.tar'))
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0].stat().st_nlink, 1)
        for name in ('base', 'next', 'unsigned', 'incomplete', 'wrong-host'):
            manifest = json.loads((output / 'variants' / name / 'manifest.json').read_bytes())
            self.assertEqual(manifest['files'], json.loads((output / 'variants/base/manifest.json').read_bytes())['files'])
            self.assertEqual(manifest['provenance']['source_revision'], spec['provenance']['source_revision'])
        self.assertFalse((output / 'variants/unsigned/signature.ed25519').exists())
        self.assertNotIn('private-test-key.pem', module.upload_files(output, job))
        module.verify_prepared(output)
        with self.assertRaises((release.ReleaseError, OSError)): module.prepare(selected, output)

    def test_prepared_tampering_and_unselected_tools_are_rejected(self):
        module = harness()
        selected, spec = self.selected_spec()
        output = self.root / 'prepared'
        module.prepare(selected, output)
        (output / 'tools/install.py').write_bytes(b'changed')
        with self.assertRaises(release.ReleaseError): module.verify_prepared(output)
        source = Path(spec['files']['tools/install.py']['source'])
        source.write_bytes(b'changed selected tool')
        spec['files']['tools/install.py']['sha256'] = release.digest(source.read_bytes())
        selected.write_bytes(release.canonical(spec))
        with self.assertRaises(release.ReleaseError): module.prepare(selected, self.root / 'wrong-tools')

    def test_run_requires_explicit_disposable_and_image_ack_before_ssh(self):
        module = harness()
        selected, spec = self.selected_spec()
        prepared = self.root / 'prepared'
        module.prepare(selected, prepared)
        args = SimpleNamespace(fresh_disposable_guest='wrong', prepared=prepared,
                               image_sha512=spec['target']['image_sha512'])
        with mock.patch.object(module, 'ssh_base', side_effect=AssertionError('SSH must not run')):
            with self.assertRaises(release.ReleaseError): module.run(args)
            args.fresh_disposable_guest = module.MARKER
            args.image_sha512 = '0' * 128
            with self.assertRaises(release.ReleaseError): module.run(args)

    def test_identity_and_freshness_mismatch_rejects_before_upload(self):
        module = harness()
        job = {'role': 'robot', 'target': {'architecture': 'arm64', 'kernel_release': release.KERNEL['robot']}}
        probe = {'euid': 0, 'debian': '13.7', 'machine': 'aarch64', 'kernel': release.KERNEL['robot'],
                 'virtualization': 'qemu', 'boot_id': '1' * 32, 'machine_id': '2' * 32,
                 'installed': [], 'active_units': [], 'authority_loaded': False}
        module.verify_probe(job, probe, '1' * 32, '2' * 32)
        for field, value in [('euid', 1000), ('debian', '13.8'), ('machine', 'x86_64'),
                             ('kernel', 'wrong'), ('virtualization', 'none'), ('boot_id', '3' * 32),
                             ('machine_id', '4' * 32), ('installed', ['/opt/actryn']),
                             ('active_units', ['actryn-robotd']), ('authority_loaded', True)]:
            wrong = copy.deepcopy(probe); wrong[field] = value
            with self.assertRaises(release.ReleaseError, msg=field):
                module.verify_probe(job, wrong, '1' * 32, '2' * 32)


if __name__ == '__main__': unittest.main()
