# SPDX-License-Identifier: Apache-2.0
"""Synthetic artifacts and disposable filesystems only; no host install or authority."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from unittest import mock

import release
from install import Installer, MAX_SLOTS, SystemPlatform


def elf(machine, module=False, variant=0):
    head = bytearray(64)
    head[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', head, 16, 1 if module else 3, machine, 1)
    if not module:
        struct.pack_into('<Q', head, 32, 64)
        struct.pack_into('<HH', head, 54, 56, 1)
        return bytes(head) + struct.pack('<II6Q', 1, 5, 0, 0, 0, 0, 0, 4096) + b'fixture executable' + str(variant).encode()
    names = b'\0.shstrtab\0.note.gnu.build-id\0.modinfo\0'
    note = struct.pack('<III', 4, 20, 3) + b'GNU\0' + hashlib.sha1(str(variant).encode()).digest()
    info = b'vermagic=6.12.111+deb13-arm64 SMP\0license=GPL\0'
    data = bytes(head) + names + note + info
    sections = b'\0' * 64
    offset = 64
    for name, blob, kind in [(b'.shstrtab', names, 3), (b'.note.gnu.build-id', note, 7), (b'.modinfo', info, 1)]:
        sections += struct.pack('<IIQQQQIIQQ', names.index(name), kind, 0, 0, offset, len(blob), 0, 0, 1, 0)
        offset += len(blob)
    struct.pack_into('<Q', head, 40, len(data))
    struct.pack_into('<HHH', head, 58, 64, 4, 1)
    return bytes(head) + data[64:] + sections



def wheel(version='7.36.1'):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('google/protobuf/__init__.py', "__version__='7.36.1'\n")
        prefix = 'protobuf-7.36.1.dist-info/'
        archive.writestr(prefix + 'METADATA', f'Metadata-Version: 2.4\nName: protobuf\nVersion: {version}\nRequires-Python: >=3.10\n\n')
        archive.writestr(prefix + 'WHEEL', 'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n')
        archive.writestr(prefix + 'RECORD', '')
    return output.getvalue()


def oci():
    def encode(value): return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    blobs = {}
    def blob(data, media):
        hash_ = 'sha256:' + release.digest(data)
        blobs['blobs/sha256/' + hash_[7:]] = data
        return {'digest': hash_, 'size': len(data), 'mediaType': media}
    layer_stream = io.BytesIO()
    with tarfile.open(fileobj=layer_stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, data in [('bin/agent', elf(62)), ('etc/actryn/input.json', b'{}'), ('etc/actryn/input.schema.json', b'{}')]:
            header = tarfile.TarInfo(name); header.size = len(data)
            archive.addfile(header, io.BytesIO(data))
    layer = blob(layer_stream.getvalue(), 'application/vnd.oci.image.layer.v1.tar')
    config = blob(encode({'architecture': 'amd64', 'os': 'linux', 'config': {'Entrypoint': ['/bin/agent'],
        'User': '65532:65532', 'WorkingDir': '/tmp', 'Labels': {'org.actryn.profile': 'offline-preview-v1'}},
        'rootfs': {'type': 'layers', 'diff_ids': [layer['digest']]}}), 'application/vnd.oci.image.config.v1+json')
    manifest = blob(encode({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
        'config': config, 'layers': [layer]}), 'application/vnd.oci.image.manifest.v1+json')
    files = {**blobs, 'oci-layout': encode({'imageLayoutVersion': '1.0.0'}),
        'index.json': encode({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': [manifest]})}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(files.items()):
            header = tarfile.TarInfo(name); header.size = len(data)
            archive.addfile(header, io.BytesIO(data))
    return output.getvalue()


class Platform:
    """Observes installer decisions; not a simulated effective grant table."""
    def __init__(self, expected):
        self.expected = expected
        self.events = []
        self.deny = False
    def inspect_host(self, manifest):
        self.events.append('host')
        release.require(manifest['target'] == self.expected, 'host tuple mismatch')
    def check_maintenance(self, role, fresh, recorded=False):
        self.events.append(('maintenance', role, fresh, recorded))
        release.require(not self.deny, 'manager not inhibited/reconciled')
    def stop(self, role): self.events.append(('stop', role))
    def check_config(self, role, config): self.events.append(('config-check', role))
    def check_resume(self, role): self.events.append(('resume-check', role))
    def check_start(self, manifest, slot): self.events.append(('start-check', manifest['role']))
    def reload(self): self.events.append('reload')


class Crash(BaseException):
    pass


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.TemporaryDirectory(prefix='actryn-test-keys-')
        key_root = Path(cls.keys.name)
        cls.private, cls.public = key_root / 'private.pem', key_root / 'public.pem'
        release.openssl(['genpkey', '-algorithm', 'ED25519', '-out', str(cls.private)])
        release.openssl(['pkey', '-in', str(cls.private), '-pubout', '-out', str(cls.public)])
        cls.fingerprint = release.digest(release.openssl(['pkey', '-pubin', '-in', str(cls.public), '-outform', 'DER']))
    @classmethod
    def tearDownClass(cls): cls.keys.cleanup()
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='actryn-release-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.number = 0
    def spec(self, role='robot', variant=0):
        self.number += 1
        source = self.root / f'inputs-{self.number}'
        source.mkdir(mode=0o700)
        files = {}
        for number, name in enumerate(sorted(release.FILES[role])):
            if name == release.BPF_OBJECT:
                data = bytearray(elf(247, variant=variant)); struct.pack_into('<H', data, 16, 1); data = bytes(data)
            elif name.startswith('bin/') or name.startswith('module/'):
                data = elf(release.MACHINE[role], name.startswith('module/'), variant)
            elif name.endswith('.whl'):
                data = wheel()
            elif name == 'share/agent/offline-oci.tar':
                data = oci()
            elif name == 'share/sdk/pyproject.toml':
                data = b'[project]\nname="actryn-sdk"\nversion="0.0.1"\nrequires-python=">=3.11"\ndependencies=["protobuf==7.36.1"]\n'
            elif name.endswith('.dtb'):
                data = b'\xd0\x0d\xfe\xedfixture device tree'
            else:
                data = f'fixture retained {name} {variant}\n'.encode()
            path = source / str(number)
            path.write_bytes(data)
            files[name] = {'source': str(path), 'sha256': release.digest(data)}
        packages = {'systemd': '257.9-1', 'openssl': '3.5.4-1', 'python3': '3.13.5-1', f'linux-image-{release.KERNEL[role]}': '6.12.111-1'}
        packages.update({name: '1.0-test' for name in release.RUNTIME_PACKAGES[role]})
        if role == 'server': packages.update(containerd='1.7.24~ds1-6+deb13u1', runc='1.1.15+ds1-2+b4', **{'python3-venv':'3.13.5-1'})
        return {'role': role, 'version': '0.0.1', 'compatibility': dict(release.COMPATIBILITY),
                'target': {'distribution': 'debian', 'version': '13.7', 'architecture': release.ARCH[role],
                    'kernel_release': release.KERNEL[role], 'kernel_image_sha256': '1' * 64,
                    'kernel_config_sha256': '2' * 64, 'image_sha512': '3' * 128, 'packages': packages},
                'provenance': {'source_revision': '4' * 40, 'rust': '1.92.0',
                    'build_inputs_sha256': files['share/target/build-inputs.toml']['sha256'],
                    'qualification': 'software-preview-qualified', 'evidence': {'qualification-bundle': '5' * 64},
                    'custodian_attestation': {'role': role,
                        'scope': 'server-independent-D2' if role == 'server' else 'robot-software-preview',
                        'qualification_bundle_sha256': '5' * 64}},
                'files': files}
    def bundle(self, role='robot', variant=0, signed=True):
        spec = self.spec(role, variant)
        output = self.root / f'bundle-{self.number}'
        release.build(spec, output)
        if signed: self.sign(output)
        return spec, output
    def sign(self, output):
        release.openssl(['pkeyutl', '-sign', '-inkey', str(self.private), '-rawin', '-in', str(output / 'manifest.json'), '-out', str(output / 'signature.ed25519')])
    def install_root(self, name='machine'):
        root = self.root / name
        root.mkdir(mode=0o700)
        for item in ('var/lib/actryn-robot/runtime/evidence', 'etc/actryn/robot/device.key', 'var/lib/actryn-server/intents'):
            path = root / item
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'preserve existing bytes')
            path.chmod(0o600)
        return root
    def installer(self, root, spec, fault=None, role=None):
        return Installer(root, Platform(spec['target']), role or spec['role'], fault)
    def run_install(self, installer, action, bundle):
        return installer.run(action, bundle, self.public, self.fingerprint)
    def tree(self, root):
        return {str(p.relative_to(root)): (os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
                for p in root.rglob('*')}

    def test_reproducible_complete_role_builder_and_unsigned_candidate(self):
        spec = self.spec('server')
        one, two = self.root / 'one', self.root / 'two'
        status = release.build(spec, one)
        release.build(spec, two)
        self.assertEqual(status['status'], 'unsigned_candidate')
        self.assertFalse(status['promotable'])
        for name in ('manifest.json', 'payload.tar'):
            self.assertEqual((one / name).read_bytes(), (two / name).read_bytes())
        _, _, status = release.load_bundle(one)
        self.assertFalse(status['signature_verified'])
        with self.assertRaises((release.ReleaseError, OSError)):
            release.load_bundle(one, self.public, self.fingerprint)
        self.assertEqual(release.FILES['server'] & {'module/actryn_authority.ko', 'bin/actryn-robotd'}, set())

    def test_builder_rejects_hash_architecture_incomplete_and_secret_inputs_before_output(self):
        for kind in ('hash', 'architecture', 'incomplete', 'secret', 'link'):
            spec = self.spec()
            source = spec['files']['bin/actryn']
            if kind == 'hash': source['sha256'] = '0' * 64
            if kind == 'architecture':
                Path(source['source']).write_bytes(elf(62))
                source['sha256'] = release.digest(elf(62))
            if kind == 'incomplete': del spec['files']['module/actryn_authority.ko']
            if kind == 'secret': spec['files']['etc/actryn/robot/device.key'] = source
            if kind == 'link':
                linked = self.root / 'linked'
                linked.symlink_to(source['source'])
                source['source'] = str(linked)
            output = self.root / ('rejected-' + kind)
            with self.assertRaises((release.ReleaseError, OSError)):
                release.build(spec, output)
            self.assertFalse(output.exists())

    def test_runtime_library_package_pins_are_mandatory_for_each_role(self):
        for role in ('server', 'robot'):
            spec = self.spec(role)
            release.target_valid(role, spec['target'])
            for package in release.RUNTIME_PACKAGES[role]:
                changed = copy.deepcopy(spec['target'])
                del changed['packages'][package]
                with self.assertRaises(release.ReleaseError, msg=(role, package)):
                    release.target_valid(role, changed)

    def test_host_rejects_runtime_package_drift_before_install_mutation(self):
        spec = self.spec('server')
        target = spec['target']
        binaries = {f'/boot/vmlinuz-{release.KERNEL["server"]}': b'image',
                    f'/boot/config-{release.KERNEL["server"]}': b'config', '/etc/debian_version': b'13.7'}
        target['kernel_image_sha256'] = release.digest(b'image')
        target['kernel_config_sha256'] = release.digest(b'config')
        adapter = SystemPlatform()
        for drift in (None, *sorted(release.RUNTIME_PACKAGES['server'])):
            def command(argv):
                return (target['packages'][argv[-1]] + ('-changed' if argv[-1] == drift else '')).encode()
            with mock.patch('install.os.geteuid', return_value=0), \
                    mock.patch('install.platform.machine', return_value='x86_64'), \
                    mock.patch('install.platform.release', return_value=release.KERNEL['server']), \
                    mock.patch('install.read_file', side_effect=lambda path, *args: binaries[path]), \
                    mock.patch('install.command', side_effect=command):
                if drift is None: adapter.inspect_host(spec)
                else:
                    with self.assertRaisesRegex(release.ReleaseError, 'package mismatch: ' + drift):
                        adapter.inspect_host(spec)

    def test_server_bpf_is_required_pinned_relocatable_and_installed_immutably(self):
        name = 'lib/observer.bpf.o'
        self.assertIn(name, release.FILES['server'])
        for problem in ('missing', 'architecture', 'kind', 'hash'):
            spec = self.spec('server')
            item = spec['files'][name]
            if problem == 'missing': del spec['files'][name]
            else:
                data = bytearray(Path(item['source']).read_bytes())
                if problem == 'architecture': struct.pack_into('<H', data, 18, 62)
                elif problem == 'kind': struct.pack_into('<H', data, 16, 3)
                else: data[-1] ^= 1
                Path(item['source']).write_bytes(data)
                if problem != 'hash': item['sha256'] = release.digest(data)
            with self.assertRaises(release.ReleaseError): release.build(spec, self.root / ('bad-bpf-' + problem))
        spec, bundle = self.bundle('server')
        root = self.install_root('bpf-machine')
        installer = self.installer(root, spec)
        identity = self.run_install(installer, 'activate', bundle)['manifest_sha256']
        path = root / 'usr/lib/actryn/observer.bpf.o'
        self.assertEqual(os.readlink(path), '/opt/actryn/server/current/' + name)
        slot = installer.slots / identity
        retained = slot / 'payload' / name
        self.assertEqual(release.digest(retained.read_bytes()), spec['files'][name]['sha256'])
        verified = {'manifest_sha256': identity, 'key_fingerprint': self.fingerprint}
        retained.write_bytes(retained.read_bytes() + b'tampered')
        with self.assertRaises(release.ReleaseError): installer.verify_slot(slot, verified)

    def test_signature_target_role_and_maintenance_mismatch_change_nothing(self):
        spec, bundle = self.bundle()
        for kind in ('key', 'signature', 'role', 'host', 'maintenance', 'unsigned', 'qualification'):
            root = self.install_root(kind)
            before = self.tree(root)
            installer = self.installer(root, spec, role='server' if kind == 'role' else None)
            fingerprint = self.fingerprint
            if kind == 'host': installer.platform.expected = dict(spec['target'], architecture='amd64')
            if kind == 'maintenance': installer.platform.deny = True
            if kind == 'key': fingerprint = 'f' * 64
            signature = (bundle / 'signature.ed25519').read_bytes()
            manifest = (bundle / 'manifest.json').read_bytes()
            if kind == 'signature': (bundle / 'signature.ed25519').write_bytes(b'0' * 64)
            if kind == 'unsigned': (bundle / 'signature.ed25519').unlink()
            if kind == 'qualification':
                value = json.loads(manifest)
                value['provenance']['qualification'] = 'incomplete'
                value['provenance']['custodian_attestation'] = None
                (bundle / 'manifest.json').write_bytes(release.canonical(value)); self.sign(bundle)
            try:
                with self.assertRaises((release.ReleaseError, OSError)):
                    installer.run('activate', bundle, self.public, fingerprint)
                self.assertEqual(before, self.tree(root), kind)
            finally:
                (bundle / 'manifest.json').write_bytes(manifest)
                (bundle / 'signature.ed25519').write_bytes(signature)

    def test_archive_links_paths_trailing_bytes_and_noncanonical_json_rejected(self):
        _, bundle = self.bundle()
        original = (bundle / 'payload.tar').read_bytes()
        for kind in ('symlink', 'hardlink', 'escape', 'duplicate', 'tail'):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w') as archive:
                member = tarfile.TarInfo('../escape' if kind == 'escape' else 'bin/actryn')
                if kind in ('symlink', 'hardlink'):
                    member.type = tarfile.SYMTYPE if kind == 'symlink' else tarfile.LNKTYPE
                    member.linkname = '/etc/actryn/robot/device.key'
                archive.addfile(member)
                if kind == 'duplicate': archive.addfile(member)
            (bundle / 'payload.tar').write_bytes(original + b'evil' if kind == 'tail' else stream.getvalue())
            with self.assertRaises(release.ReleaseError): release.load_bundle(bundle, self.public, self.fingerprint)
        (bundle / 'payload.tar').write_bytes(original)
        path = bundle / 'manifest.json'; path.write_bytes(path.read_bytes().replace(b'"role":', b'"role":"server","role":', 1))
        with self.assertRaises(release.ReleaseError): release.load_bundle(bundle)

    def test_role_activation_and_rollback_preserve_state_and_keep_inhibited(self):
        spec, old = self.bundle('server', 0)
        _, new = self.bundle('server', 1)
        root = self.install_root()
        before = self.tree(root)
        installer = self.installer(root, spec)
        old_id = self.run_install(installer, 'activate', old)['manifest_sha256']
        new_id = self.run_install(installer, 'activate', new)['manifest_sha256']
        self.assertNotEqual(old_id, new_id)
        self.assertEqual(installer.current(), new_id)
        self.assertTrue(installer.gate.is_file())
        self.assertTrue((root / 'usr/bin/actryn-serverd').is_symlink())
        self.assertFalse((root / 'usr/bin/actryn-robotd').exists())
        self.run_install(installer, 'rollback', old)
        self.assertEqual(installer.current(), old_id)
        for name, data in before.items():
            self.assertTrue((root / name).is_dir()) if data is None else self.assertEqual((root / name).read_bytes(), data)
        self.assertTrue(all(event == 'host' or event == 'reload' or event[0] in ('stop', 'maintenance') for event in installer.platform.events))

    def test_every_recorded_durable_boundary_crash_recovers_complete_inhibited_tuple(self):
        spec, bundle = self.bundle()
        root = self.install_root('reference')
        boundaries = []
        self.run_install(self.installer(root, spec, boundaries.append), 'activate', bundle)
        self.assertGreater(len(boundaries), 20)
        for number, boundary in enumerate(boundaries):
            root = self.install_root(f'crash-{number}')
            before = self.tree(root)
            def fail(name):
                if name == boundary: raise Crash(name)
            installer = self.installer(root, spec, fail)
            with self.assertRaises(Crash): self.run_install(installer, 'activate', bundle)
            self.assertTrue(installer.gate.exists(), boundary)
            recovered = self.installer(root, spec)
            self.run_install(recovered, 'recover', bundle)
            self.assertTrue(recovered.gate.exists(), boundary)
            self.assertIsNotNone(recovered.current(), boundary)
            for name, data in before.items():
                self.assertTrue((root / name).is_dir()) if data is None else self.assertEqual((root / name).read_bytes(), data, boundary)

    def test_capacity_and_managed_path_symlinks_fail_before_state_changes(self):
        spec, bundle = self.bundle()
        root = self.install_root()
        installer = self.installer(root, spec)
        for i in range(MAX_SLOTS):
            slot = installer.slots / (str(i) * 64)
            slot.mkdir(parents=True)
        before = self.tree(root)
        with self.assertRaises(release.ReleaseError): self.run_install(installer, 'activate', bundle)
        self.assertEqual(before, self.tree(root))
        root = self.install_root('symlink')
        (root / 'usr').symlink_to(self.root / 'outside')
        before = self.tree(root)
        with self.assertRaises(release.ReleaseError): self.run_install(self.installer(root, spec), 'activate', bundle)
        self.assertEqual(before, self.tree(root))

    def test_tampered_active_tuple_is_rejected_before_any_update_mutation(self):
        spec, old = self.bundle('server', 0)
        _, new = self.bundle('server', 1)
        root = self.install_root()
        installer = self.installer(root, spec)
        old_id = self.run_install(installer, 'activate', old)['manifest_sha256']
        path = installer.slots / old_id / 'payload/bin/actryn'
        path.write_bytes(b'tampered active executable')
        before = self.tree(root)
        with self.assertRaises(release.ReleaseError): self.run_install(installer, 'activate', new)
        self.assertEqual(before, self.tree(root))

    def test_offline_assets_reject_changed_wheel_version_and_oci_payload(self):
        for name, data in [('share/wheels/protobuf-7.36.1-py3-none-any.whl', wheel('1.0.0')),
                           ('share/agent/offline-oci.tar', b'not an OCI layout')]:
            spec = self.spec('server')
            path = Path(spec['files'][name]['source']); path.write_bytes(data)
            spec['files'][name]['sha256'] = release.digest(data)
            output = self.root / ('asset-rejected-' + str(self.number))
            with self.assertRaises(release.ReleaseError): release.build(spec, output)
            self.assertFalse(output.exists())

    def test_qualified_candidate_requires_named_aggregate_evidence(self):
        for role in ('robot', 'server'):
            for fault in ('missing-bundle', 'missing-attestation', 'wrong-role', 'wrong-scope', 'wrong-hash'):
                spec = self.spec(role)
                provenance = spec['provenance']
                if fault == 'missing-bundle': provenance['evidence'] = {'unrelated-test': '5' * 64}
                if fault == 'missing-attestation': provenance['custodian_attestation'] = None
                if fault == 'wrong-role': provenance['custodian_attestation']['role'] = 'server' if role == 'robot' else 'robot'
                if fault == 'wrong-scope': provenance['custodian_attestation']['scope'] = 'all-acceptance-complete'
                if fault == 'wrong-hash': provenance['custodian_attestation']['qualification_bundle_sha256'] = '6' * 64
                output = self.root / ('missing-qualification-' + str(self.number))
                with self.assertRaises(release.ReleaseError): release.build(spec, output)
                self.assertFalse(output.exists())

    def test_sparse_oversized_input_rejected_without_read_or_output(self):
        spec = self.spec()
        source = Path(spec['files']['bin/actryn']['source'])
        with source.open('r+b') as stream: stream.truncate(release.MAX_FILE + 1)
        output = self.root / 'oversized'
        with self.assertRaises(release.ReleaseError): release.build(spec, output)
        self.assertFalse(output.exists())

    def test_interrupted_update_keeps_old_or_new_complete_tuple_and_never_restores_state(self):
        spec, old = self.bundle('server', 0)
        _, new = self.bundle('server', 1)
        new_id = release.load_bundle(new)[2]['manifest_sha256']
        for index, boundary in enumerate(('gate', 'maintenance-record', 'trust-record', 'journal-staging',
                'staged-manifest.json', 'payload-bin/actryn', 'slot-published', 'pointer', 'journal-installed')):
            root = self.install_root('update-crash-' + str(index))
            installer = self.installer(root, spec)
            old_id = self.run_install(installer, 'activate', old)['manifest_sha256']
            old_bytes = (installer.slots / old_id / 'payload/bin/actryn').read_bytes()
            def fail(name):
                if name == boundary: raise Crash(name)
            interrupted = self.installer(root, spec, fail)
            with self.assertRaises(Crash): self.run_install(interrupted, 'activate', new)
            self.assertIn(interrupted.current(), (old_id, new_id))
            self.assertTrue(interrupted.gate.is_file())
            self.assertEqual((installer.slots / old_id / 'payload/bin/actryn').read_bytes(), old_bytes)
            self.run_install(self.installer(root, spec), 'recover', new)
            self.assertEqual(interrupted.current(), new_id)
            self.assertTrue(interrupted.gate.is_file())
            self.assertEqual((root / 'var/lib/actryn-server/intents').read_bytes(), b'preserve existing bytes')

    def test_cli_role_mismatch_is_structured_rejection_before_host_installation(self):
        _, bundle = self.bundle('server')
        result = subprocess.run([sys.executable, str(Path(release.__file__)), 'stage', '--role', 'robot',
            '--bundle', str(bundle), '--public-key', str(self.public), '--key-sha256', self.fingerprint],
            capture_output=True, timeout=5, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(b'Traceback', result.stderr)
        rejected = json.loads(result.stderr)
        self.assertEqual(rejected['result'], 'rejected')
        self.assertIn('matching role', rejected['error'])

    def test_installed_direct_entry_never_writes_bytecode_into_signed_slot(self):
        spec = self.spec('server')
        for name in ('release.py', 'install.py'):
            data = Path(release.__file__).with_name(name).read_bytes()
            source = Path(spec['files']['tools/' + name]['source'])
            source.write_bytes(data)
            spec['files']['tools/' + name]['sha256'] = release.digest(data)
        bundle = self.root / 'actual-tools-bundle'
        release.build(spec, bundle); self.sign(bundle)
        root = self.install_root()
        installer = self.installer(root, spec)
        identity = self.run_install(installer, 'activate', bundle)['manifest_sha256']
        slot = installer.slots / identity
        before = self.tree(slot)
        result = subprocess.run([sys.executable, str(slot / 'payload/tools/release.py'), 'stage',
            '--role', 'robot', '--bundle', str(bundle), '--public-key', str(self.public),
            '--key-sha256', self.fingerprint], capture_output=True, timeout=5,
            env={'PATH': '/usr/bin:/bin'})
        self.assertEqual(result.returncode, 1)
        self.assertIn('matching role', json.loads(result.stderr)['error'])
        self.assertEqual(before, self.tree(slot))
        self.assertFalse((slot / 'payload/tools/__pycache__').exists())
        installer.verify_slot(slot, {'manifest_sha256': identity, 'key_fingerprint': self.fingerprint})

    def test_server_config_check_uses_installed_daemon_before_accepting_readiness(self):
        adapter = SystemPlatform()
        account = mock.Mock(pw_uid=987, pw_gid=987, pw_shell='/usr/sbin/nologin')
        group = mock.Mock(gr_gid=987)
        config = {'server_uid': 987, 'operator_uid': 1000, 'io_device': '8:0', 'artifacts': {}}
        with mock.patch('install.pwd.getpwnam', return_value=account), mock.patch('install.grp.getgrnam', return_value=group):
            with mock.patch('install.command', return_value=b'{"result":"configuration_valid","artifact_count":1,"authority_issued":false}') as command:
                adapter.check_config('server', config)
                command.assert_called_once_with(['/usr/bin/actryn-serverd', '--check-config'])
            for reply in (b'{"result":"wrong"}', b'invalid JSON',
                          b'{"result":"configuration_valid","artifact_count":1}',
                          b'{"result":"configuration_valid","artifact_count":0,"authority_issued":false}',
                          b'{"result":"configuration_valid","artifact_count":true,"authority_issued":false}',
                          b'{"result":"configuration_valid","artifact_count":1,"authority_issued":true}'):
                with mock.patch('install.command', return_value=reply):
                    with self.assertRaises(release.ReleaseError): adapter.check_config('server', config)
            with mock.patch('install.command', side_effect=release.ReleaseError('daemon rejects configuration')):
                with self.assertRaises(release.ReleaseError): adapter.check_config('server', config)
            with mock.patch('install.command') as command:
                with self.assertRaises(release.ReleaseError): adapter.check_config('server', dict(config, server_uid=986))
                command.assert_not_called()
            with mock.patch('install.command') as command:
                adapter.check_config('robot', {'gateway_uid': 987, 'operator_uid': 1000})
                command.assert_not_called()

    def test_production_start_checks_loaded_build_identity_and_resume_requires_unload(self):
        spec, bundle = self.bundle()
        root = self.install_root()
        installer = self.installer(root, spec)
        identity = self.run_install(installer, 'activate', bundle)['manifest_sha256']
        slot = installer.slots / identity
        expected = release.module_note((slot / 'payload/module/actryn_authority.ko').read_bytes())
        wrong = release.module_note(elf(183, True, 99))
        real_read = release.read_file
        adapter = SystemPlatform()
        def read_with_note(note):
            def read(path, limit=release.MAX_FILE):
                if str(path) == '/sys/module/actryn_authority/notes/.note.gnu.build-id': return note
                return real_read(path, limit)
            return read
        with mock.patch('install.read_file', side_effect=read_with_note(wrong)):
            with self.assertRaises(release.ReleaseError): adapter.check_start({'role': 'robot'}, slot)
        with mock.patch('install.read_file', side_effect=read_with_note(expected)):
            adapter.check_start({'role': 'robot'}, slot)
        with mock.patch('install.Path') as path:
            path.return_value.exists.return_value = True
            with self.assertRaises(release.ReleaseError): adapter.check_resume('robot')
        self.assertIn(b'ExecStartPre=+/usr/bin/python3 -B -E -s ', installer.gate_bytes())
        self.assertIn(b'current/tools/release.py preflight --role robot', installer.gate_bytes())
        with self.assertRaises(release.ReleaseError): installer.preflight()

    def test_server_exact_optional_credential_routes_preserve_local_secret_and_peer_files(self):
        spec, bundle = self.bundle('server')
        root = self.install_root()
        directory = root / 'etc/systemd/system/actryn-serverd.service.d'
        directory.mkdir(parents=True)
        routes = {'50-openai-credential.conf': b'[Service]\nLoadCredential=openai-api-key:/etc/actryn/credentials/openai-api-key\n',
                  '50-robot-credential.conf': b'[Service]\nLoadCredential=robot-client-key:/etc/actryn/credentials/robot-client-key\n'}
        for name, data in routes.items(): (directory / name).write_bytes(data)
        secret = root / 'etc/actryn/credentials/robot-client-key'
        secret.parent.mkdir(parents=True); secret.write_bytes(b'private local key'); secret.chmod(0o600)
        peer = root / 'etc/actryn/robot-peer.json'; peer.write_bytes(b'local public peer configuration')
        installer = self.installer(root, spec)
        self.run_install(installer, 'activate', bundle)
        for name, data in routes.items(): self.assertEqual((directory / name).read_bytes(), data)
        self.assertEqual(secret.read_bytes(), b'private local key')
        self.assertEqual(peer.read_bytes(), b'local public peer configuration')
        for wrong in (b'[Service]\nLoadCredential=robot-client-key:/tmp/untrusted\n',
                      routes['50-robot-credential.conf'] + b'ExecStart=/bin/sh\n'):
            (directory / '50-robot-credential.conf').write_bytes(wrong)
            before = self.tree(root)
            with self.assertRaises(release.ReleaseError): self.run_install(installer, 'activate', bundle)
            self.assertEqual(before, self.tree(root))

    def test_local_configuration_must_match_actual_noninteractive_service_account(self):
        adapter = SystemPlatform()
        account = mock.Mock(pw_uid=987, pw_gid=987, pw_shell='/usr/sbin/nologin')
        group = mock.Mock(gr_gid=987)
        with mock.patch('install.pwd.getpwnam', return_value=account), mock.patch('install.grp.getgrnam', return_value=group):
            adapter.check_config('robot', {'operator_uid': 1000, 'gateway_uid': 987})
            with self.assertRaises(release.ReleaseError): adapter.check_config('robot', {'gateway_uid': 986})
            account.pw_shell = '/bin/bash'
            with self.assertRaises(release.ReleaseError): adapter.check_config('robot', {'gateway_uid': 987})

    def test_production_existing_robot_requires_actual_inhibited_reconciled_describe(self):
        value = {'result': 'report', 'report': {'runtime': {'prepared': None, 'recovery_pending': False, 'recovery_ready': True,
                 'kernel': {'state': 0, 'operation_state': 0, 'flags': 1}}}}
        adapter = SystemPlatform()
        with mock.patch('install.command', return_value=release.canonical(value)):
            adapter.check_maintenance('robot', False)
        for key, bad in [('prepared', {}), ('recovery_pending', True), ('recovery_ready', False)]:
            changed = copy.deepcopy(value); changed['report']['runtime'][key] = bad
            with mock.patch('install.command', return_value=release.canonical(changed)):
                with self.assertRaises(release.ReleaseError): adapter.check_maintenance('robot', False)
        missing = copy.deepcopy(value); del missing['report']['runtime']['recovery_ready']
        with mock.patch('install.command', return_value=release.canonical(missing)):
            with self.assertRaises(release.ReleaseError): adapter.check_maintenance('robot', False)
        for key, bad in [('state', 1), ('operation_state', 5), ('flags', 9)]:
            changed = copy.deepcopy(value); changed['report']['runtime']['kernel'][key] = bad
            with mock.patch('install.command', return_value=release.canonical(changed)):
                with self.assertRaises(release.ReleaseError): adapter.check_maintenance('robot', False)

    def test_resume_only_clears_inhibition_after_complete_tuple_and_local_configuration(self):
        spec, bundle = self.bundle()
        root = self.install_root()
        installer = self.installer(root, spec)
        self.run_install(installer, 'activate', bundle)
        with self.assertRaises(release.ReleaseError): self.run_install(installer, 'resume', bundle)
        self.assertTrue(installer.gate.exists())
        (root / 'etc/actryn/robot.json').write_text('{"operator_uid":1000,"gateway_uid":987}')
        result = self.run_install(installer, 'resume', bundle)
        self.assertFalse(installer.gate.exists())
        self.assertFalse(result['authority_issued'])
        self.assertEqual(result['result'], 'ready_for_explicit_service_start')
        self.assertEqual(installer.preflight()['result'], 'preflight_passed')


if __name__ == '__main__': unittest.main()
