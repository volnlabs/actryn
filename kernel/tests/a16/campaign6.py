#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Module16 amendment: reuse the frozen campaign; never launch/deploy a VM."""
import argparse
import hashlib
import importlib
import json
import pathlib
import re
import shlex
import struct
import sys
import tarfile
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
BUILD = '/opt/actryn-a16/build-amendment6'
EXTRA = {'campaign6.py', 'campaign6_test.py'}
CAMPAIGNS = {
    'lifecycle01': ('selftest', 'dup', 'rights', 'owner-exit', 'unbind-rebind', 'repeated-revoke', 'cancel-revoke'),
    'closure01': ('event-capacity', 'late-sample', 'late-barrier', 'delayed-handoff', 'controller-restart',
                  'ready-recovery', 'inhibited-revoke'),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifests():
    return [tomllib.loads((HERE / name).read_text()) for name in ('campaign.toml', 'amendment6.toml')]


def only_module_change(base, amended):
    expected = dict(base)
    expected['guest_binaries'] = dict(base['guest_binaries'])
    expected['guest_binaries']['kernel/actryn_authority.ko'] = amended['amendment']['module_sha256']
    expected['sources'] = dict(base['sources'])
    expected['sources'].update({name: amended['sources'][name] for name in EXTRA})
    expected['amendment'] = amended['amendment']
    if (amended != expected or amended['amendment']['revision'] != 6
            or amended['amendment']['guest_build'] != BUILD):
        raise ValueError('only the selected module and explicit wrapper inputs may change')


def build_note(data):
    """Read the one exact GNU note from a bounded little-endian ELF64 ARM module."""
    if len(data) < 64 or len(data) > 4 * 1024 * 1024 or data[:7] != b'\x7fELF\x02\x01\x01':
        raise ValueError('bounded ELF64 module required')
    if struct.unpack_from('<HH', data, 16) != (1, 183):
        raise ValueError('ARM64 relocatable module required')
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count, strings = struct.unpack_from('<HHH', data, 58)
    if size != 64 or not 0 < strings < count or offset + size * count > len(data):
        raise ValueError('invalid section table')
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, offset + size * i) for i in range(count)]
    def contents(section):
        start, length = section[4:6]
        if start + length > len(data):
            raise ValueError('truncated section')
        return data[start:start + length]
    names = contents(sections[strings]); notes = []
    for section in sections:
        at = section[0]
        if at >= len(names) or b'\0' not in names[at:]:
            raise ValueError('invalid section name')
        if names[at:].split(b'\0', 1)[0] == b'.note.gnu.build-id':
            if section[1] != 7:
                raise ValueError('build ID is not a note')
            notes.append(contents(section))
    if len(notes) != 1 or len(notes[0]) != 36 or notes[0][:16] != struct.pack('<III', 4, 20, 3) + b'GNU\0':
        raise ValueError('one complete SHA-1 GNU build-ID note required')
    return notes[0]


def qualify_owner(leader, reuse):
    before = re.search(r'leader before exit tgid=(\d+)', leader)
    after = re.search(r'leader exited; surviving tgid=(\d+) tid=(\d+)', leader)
    old = re.search(r'original owner tgid=(\d+)', reuse)
    new = re.search(r'replacement owner tgid=(\d+) equals reaped original', reuse)
    if not (before and after and old and new and before[1] == after[1] != after[2] and old[1] == new[1]):
        raise ValueError('live sibling and genuine numeric PID reuse evidence required')
    for text, case in ((leader, 'leader-exit'), (reuse, 'pid-reuse')):
        for phrase in ('retained HEALTH result=-1 errno=1 ', 'retained ACTIVATE result=-1 errno=1\n',
                       'PASS authority owner lifetime ' + case + '\n'):
            if phrase not in text:
                raise ValueError('owner denial/PASS evidence missing')


def qualify_records(repository, amendment):
    artifacts = repository / 'artifacts'
    for label, cases in CAMPAIGNS.items():
        directory = artifacts / ('kernel-module16-' + label)
        if amendment['module_sha256'] not in (directory / 'environment.log').read_text():
            raise ValueError('correctness campaign tested a different module')
        for index, case in enumerate(cases, 1):
            name = f'{index:02}-{case}'
            if ((directory / (name + '.PASS')).read_text() != 'PASS ' + case + '\n'
                    or (directory / (name + '.log.exit')).read_text() != '0\n'):
                raise ValueError('actual module16 scenario did not pass: ' + name)
    owner = artifacts / 'kernel-module16-owner01'
    if amendment['module_sha256'] not in (owner / 'compile.stdout').read_text():
        raise ValueError('owner tests used a different module')
    for case in ('leader-exit', 'pid-reuse'):
        if (owner / (case + '.PASS')).read_text() != 'PASS ' + case + '\n' or (owner / (case + '.exit')).read_text() != '0\n':
            raise ValueError('actual owner scenario did not pass: ' + case)
    qualify_owner((owner / 'leader-exit.stdout').read_text(), (owner / 'pid-reuse.stdout').read_text())


def verify_hashes(directory, hashes):
    for name, expected in hashes.items():
        path = pathlib.PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('invalid evidence path')
        if sha(directory / name) != expected:
            raise ValueError('actual evidence changed: ' + name)


def verify_acceptance(repository, amendment):
    directory = repository / 'artifacts/kernel-module16-acceptance01'
    if sha(directory / 'manifest.json') != amendment['actual_acceptance_sha256']:
        raise ValueError('selected actual acceptance record changed')
    record = json.loads((directory / 'manifest.json').read_text())
    for field, expected in {'module_sha256': amendment['module_sha256'],
            'source_archive_sha256': amendment['source_archive_sha256'],
            'source_driver_sha256': amendment['driver_sha256'],
            'source_revision': amendment['source_revision'],
            'kernel_release': '6.12.111+deb13-arm64', 'actual_case_count': 16,
            'diagnostic_configurations': dict.fromkeys(('plain', 'lockdep', 'kasan', 'kcsan'), 17),
            'physical_acceptance': False, 'full_release_acceptance': False}.items():
        if record[field] != expected:
            raise ValueError('actual acceptance scope differs: ' + field)
    if sha(directory / 'diagnostics16.tar.gz') != record['diagnostics_archive_sha256']:
        raise ValueError('diagnostic evidence changed')
    expected_cases = {'kernel-module16-' + label: [f'{i:02}-{case}.PASS' for i, case in enumerate(cases, 1)]
                      for label, cases in CAMPAIGNS.items()}
    expected_cases['kernel-module16-owner01'] = ['leader-exit.PASS', 'pid-reuse.PASS']
    if set(record['actual_cases']) != set(expected_cases):
        raise ValueError('actual scenario set changed')
    for name, markers in expected_cases.items():
        evidence = repository / 'artifacts' / name; entry = record['actual_cases'][name]
        if entry['pass_markers'] != markers or sha(evidence / 'artifact-hashes.json') != entry['artifact_hashes_sha256']:
            raise ValueError('actual scenario inventory changed')
        hashes = json.loads((evidence / 'artifact-hashes.json').read_text())
        if len(hashes) != entry['files'] or any(evidence.glob('FAILED*')) or any(evidence.glob('INTERRUPTED*')):
            raise ValueError('incomplete or failed actual scenario evidence')
        verify_hashes(evidence, hashes)
    qualify_records(repository, amendment)
    return record


def verify(root):
    if root.parts[-3:] != ('.cache', 'qemu', 'a16'):
        raise ValueError('dedicated A16 directory required')
    base, amended = read_manifests(); only_module_change(base, amended)
    amendment = amended['amendment']
    if sha(HERE / 'campaign.toml') != amendment['base_campaign_sha256']:
        raise ValueError('original campaign manifest changed')
    for name, expected in amended['sources'].items():
        if sha(HERE / name) != expected:
            raise ValueError('source input changed: ' + name)
    repository = root.parents[2]
    acceptance = verify_acceptance(repository, amendment)
    build = repository / 'artifacts/kernel-module16-build02/evidence'
    for name, field in (('kernel/actryn_authority.ko', 'module_sha256'), ('source.tar.gz', 'source_archive_sha256'),
                        ('config', 'config_sha256'), ('Module.symvers.exact', 'symvers_sha256'),
                        ('packages.txt', 'packages_sha256'), ('compiler.txt', 'compiler_sha256')):
        if sha(build / name) != amendment[field]:
            raise ValueError('selected module provenance changed: ' + name)
    with tarfile.open(build / 'source.tar.gz') as archive:
        for name, field in (('kernel/actryn_driver.c', 'driver_sha256'), ('kernel/actryn_driver_test.h', 'driver_test_sha256')):
            members = [entry for entry in archive.getmembers() if entry.name == name]
            if len(members) != 1 or not members[0].isfile() or members[0].size > 1024 * 1024:
                raise ValueError('invalid selected source archive')
            if hashlib.sha256(archive.extractfile(members[0]).read()).hexdigest() != amendment[field]:
                raise ValueError('tested production source differs')
    note = build_note((build / 'kernel/actryn_authority.ko').read_bytes())
    if note.hex() != amendment['module_note_hex'] or hashlib.sha256(note).hexdigest() != acceptance['loaded_build_id_note_sha256']:
        raise ValueError('selected module build note differs')
    return amended


def stage(root, manifest):
    host = root / 'amendment6/host'; host.mkdir(parents=True)
    target = host / 'a16'; target.mkdir()
    for name in manifest['sources']:
        path = target / name
        with path.open('xb') as stream:
            stream.write((HERE / name).read_bytes())
    (target / 'campaign.toml').write_bytes((HERE / 'amendment6.toml').read_bytes())
    verify_stage(root, manifest)
    return target


def verify_stage(root, manifest):
    target = root / 'amendment6/host/a16'
    for name, expected in manifest['sources'].items():
        if sha(target / name) != expected:
            raise ValueError('staged source changed: ' + name)
    if (target / 'campaign.toml').read_bytes() != (HERE / 'amendment6.toml').read_bytes():
        raise ValueError('staged campaign amendment changed')
    return target


def loaded_command(module_sha, note, module=BUILD + '/kernel/actryn_authority.ko',
                   sysfs='/sys/module/actryn_authority/notes/.note.gnu.build-id'):
    code = ('import hashlib,json,pathlib\n'
            f'p=pathlib.Path({module!r}); n=pathlib.Path({sysfs!r}).read_bytes()\n'
            f'if hashlib.sha256(p.read_bytes()).hexdigest()!={module_sha!r}: raise ValueError("module bytes changed")\n'
            f'if n!=bytes.fromhex({note.hex()!r}): raise ValueError("loaded module note differs")\n'
            'print(json.dumps({"loaded_module_note_hex":n.hex(),"module_sha256":hashlib.sha256(p.read_bytes()).hexdigest()}))')
    return 'python3 -c ' + shlex.quote(code)


def remote_with_note(base, module_sha, note, manifest_sha):
    class SelectedRemote(base):
        def run(self, command, output, name, **kwargs):
            if name == 'preflight.log':
                command = (f'set -eu; test "$(sha256sum {BUILD}/amendment6.toml | cut -d" " -f1)" = {manifest_sha}; '
                           + command)
            result = super().run(command, output, name, **kwargs)
            if name == 'authority-load.log':
                super().run(loaded_command(module_sha, note), output, 'module16-loaded.log')
            return result
    return SelectedRemote


def execute(root, label, arm, block):
    if root.parts[-3:] != ('.cache', 'qemu', 'a16'):
        raise ValueError('dedicated A16 directory required')
    output = root / 'amendment6/attempts' / label; output.mkdir(parents=True)
    record = {'amendment': 6, 'wrapper_sha256': sha(HERE / 'campaign6.py'),
              'campaign_sha256': sha(HERE / 'amendment6.toml'), 'status': 'FAILED', 'label': label}
    (output / 'amendment6.toml').write_bytes((HERE / 'amendment6.toml').read_bytes())
    (output / 'started.json').write_text(json.dumps(record, indent=2) + '\n')
    try:
        manifest = verify(root); target = verify_stage(root, manifest)
        campaign = importlib.import_module('campaign')
        original = campaign.HERE, campaign.BUILD, campaign.Remote
        campaign.HERE, campaign.BUILD = target, BUILD
        campaign.Remote = remote_with_note(original[2], manifest['amendment']['module_sha256'],
                                          bytes.fromhex(manifest['amendment']['module_note_hex']), record['campaign_sha256'])
        try:
            campaign.execute(root, label, arm, block)
        finally:
            campaign.HERE, campaign.BUILD, campaign.Remote = original
        result = root / ('comparison/block%02d' % block if block else 'qualification/instrumentation-' + arm + '01')
        record['completed_sha256'] = sha(result / 'completed.json')
        record['status'] = json.loads((result / 'completed.json').read_text())['status']
    except BaseException as error:
        record['error'] = repr(error)
        raise
    finally:
        (output / 'attempt.json').write_text(json.dumps(record, indent=2) + '\n')
        (output / record['status']).write_text(record['status'] + ' module amendment wrapper\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('verify', 'stage', 'commands', 'trace-pilot', 'block'))
    parser.add_argument('directory', type=pathlib.Path)
    parser.add_argument('selection', nargs='?')
    args = parser.parse_args(); root = args.directory.resolve()
    if args.action in ('verify', 'stage', 'commands'):
        manifest = verify(root)
        if args.action == 'stage':
            print(stage(root, manifest))
        elif args.action == 'commands':
            print(json.dumps(importlib.import_module('campaign').commands(root), indent=2))
        else:
            print(json.dumps({'amendment': 6, 'manifest_sha256': sha(HERE / 'amendment6.toml'), 'actual_module16_records': 'PASS'}))
        return
    if args.action == 'trace-pilot' and args.selection in ('kernel', 'userspace'):
        execute(root, 'trace' + args.selection + '01', args.selection, 0)
    elif args.action == 'block' and args.selection in ('1', '2', '3', '4'):
        block = int(args.selection); execute(root, f'block{block:02d}', ('kernel', 'userspace', 'userspace', 'kernel')[block - 1], block)
    else:
        parser.error('trace-pilot requires kernel|userspace; block requires 1|2|3|4')


if __name__ == '__main__':
    main()
