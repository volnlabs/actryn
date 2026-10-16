#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Bounded deterministic software-preview bundles; no downloads or signing keys."""
import argparse
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
# Installed tools are signed immutable payloads, including when invoked without -B.
sys.dont_write_bytecode = True
import tarfile
import tempfile
import tomllib
import zipfile

FORMAT = 'actryn-release-1'
MAX_FILE = 64 * 1024 * 1024
MAX_BYTES = 256 * 1024 * 1024
MAX_MANIFEST = 256 * 1024
MAX_FILES = 64
MAX_ASSET = 16 * 1024 * 1024
ASSETS = {'share/wheels/protobuf-7.36.1-py3-none-any.whl', 'share/agent/offline-oci.tar', 'share/sdk/pyproject.toml'}
KERNEL = {'server': '6.12.111+deb13-amd64', 'robot': '6.12.111+deb13-arm64'}
ARCH = {'server': 'amd64', 'robot': 'arm64'}
MACHINE = {'server': 62, 'robot': 183}
BPF_OBJECT = 'lib/observer.bpf.o'
# Observed ldd dependency closure of the selected Debian production executables.
RUNTIME_PACKAGES = {'server': {'libc6', 'libgcc-s1', 'libelf1t64', 'libzstd1', 'zlib1g'},
                    'robot': {'libc6', 'libgcc-s1'}}
UNITS = {'server': ('actryn-observer', 'actryn-launcher', 'actryn-serverd'),
         'robot': ('actryn-robotd', 'actryn-gatewayd')}
BINARIES = {'server': ('actryn', 'actryn-observer', 'actryn-launcher', 'actryn-serverd', 'controller-fixture'),
            'robot': ('actryn', 'actryn-robotd', 'actryn-gatewayd')}
COMMON = {'tools/release.py', 'tools/install.py', 'share/target/profile.toml', 'share/target/build-inputs.toml',
          'share/licenses/Apache-2.0.txt', 'share/licenses/THIRD-PARTY.txt'}
FILES = {role: COMMON | {f'bin/{name}' for name in BINARIES[role]} |
         {f'units/{name}.service' for name in UNITS[role]} | {f'sysusers/{role}.conf'}
         for role in ARCH}
FILES['server'] |= {BPF_OBJECT, 'share/licenses/GPL-2.0-only.txt', 'share/source/observer.bpf.c', 'tmpfiles/server.conf', 'share/sdk/actryn/__init__.py',
                    'share/sdk/actryn/client.py', 'share/sdk/actryn/robot_v1_pb2.py', 'share/sdk/pyproject.toml',
                    'share/wheels/protobuf-7.36.1-py3-none-any.whl', 'share/agent/offline-oci.tar'}
FILES['robot'] |= {'module/actryn_authority.ko', 'share/target/virt-actryn.dtb',
                   'share/licenses/GPL-2.0-only.txt', 'share/source/kernel.tar'}
COMPATIBILITY = {'rpc': 1, 'uapi': 1, 'wire': 2, 'state_schema': 1,
                 'server_rpc_min': 1, 'server_rpc_max': 1, 'live_actuation': False,
                 'physical_acceptance': False}


class ReleaseError(ValueError):
    pass


def require(test, message):
    if not test:
        raise ReleaseError(message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                       allow_nan=False) + '\n').encode('ascii')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def is_hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def strict_json(data):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ReleaseError('nonfinite JSON')))
    except (ValueError, UnicodeError) as error:
        raise ReleaseError('invalid JSON') from error


def fields(value, names, label):
    require(isinstance(value, dict) and set(value) == set(names), f'{label} fields')


def read_file(path, limit=MAX_FILE, single_link=True):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        m = os.fstat(stream.fileno())
        require(stat.S_ISREG(m.st_mode) and (not single_link or m.st_nlink == 1) and m.st_size <= limit,
                'regular, single-link, bounded input required')
        data = stream.read(limit + 1)
        require(len(data) <= limit and len(data) == m.st_size, 'input size changed')
        return data


def target_valid(role, target):
    fields(target, ('distribution', 'version', 'architecture', 'kernel_release',
                    'kernel_image_sha256', 'kernel_config_sha256', 'image_sha512', 'packages'), 'target')
    require(target['distribution'] == 'debian' and target['version'] == '13.7'
            and target['architecture'] == ARCH[role] and target['kernel_release'] == KERNEL[role], 'unsupported target')
    require(is_hash(target['kernel_image_sha256']) and is_hash(target['kernel_config_sha256']), 'kernel pins required')
    require(isinstance(target['image_sha512'], str) and re.fullmatch('[0-9a-f]{128}', target['image_sha512']), 'image pin required')
    packages = target['packages']
    required = {'systemd', 'openssl', 'python3', f'linux-image-{KERNEL[role]}'} | RUNTIME_PACKAGES[role]
    if role == 'server':
        required |= {'containerd', 'runc', 'python3-venv'}
    require(isinstance(packages, dict) and required <= set(packages) and len(packages) <= 32, 'required package pins')
    for name, version in packages.items():
        require(re.fullmatch('[a-z0-9][a-z0-9+.-]{0,127}', name) and isinstance(version, str)
                and re.fullmatch('[A-Za-z0-9:~+._-]{1,128}', version), 'package identity')
    require(packages[f'linux-image-{KERNEL[role]}'] == '6.12.111-1', 'kernel package mismatch')
    if role == 'server':
        require(packages['containerd'] == '1.7.24~ds1-6+deb13u1'
                and packages['runc'] == '1.1.15+ds1-2+b4', 'runtime package mismatch')


def provenance_valid(value, role):
    fields(value, ('source_revision', 'rust', 'build_inputs_sha256', 'qualification', 'evidence', 'custodian_attestation'), 'provenance')
    require(isinstance(value['source_revision'], str) and re.fullmatch('[0-9a-f]{40}', value['source_revision']), 'source revision pin')
    require(value['rust'] == '1.92.0' and is_hash(value['build_inputs_sha256']), 'build pins')
    require(value['qualification'] in ('incomplete', 'software-preview-qualified'), 'qualification state')
    evidence = value['evidence']
    require(isinstance(evidence, dict) and len(evidence) <= 64, 'evidence bounds')
    require(all(isinstance(name, str) and re.fullmatch('[A-Za-z0-9_.-]{1,64}', name)
                and is_hash(hash_) for name, hash_ in evidence.items()), 'evidence pins')
    if value['qualification'] == 'software-preview-qualified':
        require('qualification-bundle' in evidence, 'named qualification bundle absent')
        attestation = value['custodian_attestation']
        fields(attestation, ('role', 'scope', 'qualification_bundle_sha256'), 'custodian attestation')
        require(attestation == {'role': role,
                'scope': 'server-independent-D2' if role == 'server' else 'robot-software-preview',
                'qualification_bundle_sha256': evidence['qualification-bundle']},
                'role-scoped qualification attestation mismatch')
    else:
        require(value['custodian_attestation'] is None, 'incomplete qualification cannot carry approval')


def elf_section(data, wanted):
    require(len(data) >= 64 and data[:6] == b'\x7fELF\x02\x01', 'ELF section header')
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count, strings = struct.unpack_from('<HHH', data, 58)
    require(size == 64 and 1 <= count <= 4096 and strings < count
            and offset + count * size <= len(data), 'ELF section table')
    table = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * size) for i in range(count)]
    names = table[strings]
    require(names[4] + names[5] <= len(data), 'ELF string table')
    names = data[names[4]:names[4] + names[5]]
    for entry in table:
        require(entry[0] < len(names), 'ELF section name')
        end = names.find(b'\0', entry[0])
        require(end >= 0, 'ELF section name termination')
        if names[entry[0]:end] == wanted.encode('ascii'):
            require(entry[4] + entry[5] <= len(data), 'ELF section bounds')
            return data[entry[4]:entry[4] + entry[5]]
    raise ReleaseError('required ELF section absent: ' + wanted)


def module_note(data):
    note = elf_section(data, '.note.gnu.build-id')
    require(36 <= len(note) <= 80 and struct.unpack_from('<I', note)[0] == 4
            and 20 <= struct.unpack_from('<I', note, 4)[0] <= 64
            and len(note) == 16 + ((struct.unpack_from('<I', note, 4)[0] + 3) // 4) * 4
            and struct.unpack_from('<I', note, 8)[0] == 3 and note[12:16] == b'GNU\0',
            'GNU module build identity required')
    return note


def validate_binary(role, name, data):
    if not (name.startswith('bin/') or name.startswith('module/') or name == BPF_OBJECT):
        return
    require(len(data) >= 64 and data[:6] == b'\x7fELF\x02\x01', 'ELF64 little-endian artifact required')
    kind, machine = struct.unpack_from('<HH', data, 16)
    if name == BPF_OBJECT:
        require(role == 'server' and machine == 247 and kind == 1, 'BPF ELF architecture/kind mismatch')
        return
    require(machine == MACHINE[role], 'ELF architecture mismatch')
    if name.startswith('module/'):
        require(kind == 1, 'module ELF kind')
        info = elf_section(data, '.modinfo').split(b'\0')
        require(any(part.startswith(b'vermagic=' + KERNEL[role].encode() + b' ') for part in info)
                and b'license=GPL' in info, 'module kernel/license mismatch')
        module_note(data)
    else:
        require(kind in (2, 3), 'executable ELF required')


def small_tar(data, maximum):
    require(len(data) <= MAX_ASSET, 'offline archive capacity')
    result = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
            for index, member in enumerate(archive):
                require(index < maximum and member.type in (tarfile.REGTYPE, tarfile.AREGTYPE) and not member.pax_headers
                        and member.name not in result and 0 <= member.size <= MAX_ASSET,
                        'offline archive metadata/links/count')
                require(member.name in ('oci-layout', 'index.json', 'bin/agent', 'etc/actryn/input.json', 'etc/actryn/input.schema.json')
                        or re.fullmatch('blobs/sha256/[0-9a-f]{64}', member.name), 'offline archive path')
                require(member.uid == member.gid == 0 and member.mode & 0o7000 == 0
                        and not member.linkname, 'offline archive ownership/mode')
                require(sum(map(len, result.values())) + member.size <= MAX_ASSET, 'offline archive bytes')
                result[member.name] = archive.extractfile(member).read(MAX_ASSET + 1)
    except (tarfile.TarError, OSError) as error:
        raise ReleaseError('invalid offline OCI archive') from error
    return result


def validate_asset(name, data):
    if name not in ASSETS:
        return
    require(len(data) <= MAX_ASSET, 'offline asset capacity')
    if name.endswith('pyproject.toml'):
        try:
            project = tomllib.loads(data.decode())['project']
            require(project['name'] == 'actryn-sdk' and project['version'] == '0.0.1'
                    and project['requires-python'] == '>=3.11'
                    and project['dependencies'] == ['protobuf==7.36.1'], 'SDK metadata/version')
        except (ValueError, KeyError, UnicodeError) as error:
            raise ReleaseError('invalid SDK metadata') from error
    elif name.endswith('.whl'):
        # Bound central-directory work before zipfile allocates its member list.
        require(len(data) >= 22 and data[-22:-18] == b'PK\x05\x06', 'wheel EOCD/comment')
        _, disk, central_disk, local_count, count, size, offset, comment = struct.unpack('<4s4H2IH', data[-22:])
        require(disk == central_disk == comment == 0 and local_count == count
                and 1 <= count <= 512 and offset + size == len(data) - 22, 'wheel directory/ZIP64 bounds')
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = archive.infolist()
                require(len(infos) == count and sum(i.file_size for i in infos) <= 32 * 1024 * 1024, 'wheel file/byte capacity')
                seen = set()
                for info in infos:
                    path = info.filename
                    require(path == info.orig_filename and path not in seen
                            and re.fullmatch('[A-Za-z0-9_./-]+', path)
                            and not path.startswith('/') and '..' not in path.split('/')
                            and path.startswith(('google/', 'protobuf-7.36.1.dist-info/'))
                            and not info.flag_bits & 1 and info.file_size <= 8 * 1024 * 1024
                            and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR),
                            'wheel member path/link/metadata')
                    seen.add(path)
                    require(not path.endswith(('.so', '.pyd', '.dll')), 'universal wheel contains native extension')
                prefix = 'protobuf-7.36.1.dist-info/'
                require({prefix + 'METADATA', prefix + 'WHEEL', prefix + 'RECORD'} <= seen, 'wheel metadata absent')
                meta = BytesParser().parsebytes(archive.read(prefix + 'METADATA'))
                wheel = BytesParser().parsebytes(archive.read(prefix + 'WHEEL'))
                require(meta.get_all('Name') == ['protobuf'] and meta.get_all('Version') == ['7.36.1']
                        and meta.get_all('Requires-Python') == ['>=3.10'] and not meta.get_all('Requires-Dist')
                        and wheel.get_all('Wheel-Version') == ['1.0'] and wheel.get_all('Root-Is-Purelib') == ['true']
                        and wheel.get_all('Tag') == ['py3-none-any'], 'wheel version/platform/python/dependencies')
        except (zipfile.BadZipFile, KeyError, OSError) as error:
            raise ReleaseError('invalid universal protobuf wheel') from error
    else:
        files = small_tar(data, 5)
        require(strict_json(files.get('oci-layout', b'null')) == {'imageLayoutVersion': '1.0.0'}, 'OCI layout version')
        index = strict_json(files.get('index.json', b'null'))
        fields(index, ('schemaVersion', 'mediaType', 'manifests'), 'OCI index')
        require(index['schemaVersion'] == 2 and index['mediaType'] == 'application/vnd.oci.image.index.v1+json'
                and isinstance(index['manifests'], list) and len(index['manifests']) == 1, 'OCI index version/platform')
        def blob(descriptor, media):
            fields(descriptor, ('mediaType', 'digest', 'size'), 'OCI descriptor')
            hash_ = descriptor['digest']
            require(descriptor['mediaType'] == media and isinstance(hash_, str)
                    and hash_.startswith('sha256:') and is_hash(hash_[7:]), 'OCI blob identity')
            value = files.get('blobs/sha256/' + hash_[7:])
            require(value is not None and type(descriptor['size']) is int and descriptor['size'] == len(value)
                    and digest(value) == hash_[7:], 'OCI blob size/SHA256')
            return value
        descriptor = index['manifests'][0]
        manifest = strict_json(blob(descriptor, 'application/vnd.oci.image.manifest.v1+json'))
        fields(manifest, ('schemaVersion', 'mediaType', 'config', 'layers'), 'OCI manifest')
        require(manifest['schemaVersion'] == 2 and manifest['mediaType'] == 'application/vnd.oci.image.manifest.v1+json'
                and isinstance(manifest['layers'], list) and len(manifest['layers']) == 1, 'OCI manifest version/layers')
        config = strict_json(blob(manifest['config'], 'application/vnd.oci.image.config.v1+json'))
        layer = manifest['layers'][0]
        layer_data = blob(layer, 'application/vnd.oci.image.layer.v1.tar')
        expected_config = {'architecture': 'amd64', 'os': 'linux', 'config': {'Entrypoint': ['/bin/agent'],
            'User': '65532:65532', 'WorkingDir': '/tmp', 'Labels': {'org.actryn.profile': 'offline-preview-v1'}},
            'rootfs': {'type': 'layers', 'diff_ids': [layer['digest']]}}
        require(config == expected_config and len(files) == 5, 'offline OCI execution metadata/profile')
        retained = small_tar(layer_data, 3)
        require(set(retained) == {'bin/agent', 'etc/actryn/input.json', 'etc/actryn/input.schema.json'}
                and len(retained['bin/agent']) <= 8 * 1024 * 1024
                and len(retained['etc/actryn/input.json']) <= 4096
                and len(retained['etc/actryn/input.schema.json']) <= 8192, 'offline OCI layer files')
        agent = retained['bin/agent']
        validate_binary('server', 'bin/agent', agent)
        offset = struct.unpack_from('<Q', agent, 32)[0]
        size, count = struct.unpack_from('<HH', agent, 54)
        require(size == 56 and 1 <= count <= 128 and offset + size * count <= len(agent), 'offline agent program headers')
        kinds = [struct.unpack_from('<I', agent, offset + i * size)[0] for i in range(count)]
        require(1 in kinds and 3 not in kinds, 'offline agent must be static')
        require(isinstance(strict_json(retained['etc/actryn/input.json']), dict)
                and strict_json(retained['etc/actryn/input.json']).get('mode', 'offline') == 'offline'
                and isinstance(strict_json(retained['etc/actryn/input.schema.json']), dict), 'offline OCI JSON assets')


def mode_for(name):
    return 0o755 if name.startswith('bin/') else 0o644


def license_for(name):
    if name.startswith('module/') or name in ('share/source/kernel.tar', 'share/source/observer.bpf.c', 'share/licenses/GPL-2.0-only.txt', BPF_OBJECT):
        return 'GPL-2.0-only'
    return 'SEE-NOTICES' if name.endswith('THIRD-PARTY.txt') or name.startswith('share/wheels/') else 'Apache-2.0'


def validate_manifest(manifest):
    fields(manifest, ('format', 'role', 'version', 'target', 'compatibility', 'provenance', 'files'), 'manifest')
    role = manifest['role']
    require(manifest['format'] == FORMAT and isinstance(role, str) and role in ARCH and manifest['version'] == '0.0.1', 'release format/role/version')
    require(canonical(manifest['compatibility']) == canonical(COMPATIBILITY), 'unsupported compatibility tuple')
    target_valid(role, manifest['target'])
    provenance_valid(manifest['provenance'], manifest['role'])
    entries = manifest['files']
    require(isinstance(entries, list) and len(entries) <= MAX_FILES, 'file count')
    names, total = [], 0
    for entry in entries:
        fields(entry, ('path', 'size', 'sha256', 'mode', 'license'), 'file')
        name = entry['path']
        require(isinstance(name, str) and name in FILES[role], 'forbidden role payload path')
        require(type(entry['size']) is int and 0 <= entry['size'] <= MAX_FILE and is_hash(entry['sha256']), 'file size/hash')
        require(type(entry['mode']) is int and entry['mode'] == mode_for(name)
                and entry['license'] == license_for(name), 'file mode/license')
        total += entry['size']
        names.append(name)
    require(names == sorted(FILES[role]) and total <= MAX_BYTES, 'incomplete/duplicate/oversized role tuple')
    return role


def payload_tar(entries, contents):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for entry in entries:
            info = tarfile.TarInfo(entry['path'])
            info.size, info.mode = entry['size'], entry['mode']
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ''
            archive.addfile(info, io.BytesIO(contents[entry['path']]))
    return stream.getvalue()


def build(spec, destination):
    fields(spec, ('role', 'version', 'target', 'compatibility', 'provenance', 'files'), 'build spec')
    role = spec['role']
    require(isinstance(role, str) and role in FILES and isinstance(spec['files'], dict) and set(spec['files']) == FILES[role], 'complete role inputs required')
    contents, entries, total = {}, [], 0
    for name in sorted(spec['files']):
        source = spec['files'][name]
        fields(source, ('source', 'sha256'), 'input')
        require(isinstance(source['source'], str) and 0 < len(source['source']) <= 4096
                and '\0' not in source['source'], 'input path')
        data = read_file(source['source'], single_link=False)
        require(is_hash(source['sha256']) and digest(data) == source['sha256'], 'input SHA256 mismatch')
        total += len(data)
        require(total <= MAX_BYTES, 'payload capacity')
        validate_binary(role, name, data)
        validate_asset(name, data)
        if name.endswith('.dtb'):
            require(data.startswith(b'\xd0\x0d\xfe\xed'), 'flattened device tree required')
        contents[name] = data
        entries.append({'path': name, 'size': len(data), 'sha256': digest(data),
                        'mode': mode_for(name), 'license': license_for(name)})
    manifest = {key: spec[key] for key in ('role', 'version', 'target', 'compatibility', 'provenance')}
    manifest.update(format=FORMAT, files=entries)
    validate_manifest(manifest)
    require(manifest['provenance']['build_inputs_sha256'] == digest(contents['share/target/build-inputs.toml']), 'build input file pin mismatch')
    destination = Path(destination)
    destination.mkdir(mode=0o700)
    for name, data in [('manifest.json', canonical(manifest)), ('payload.tar', payload_tar(entries, contents))]:
        with (destination / name).open('xb') as stream:
            os.fchmod(stream.fileno(), 0o644)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    sync_dir(destination)
    sync_dir(destination.parent)
    return {'manifest_sha256': digest(canonical(manifest)), 'signature_verified': False,
            'promotable': False, 'status': 'unsigned_candidate'}


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def openssl(arguments):
    try:
        return subprocess.run(['/usr/bin/openssl', *arguments], check=True, timeout=5,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'OPENSSL_CONF': '/dev/null'}).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise ReleaseError('OpenSSL signature/key verification failed') from error


def tar_header(entry):
    info = tarfile.TarInfo(entry['path'])
    info.size, info.mode = entry['size'], entry['mode']
    info.uid = info.gid = info.mtime = 0
    info.uname = info.gname = ''
    return info.tobuf(format=tarfile.USTAR_FORMAT)


def hash_file(path, size):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    result = hashlib.sha256()
    with os.fdopen(fd, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
                and metadata.st_size == size, 'installed payload type/size')
        remaining = size
        while remaining:
            data = stream.read(min(65536, remaining))
            require(bool(data), 'installed payload truncated')
            remaining -= len(data)
            result.update(data)
        require(stream.read(1) == b'', 'installed payload grew')
    return result.hexdigest()


def load_bundle(root, public_key=None, trusted_fingerprint=None, retain=True):
    root = Path(root)
    manifest_bytes = read_file(root / 'manifest.json', MAX_MANIFEST)
    manifest = strict_json(manifest_bytes)
    role = validate_manifest(manifest)
    require(canonical(manifest) == manifest_bytes, 'noncanonical manifest')
    contents = {}
    fd = os.open(root / 'payload.tar', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1
                and metadata.st_size <= MAX_BYTES + MAX_FILES * 1024 + 10240, 'archive type/size')
        consumed = 0
        for entry in manifest['files']:
            name, size = entry['path'], entry['size']
            # Exact headers reject links, path tricks, unknown metadata, order,
            # duplicate members and extended/PAX headers before reading bytes.
            require(stream.read(512) == tar_header(entry), 'noncanonical/unsupported archive header')
            consumed += 512
            remaining, hash_, blocks, prefix = size, hashlib.sha256(), [], b''
            while remaining:
                data = stream.read(min(65536, remaining))
                require(bool(data), 'truncated archive payload')
                remaining -= len(data)
                hash_.update(data)
                if len(prefix) < 64:
                    prefix += data[:64 - len(prefix)]
                if retain or name.startswith('module/') or name in ASSETS:
                    blocks.append(data)
            require(hash_.hexdigest() == entry['sha256'], 'payload SHA256 mismatch')
            collected = b''.join(blocks) if blocks else b''
            validate_binary(role, name, collected if name.startswith('module/') or retain else prefix)
            validate_asset(name, collected)
            if name.endswith('.dtb'):
                require(prefix.startswith(b'\xd0\x0d\xfe\xed'), 'flattened device tree required')
            if retain:
                contents[name] = collected
            padding = (-size) % 512
            require(stream.read(padding) == b'\0' * padding, 'archive padding')
            consumed += size + padding
        tail = ((consumed + 1024 + 10239) // 10240) * 10240 - consumed
        require(stream.read(tail) == b'\0' * tail and stream.read(1) == b'', 'archive trailer/trailing bytes')
    build_input = next(e for e in manifest['files'] if e['path'] == 'share/target/build-inputs.toml')
    require(manifest['provenance']['build_inputs_sha256'] == build_input['sha256'], 'build input pin mismatch')
    verified = False
    if public_key is not None:
        require(is_hash(trusted_fingerprint), 'external trusted public-key fingerprint required')
        key_bytes = read_file(public_key, 8192)
        signature = read_file(root / 'signature.ed25519', 64)
        require(len(signature) == 64, 'Ed25519 signature length')
        # Verify private snapshots, never attacker-replaceable source paths.
        with tempfile.TemporaryDirectory(prefix='actryn-verify-') as temporary:
            snapshot = Path(temporary)
            (snapshot / 'key.pem').write_bytes(key_bytes)
            (snapshot / 'manifest.json').write_bytes(manifest_bytes)
            (snapshot / 'signature').write_bytes(signature)
            der = openssl(['pkey', '-pubin', '-in', str(snapshot / 'key.pem'), '-outform', 'DER'])
            require(len(der) == 44 and der[:12] == bytes.fromhex('302a300506032b6570032100')
                    and digest(der) == trusted_fingerprint, 'untrusted Ed25519 key')
            openssl(['pkeyutl', '-verify', '-pubin', '-inkey', str(snapshot / 'key.pem'), '-rawin',
                     '-in', str(snapshot / 'manifest.json'), '-sigfile', str(snapshot / 'signature')])
        verified = True
    return manifest, contents, {'manifest_sha256': digest(manifest_bytes), 'signature_verified': verified,
        'promotable': verified and manifest['provenance']['qualification'] == 'software-preview-qualified',
        'physical_acceptance': False,
        **({'public_key_pem': key_bytes.decode('ascii'), 'signature_hex': signature.hex()} if verified else {})}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    builder = commands.add_parser('build')
    builder.add_argument('--spec', required=True, type=Path)
    builder.add_argument('--out', required=True, type=Path)
    for name in ('inspect', 'stage', 'activate', 'rollback', 'recover', 'resume'):
        command = commands.add_parser(name)
        command.add_argument('--bundle', required=True, type=Path)
        command.add_argument('--public-key', type=Path, required=name != 'inspect')
        command.add_argument('--key-sha256', required=name != 'inspect')
        if name != 'inspect':
            command.add_argument('--role', choices=ARCH, required=True)
    preflight = commands.add_parser('preflight')
    preflight.add_argument('--role', choices=ARCH, required=True)
    args = parser.parse_args()
    if args.command == 'build':
        result = build(strict_json(read_file(args.spec, MAX_MANIFEST)), args.out)
    elif args.command == 'preflight':
        from install import Installer, SystemPlatform
        result = Installer(Path('/'), SystemPlatform(), args.role).preflight()
    elif args.command == 'inspect':
        _, _, result = load_bundle(args.bundle, args.public_key, args.key_sha256)
    else:
        from install import Installer, SystemPlatform
        installer = Installer(Path('/'), SystemPlatform(), args.role)
        try:
            result = installer.run(args.command, args.bundle, args.public_key, args.key_sha256)
        except (ReleaseError, OSError) as error:
            if installer.mutation_started:
                print(json.dumps({'result': 'inhibited_or_unknown', 'error': str(error),
                    'next_action': 'inspect_retained_installer_journal_before_explicit_recovery',
                    'automatic_retry': False, 'authority_issued': False}), file=sys.stderr)
                raise SystemExit(1) from error
            raise
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    # The installer imports this module; keep one exception/type identity when
    # this file is also the executable entry point.
    sys.modules['release'] = sys.modules[__name__]
    try:
        main()
    except (ReleaseError, OSError) as error:
        print(json.dumps({'result': 'rejected', 'error': str(error), 'authority_issued': False}), file=sys.stderr)
        sys.exit(1)
