# SPDX-License-Identifier: Apache-2.0
"""Transactional role slots. SystemPlatform is the only production platform adapter."""
import fcntl
import itertools
import os
import pwd
import grp
from pathlib import Path
import platform
import stat
import subprocess

from release import (ARCH, BINARIES, KERNEL, MAX_BYTES, MAX_FILES,
                     MAX_MANIFEST, UNITS, ReleaseError, canonical, digest, fields,
                     hash_file, is_hash, load_bundle, module_note, payload_tar, read_file, require,
                     strict_json, sync_dir)

MAX_SLOTS = 3
MAX_INSTALL_BYTES = MAX_SLOTS * (2 * MAX_BYTES + 2 * MAX_MANIFEST + 16384)


def command(args):
    try:
        return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=40, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin'}).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise ReleaseError(f'local maintenance command failed: {args[0]}') from error


class SystemPlatform:
    """Exclusive trusted local maintenance is an explicit operator precondition."""
    def inspect_host(self, manifest):
        role, target = manifest['role'], manifest['target']
        require(os.geteuid() == 0, 'local root maintenance required')
        require(read_file('/etc/debian_version', 128).strip() == b'13.7', 'Debian version mismatch')
        require(platform.machine() == ('aarch64' if role == 'robot' else 'x86_64')
                and platform.release() == target['kernel_release'], 'host architecture/kernel mismatch')
        for item, path in [('kernel_image_sha256', f'/boot/vmlinuz-{KERNEL[role]}'),
                           ('kernel_config_sha256', f'/boot/config-{KERNEL[role]}')]:
            require(digest(read_file(path)) == target[item], 'installed kernel artifact mismatch')
        for package, version in target['packages'].items():
            actual = command(['/usr/bin/dpkg-query', '-W', '-f=${Version}', package]).decode()
            require(actual == version, f'package mismatch: {package}')
        if role == 'robot':
            require(read_file('/proc/device-tree/compatible', 4096).startswith(b'linux,dummy-virt\0'), 'non-actuating QEMU target required')
            require(command(['/usr/bin/systemd-detect-virt']).strip() == b'qemu', 'QEMU virtualization required')
        self.role = role

    def inactive(self, unit):
        value = command(['/usr/bin/systemctl', 'show', '--value', '-p', 'ActiveState', unit + '.service']).strip()
        return value in (b'inactive', b'failed')

    def check_maintenance(self, role, fresh, recorded=False):
        if recorded and all(self.inactive(u) for u in UNITS[role]):
            return
        if role == 'server':
            require(all(self.inactive(u) for u in UNITS[role]), 'stop server services before maintenance')
            # No stopped service may leave a running/prepared task behind. This
            # queries the dedicated namespace; missing containerd is not success.
            tasks = command(['/usr/bin/ctr', '--namespace', 'actryn', 'tasks', 'list', '--quiet'])
            require(not tasks.strip(), 'Actryn container tasks remain')
        elif fresh:
            require(all(self.inactive(u) for u in UNITS[role])
                    and not Path('/sys/module/actryn_authority').exists(),
                    'fresh robot requires inactive services and absent authority module')
        else:
            description = strict_json(command(['/usr/bin/actryn', 'robot', 'describe']))
            runtime = description.get('report', {}).get('runtime', {})
            kernel = runtime.get('kernel', {})
            require(description.get('result') == 'report' and runtime.get('prepared', 'missing') is None
                    and kernel.get('state') == 0 and kernel.get('operation_state') == 0
                    and kernel.get('flags') == 1 and not runtime.get('recovery_pending', True)
                    and runtime.get('recovery_ready') is True,
                    'explicit inhibited reconciled recovered robot required')

    def stop(self, role):
        command(['/usr/bin/systemctl', 'daemon-reload'])
        loaded = []
        for unit in reversed(UNITS[role]):
            state = command(['/usr/bin/systemctl', 'show', '--value', '-p', 'LoadState', unit + '.service']).strip()
            if state == b'not-found':
                require(self.inactive(unit), 'absent unit unexpectedly active')
            else:
                require(state in (b'loaded', b'masked'), 'ambiguous service load state')
                loaded.append(unit + '.service')
        if loaded:
            command(['/usr/bin/systemctl', 'stop', *loaded])
        require(all(self.inactive(u) for u in UNITS[role]), 'services did not stop')

    def check_config(self, role, config):
        name = 'actryn-server' if role == 'server' else 'actryn-gateway'
        try:
            account, group = pwd.getpwnam(name), grp.getgrnam(name)
        except KeyError as error:
            raise ReleaseError('apply and verify pinned sysusers configuration first') from error
        require(account.pw_uid != 0 and account.pw_gid == group.gr_gid
                and account.pw_shell == '/usr/sbin/nologin'
                and account.pw_uid == config['server_uid' if role == 'server' else 'gateway_uid'],
                'local configuration differs from noninteractive service identity')
        if role == 'server':
            # Reuse the daemon's actual approval/configuration validator without
            # opening its database, listeners, service lock or dispatch routes.
            report = strict_json(command(['/usr/bin/actryn-serverd', '--check-config']))
            fields(report, ('result', 'artifact_count', 'authority_issued'), 'daemon configuration report')
            require(report['result'] == 'configuration_valid' and report['authority_issued'] is False
                    and type(report['artifact_count']) is int and 1 <= report['artifact_count'] <= 8,
                    'installed daemon configuration check failed')

    def check_resume(self, role):
        if role == 'robot':
            require(not Path('/sys/module/actryn_authority').exists(),
                    'unload old authority module after trusted quiescence; then resume and load signed slot module explicitly')

    def check_start(self, manifest, slot):
        if manifest['role'] == 'robot':
            note = read_file('/sys/module/actryn_authority/notes/.note.gnu.build-id', 80)
            expected = module_note(read_file(slot / 'payload/module/actryn_authority.ko'))
            require(note == expected, 'loaded authority module build does not match installed signed tuple')

    def reload(self):
        command(['/usr/bin/systemctl', 'daemon-reload'])


class Installer:
    """A root directory is injectable only in the Python test API, never the CLI.

    No callback can grant/rearm/dispatch. Fault injection runs after durable
    boundaries and models process interruption, not arbitrary storage guarantees.
    """
    def __init__(self, root, platform_adapter, role, fault=None):
        require(role in ARCH, 'role required')
        self.root, self.platform, self.role = Path(root), platform_adapter, role
        self.fault = fault or (lambda _: None)
        self.mutation_started = False
        self.base = self.root / 'opt/actryn' / role
        self.state = self.root / 'var/lib/actryn-install' / role
        self.slots = self.base / 'releases'
        self.gate = self.state / 'INHIBITED'

    def checkpoint(self, name):
        self.fault(name)

    def protected(self, path, allow_missing=False):
        require(path.is_relative_to(self.root), 'installation path escaped root')
        current = self.root
        paths = [self.root]
        for part in path.relative_to(self.root).parts:
            current = current / part
            paths.append(current)
        for item in paths:
            try:
                m = item.lstat()
            except FileNotFoundError:
                require(allow_missing, 'installation path missing')
                return
            require(not stat.S_ISLNK(m.st_mode) and m.st_uid == os.geteuid()
                    and m.st_mode & 0o022 == 0, 'untrusted installation ancestor')

    def mkdir(self, path):
        self.protected(path, True)
        if path.exists():
            require(path.is_dir(), 'installation directory type')
            return
        self.mkdir(path.parent)
        # Apply only to a new directory; preserve all existing state/config modes.
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700 if path.is_relative_to(self.state) else 0o755, follow_symlinks=False)
        sync_dir(path)
        sync_dir(path.parent)

    def write_new(self, path, data, mode=0o644):
        self.mkdir(path.parent)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), 0o600 if path.is_relative_to(self.state) else mode)
            os.fsync(stream.fileno())
        sync_dir(path.parent)

    def replace(self, path, data):
        pending = path.with_name(path.name + '.pending')
        if pending.exists():
            self.protected(pending)
            require(pending.is_file() and pending.stat().st_nlink == 1, 'pending state type')
            pending.unlink()
        self.write_new(pending, data)
        os.replace(pending, path)
        sync_dir(path.parent)

    def current(self):
        path = self.base / 'current'
        try:
            target = os.readlink(path)
        except FileNotFoundError:
            return None
        parts = target.split('/')
        require(len(parts) == 3 and parts[0] == 'releases' and is_hash(parts[1])
                and parts[2] == 'payload', 'invalid active release pointer')
        return parts[1]

    def bindings(self, manifest):
        result = {}
        prefix = f'/opt/actryn/{self.role}/current'
        for name in BINARIES[self.role]:
            result[f'usr/bin/{name}'] = prefix + f'/bin/{name}'
        for name in UNITS[self.role]:
            result[f'usr/lib/systemd/system/{name}.service'] = prefix + f'/units/{name}.service'
        result[f'usr/lib/sysusers.d/actryn-{self.role}.conf'] = prefix + f'/sysusers/{self.role}.conf'
        if self.role == 'server':
            result['usr/lib/tmpfiles.d/actryn-server.conf'] = prefix + '/tmpfiles/server.conf'
            result['usr/lib/actryn/observer.bpf.o'] = prefix + '/lib/observer.bpf.o'
        else:
            result[f'usr/lib/modules/{KERNEL[self.role]}/extra/actryn_authority.ko'] = prefix + '/module/actryn_authority.ko'
        return result

    def gate_bytes(self):
        return (f'[Unit]\nConditionPathExists=!/var/lib/actryn-install/{self.role}/INHIBITED\n'
                f'[Service]\nExecStartPre=+/usr/bin/python3 -B -E -s /opt/actryn/{self.role}/current/tools/release.py preflight --role {self.role}\n').encode()

    def validate_paths(self, manifest):
        for target, link in self.bindings(manifest).items():
            path = self.root / target
            self.protected(path.parent, True)
            if path.is_symlink():
                require(os.readlink(path) == link, 'managed link conflict')
            else:
                require(not path.exists(), 'existing unmanaged file conflict')
        for unit in UNITS[self.role]:
            # An untracked full override defeats the pinned unit identity.
            override = self.root / f'etc/systemd/system/{unit}.service'
            require(not override.exists() and not override.is_symlink(), 'unmanaged service override')
            directory = self.root / f'etc/systemd/system/{unit}.service.d'
            self.protected(directory, True)
            if directory.exists():
                allowed = {'90-actryn-install.conf': self.gate_bytes()}
                if unit == 'actryn-serverd':
                    allowed['50-openai-credential.conf'] = (b'[Service]\n'
                        b'LoadCredential=openai-api-key:/etc/actryn/credentials/openai-api-key\n')
                    allowed['50-robot-credential.conf'] = (b'[Service]\n'
                        b'LoadCredential=robot-client-key:/etc/actryn/credentials/robot-client-key\n')
                names = [p.name for p in itertools.islice(directory.iterdir(), len(allowed) + 1)]
                require(set(names) <= set(allowed), 'unmanaged service drop-in')
                for name in names:
                    self.protected(directory / name)
                    require(read_file(directory / name, 4096) == allowed[name], 'service drop-in conflict')
        for path in (self.base, self.state, self.slots):
            self.protected(path, True)
        for name in ('INHIBITED', 'install.lock', 'maintenance.json', 'journal.json', 'trust.json'):
            path = self.state / name
            if path.exists() or path.is_symlink():
                self.protected(path)
                require(path.is_file() and path.stat().st_nlink == 1, 'invalid installer state')

    def capacity(self, incoming=0):
        slots, total = 0, 0
        if self.slots.exists():
            for slot in self.slots.iterdir():
                require(slot.is_dir() and not slot.is_symlink()
                        and (is_hash(slot.name) or slot.name.startswith('.staging-') and is_hash(slot.name[9:])), 'unexpected release slot')
                slots += 1
                require(slots <= MAX_SLOTS, 'release slot capacity')
                files = 0
                for parent, dirs, names in os.walk(slot, followlinks=False):
                    require(len(dirs) <= MAX_FILES, 'release directory capacity')
                    for name in dirs + names:
                        m = (Path(parent) / name).lstat()
                        require(not stat.S_ISLNK(m.st_mode) and (stat.S_ISDIR(m.st_mode)
                                or stat.S_ISREG(m.st_mode) and m.st_nlink == 1), 'invalid release storage')
                        files += 1
                        require(files <= MAX_FILES * 4, 'release storage file capacity')
                        if stat.S_ISREG(m.st_mode):
                            total += m.st_size
        require(slots + bool(incoming) <= MAX_SLOTS and total + incoming <= MAX_INSTALL_BYTES, 'release retention capacity; preserve old slots explicitly')

    def establish_gate(self, previous):
        self.mkdir(self.state)
        if not self.gate.exists():
            self.write_new(self.gate, b'Explicit local maintenance; no automatic restart or authority.\n')
        else:
            self.protected(self.gate)
        self.checkpoint('gate')
        self.replace(self.state / 'maintenance.json', canonical({'format': 1, 'role': self.role,
                     'checked_current': previous, 'inhibited_reconciled': True}))
        self.checkpoint('maintenance-record')
        for unit in UNITS[self.role]:
            path = self.root / f'etc/systemd/system/{unit}.service.d/90-actryn-install.conf'
            if not path.exists():
                self.write_new(path, self.gate_bytes())
        self.platform.stop(self.role)
        self.checkpoint('stopped')

    def journal(self, phase, target, previous):
        self.replace(self.state / 'journal.json', canonical({'format': 1, 'role': self.role,
                     'phase': phase, 'target': target, 'previous': previous}))
        self.checkpoint('journal-' + phase)

    def install_links(self, manifest):
        for name, target in self.bindings(manifest).items():
            path = self.root / name
            self.mkdir(path.parent)
            if not path.is_symlink():
                path.symlink_to(target)
                sync_dir(path.parent)
            self.checkpoint('link-' + name)

    def stage(self, manifest, contents, verified):
        identity = verified['manifest_sha256']
        slot = self.slots / identity
        if slot.exists():
            self.verify_slot(slot, verified)
            return slot
        pending = self.slots / ('.staging-' + identity)
        require(not pending.exists(), 'unfinished staging remains; use explicit recover')
        self.mkdir(self.slots)
        self.mkdir(pending)
        for name, data in [('manifest.json', canonical(manifest)),
                           ('payload.tar', payload_tar(manifest['files'], contents)),
                           ('signature.ed25519', bytes.fromhex(verified['signature_hex'])),
                           ('signer.pem', verified['public_key_pem'].encode('ascii'))]:
            self.write_new(pending / name, data)
            self.checkpoint('staged-' + name)
        for entry in manifest['files']:
            self.write_new(pending / 'payload' / entry['path'], contents[entry['path']], entry['mode'])
            self.checkpoint('payload-' + entry['path'])
        self.verify_slot(pending, verified)
        sync_dir(pending)
        os.rename(pending, slot)
        sync_dir(self.slots)
        self.checkpoint('slot-published')
        return slot

    def verify_slot(self, slot, verified):
        manifest, _, info = load_bundle(slot, slot / 'signer.pem', verified['key_fingerprint'], retain=False)
        require(info['manifest_sha256'] == verified['manifest_sha256'], 'retained slot identity changed')
        expected = {'manifest.json', 'payload.tar', 'signature.ed25519', 'signer.pem'}
        expected |= {'payload/' + entry['path'] for entry in manifest['files']}
        actual = set()
        for parent, dirs, names in os.walk(slot, followlinks=False):
            for name in dirs:
                self.protected(Path(parent) / name)
            for name in names:
                path = Path(parent) / name
                self.protected(path)
                actual.add(path.relative_to(slot).as_posix())
        require(actual == expected, 'retained slot file set')
        for entry in manifest['files']:
            path = slot / 'payload' / entry['path']
            require(hash_file(path, entry['size']) == entry['sha256']
                    and stat.S_IMODE(path.stat().st_mode) == entry['mode'], 'retained installed payload changed')
        return manifest

    def switch(self, manifest, verified, previous):
        identity = verified['manifest_sha256']
        slot = self.slots / identity
        self.verify_slot(slot, verified)
        self.install_links(manifest)
        self.journal('switching', identity, previous)
        pending = self.base / 'current.pending'
        if pending.is_symlink():
            require(os.readlink(pending) == 'releases/' + identity + '/payload', 'unexpected pending pointer')
            pending.unlink()
        require(not pending.exists(), 'pending pointer conflict')
        # current points to the complete payload, while the signed bundle remains
        # retained beside it for revalidation and rollback.
        pending.symlink_to('releases/' + identity + '/payload')
        os.replace(pending, self.base / 'current')
        sync_dir(self.base)
        self.checkpoint('pointer')
        self.journal('installed', identity, previous)
        self.platform.reload()

    def configuration(self):
        path = self.root / f'etc/actryn/{self.role}.json'
        require(path.is_file(), 'local configuration required before resume/start')
        self.protected(path)
        config = strict_json(read_file(path, 65536))
        if self.role == 'robot':
            fields(config, ('operator_uid', 'gateway_uid'), 'local robot configuration')
            require(type(config['operator_uid']) is int and 0 <= config['operator_uid'] <= 2**32-1
                    and type(config['gateway_uid']) is int and 0 < config['gateway_uid'] <= 2**32-1
                    and config['operator_uid'] != config['gateway_uid'], 'local robot identity binding')
        else:
            fields(config, ('server_uid', 'operator_uid', 'io_device', 'artifacts'), 'local server configuration')
            require(type(config['server_uid']) is int and 0 < config['server_uid'] <= 2**32-1
                    and type(config['operator_uid']) is int and 0 <= config['operator_uid'] <= 2**32-1
                    and config['operator_uid'] != config['server_uid']
                    and isinstance(config['artifacts'], dict), 'local server identity binding')
        return config

    def preflight(self):
        self.protected(self.state)
        require(not self.gate.exists(), 'installation still inhibited')
        trust = strict_json(read_file(self.state / 'trust.json', 4096))
        fields(trust, ('format', 'role', 'ed25519_spki_sha256'), 'release trust')
        require(type(trust['format']) is int and trust['format'] == 1 and trust['role'] == self.role
                and is_hash(trust['ed25519_spki_sha256']), 'release trust binding')
        identity = self.current()
        require(identity is not None, 'installed tuple absent')
        slot = self.slots / identity
        manifest, _, verified = load_bundle(slot, slot / 'signer.pem', trust['ed25519_spki_sha256'], retain=False)
        require(manifest['role'] == self.role and verified['promotable']
                and verified['manifest_sha256'] == identity, 'installed release identity')
        verified['key_fingerprint'] = trust['ed25519_spki_sha256']
        self.platform.inspect_host(manifest)
        self.validate_paths(manifest)
        self.capacity()
        self.verify_slot(slot, verified)
        self.platform.check_config(self.role, self.configuration())
        self.platform.check_start(manifest, slot)
        return {'result': 'preflight_passed', 'role': self.role,
                'manifest_sha256': identity, 'authority_issued': False}

    def run(self, action, bundle, public_key, fingerprint):
        self.mutation_started = False
        require(action in ('stage', 'activate', 'rollback', 'recover', 'resume'), 'install action')
        manifest, contents, verified = load_bundle(bundle, public_key, fingerprint)
        require(manifest['role'] == self.role and verified['promotable'], 'signed qualified matching role required')
        verified['key_fingerprint'] = fingerprint
        # Every package, signature, target and path mismatch is checked before
        # gate creation, service changes, mkdir or lock creation.
        self.platform.inspect_host(manifest)
        self.validate_paths(manifest)
        current = self.current()
        incoming = verified['manifest_sha256']
        self.capacity(0 if (self.slots / incoming).exists() or (self.slots / ('.staging-' + incoming)).exists()
                      else 2 * sum(e['size'] for e in manifest['files']) + MAX_MANIFEST)
        if current is not None:
            old_slot = self.slots / current
            old_manifest, _, old_verified = load_bundle(old_slot, old_slot / 'signer.pem', fingerprint, retain=False)
            require(old_manifest['role'] == self.role
                    and old_manifest['compatibility'] == manifest['compatibility'], 'unsupported installed tuple/downgrade')
            old_verified['key_fingerprint'] = fingerprint
            require(old_verified['manifest_sha256'] == current, 'active pointer identity mismatch')
            self.verify_slot(old_slot, old_verified)
        fresh = current is None
        if action == 'rollback':
            require((self.slots / incoming).is_dir(), 'rollback requires a retained slot')
        if action == 'resume':
            require(current == incoming, 'resume must name installed tuple')
            self.verify_slot(self.slots / incoming, verified)
        recorded = False
        maintenance_path = self.state / 'maintenance.json'
        if self.gate.exists() and maintenance_path.exists():
            record = strict_json(read_file(maintenance_path, 4096))
            fields(record, ('format', 'role', 'checked_current', 'inhibited_reconciled'), 'maintenance record')
            require(type(record['format']) is int and record['format'] == 1 and record['role'] == self.role
                    and record['inhibited_reconciled'] is True
                    and (record['checked_current'] is None or is_hash(record['checked_current'])), 'maintenance record invalid')
            recorded = True
        if action == 'resume':
            self.platform.check_config(self.role, self.configuration())
            self.platform.check_resume(self.role)
        self.platform.check_maintenance(self.role, fresh, recorded)
        self.mutation_started = True
        self.mkdir(self.state)
        lock = os.open(self.state / 'install.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            require(self.current() == current, 'release changed concurrently')
            self.validate_paths(manifest)
            self.capacity(0 if (self.slots / incoming).exists() or (self.slots / ('.staging-' + incoming)).exists()
                          else 2 * sum(e['size'] for e in manifest['files']) + MAX_MANIFEST)
            self.establish_gate(current)
            self.replace(self.state / 'trust.json', canonical({'format': 1, 'role': self.role,
                         'ed25519_spki_sha256': fingerprint}))
            self.checkpoint('trust-record')
            if action == 'resume':
                require(self.gate.exists(), 'inhibitor absent')
                # Clearing the gate never starts services. Local recovery/rearm
                # and fresh grants remain separate operator actions.
                self.gate.unlink()
                sync_dir(self.state)
                self.platform.reload()
                return {'result': 'ready_for_explicit_service_start', 'authority_issued': False}
            self.journal('staging', incoming, current)
            if action == 'recover':
                pending = self.slots / ('.staging-' + incoming)
                if pending.exists():
                    # Reconstruct only the installer-owned incomplete slot, never
                    # mutate state/evidence/configuration or a published slot.
                    import shutil
                    self.protected(pending)
                    shutil.rmtree(pending)
                    sync_dir(self.slots)
            self.stage(manifest, contents, verified)
            self.journal('staged', incoming, current)
            if action != 'stage':
                self.switch(manifest, verified, current)
            return {'result': 'staged' if action == 'stage' else 'installed_inhibited',
                    'role': self.role, 'manifest_sha256': incoming,
                    'previous_manifest_sha256': current, 'authority_issued': False,
                    'automatic_restart': False, 'state_restored': False}
        finally:
            os.close(lock)
