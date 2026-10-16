#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Explicit disposable-QEMU installation fixture; never release qualification."""
import argparse
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'tools' if (HERE / 'tools/release.py').is_file() else HERE.parent))
import release

PURPOSE = 'integration-fixture-NOT-A-RELEASE'
VARIANTS = ('base', 'next', 'unsigned', 'incomplete', 'wrong-host')
MAX_TRANSFER = release.MAX_BYTES + 2 * 1024 * 1024
MARKER = 'I_CREATED_THIS_DISPOSABLE_GUEST'


def write(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)


def names():
    result = {'payload.tar', 'public-test-key.pem', 'guest.py', 'tools/release.py', 'tools/install.py',
              'TEST-FIXTURE-base.json', 'TEST-FIXTURE-next.json'}
    for name in VARIANTS:
        result.add(f'variants/{name}/manifest.json')
        if name != 'unsigned': result.add(f'variants/{name}/signature.ed25519')
    return result


def prepare(selected, output):
    raw = release.read_file(selected, release.MAX_MANIFEST)
    spec = release.strict_json(raw)
    release.require(spec['provenance']['qualification'] == 'incomplete', 'only unqualified inputs may enter fixture preparation')
    for name in ('release.py', 'install.py'):
        entry = spec['files']['tools/' + name]
        data = release.read_file(entry['source'], single_link=False)
        release.require(release.digest(data) == entry['sha256'] == release.digest((HERE.parent / name).read_bytes()),
                        'selected installer tools differ from this harness revision')
    output = Path(output)
    output.mkdir(mode=0o700)
    campaign = uuid.uuid4().hex
    private, public = output / 'private-test-key.pem', output / 'public-test-key.pem'
    release.openssl(['genpkey', '-algorithm', 'ED25519', '-out', str(private)])
    private.chmod(0o600)
    release.openssl(['pkey', '-in', str(private), '-pubout', '-out', str(public)])
    fingerprint = release.digest(release.openssl(['pkey', '-pubin', '-in', str(public), '-outform', 'DER']))
    manifests = {}
    for version in ('base', 'next'):
        assertion = {'purpose': PURPOSE, 'release_qualification': False, 'role': spec['role'],
                     'campaign': campaign, 'fixture_variant': version, 'input_spec_sha256': release.digest(raw)}
        blob = release.canonical(assertion)
        write(output / f'TEST-FIXTURE-{version}.json', blob)
        fixture = copy.deepcopy(spec)
        fixture['provenance'].update(qualification='software-preview-qualified',
            evidence={'qualification-bundle': release.digest(blob), 'INTEGRATION-FIXTURE-NOT-RELEASE': release.digest(blob)},
            custodian_attestation={'role': spec['role'], 'scope': 'server-independent-D2' if spec['role'] == 'server' else 'robot-software-preview',
                                   'qualification_bundle_sha256': release.digest(blob)})
        if version == 'base':
            release.build(fixture, output / '.build')
            manifests['base'] = release.strict_json((output / '.build/manifest.json').read_bytes())
            (output / '.build/payload.tar').rename(output / 'payload.tar')
            (output / '.build/manifest.json').unlink(); (output / '.build').rmdir()
        else:
            manifests['next'] = copy.deepcopy(manifests['base'])
            manifests['next']['provenance'] = fixture['provenance']
    manifests['unsigned'] = copy.deepcopy(manifests['base'])
    manifests['incomplete'] = copy.deepcopy(manifests['base'])
    manifests['incomplete']['provenance'].update(qualification='incomplete', custodian_attestation=None)
    manifests['wrong-host'] = copy.deepcopy(manifests['base'])
    original = manifests['wrong-host']['target']['kernel_image_sha256']
    manifests['wrong-host']['target']['kernel_image_sha256'] = ('1' if original[0] == '0' else '0') + original[1:]
    for name, manifest in manifests.items():
        release.validate_manifest(manifest)
        directory = output / 'variants' / name
        write(directory / 'manifest.json', release.canonical(manifest))
        if name != 'unsigned':
            release.openssl(['pkeyutl', '-sign', '-rawin', '-inkey', str(private),
                '-in', str(directory / 'manifest.json'), '-out', str(directory / 'signature.ed25519')])
    for name in ('release.py', 'install.py'):
        data = release.read_file(spec['files']['tools/' + name]['source'], single_link=False)
        release.require(release.digest(data) == spec['files']['tools/' + name]['sha256'], 'tool changed during preparation')
        write(output / 'tools' / name, data)
    write(output / 'guest.py', Path(__file__).read_bytes())
    job = {'format': 1, 'purpose': PURPOSE, 'release_qualification': False, 'role': spec['role'],
           'campaign': campaign, 'input_spec_sha256': release.digest(raw), 'target': spec['target'],
           'key_fingerprint': fingerprint, 'files': {}}
    for name in sorted(names()):
        path = output / name
        job['files'][name] = {'size': path.stat().st_size, 'sha256': release.hash_file(path, path.stat().st_size)}
    release.require(sum(e['size'] for e in job['files'].values()) <= MAX_TRANSFER, 'fixture transfer capacity')
    write(output / 'job.json', release.canonical(job))
    verify_prepared(output)
    return job


def verify_prepared(root):
    root = Path(root)
    metadata = root.lstat()
    release.require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.geteuid()
                    and metadata.st_mode & 0o077 == 0, 'private owned preparation directory required')
    job = release.strict_json(release.read_file(root / 'job.json', release.MAX_MANIFEST))
    release.require(job['format'] == 1 and job['purpose'] == PURPOSE and job['release_qualification'] is False
                    and re.fullmatch('[0-9a-f]{32}', job['campaign']) and set(job['files']) == names(), 'fixture job binding')
    release.target_valid(job['role'], job['target'])
    total = 0
    for name, entry in job['files'].items():
        release.fields(entry, ('size', 'sha256'), 'fixture file')
        release.require(type(entry['size']) is int and 0 <= entry['size'] <= MAX_TRANSFER
                        and release.is_hash(entry['sha256']), 'fixture file bounds')
        for parent in (root / name).parents:
            if parent == root: break
            release.require(parent.is_dir() and not parent.is_symlink(), 'fixture path symlink')
        release.require(release.hash_file(root / name, entry['size']) == entry['sha256'], 'fixture file changed')
        total += entry['size']
    release.require(total <= MAX_TRANSFER, 'fixture aggregate capacity')
    return job


def upload_files(root, job):
    release.require(set(job['files']) == names(), 'fixture upload allowlist')
    return sorted(job['files']) + ['job.json']


PROBE = r'''import json,os,pathlib,platform,subprocess
p=pathlib.Path
units=['actryn-observer','actryn-launcher','actryn-serverd','actryn-robotd','actryn-gatewayd']
active=[]
for u in units:
 s=subprocess.run(['/usr/bin/systemctl','show','--value','-p','ActiveState',u+'.service'],capture_output=True,timeout=10)
 if s.returncode or s.stdout.strip() not in [b'inactive',b'failed']: active.append(u)
paths=['/opt/actryn','/var/lib/actryn-install','/etc/actryn','/var/lib/actryn-server',
'/var/lib/actryn-robot','/var/lib/actryn-observer','/var/lib/actryn-artifacts']
paths+=['/usr/bin/'+u for u in ['actryn']+units]
paths+=['/usr/local/bin/'+u for u in ['actryn']+units]
paths+=['/usr/lib/systemd/system/'+u+'.service' for u in units]
paths+=['/etc/systemd/system/'+u+'.service' for u in units]
paths+=['/etc/systemd/system/'+u+'.service.d' for u in units]
paths+=['/usr/lib/sysusers.d/actryn-'+r+'.conf' for r in ['server','robot']]
paths+=['/usr/lib/tmpfiles.d/actryn-server.conf','/usr/lib/actryn/observer.bpf.o']
print(json.dumps({'euid':os.geteuid(),'debian':p('/etc/debian_version').read_text().strip(),
'machine':platform.machine(),'kernel':platform.release(),'virtualization':subprocess.check_output(['/usr/bin/systemd-detect-virt'],timeout=10).decode().strip(),
'boot_id':p('/proc/sys/kernel/random/boot_id').read_text().strip().replace('-',''),'machine_id':p('/etc/machine-id').read_text().strip(),
'installed':[v for v in paths if p(v).exists() or p(v).is_symlink()],'active_units':active,'authority_loaded':p('/sys/module/actryn_authority').exists()}))'''


def verify_probe(job, probe, boot, machine):
    role = job['role']
    release.require(probe['euid'] == 0 and probe['debian'] == '13.7'
        and probe['machine'] == ('aarch64' if role == 'robot' else 'x86_64')
        and probe['kernel'] == job['target']['kernel_release']
        and probe['virtualization'] in (('qemu', 'kvm') if role == 'server' else ('qemu',))
        and probe['boot_id'] == boot and probe['machine_id'] == machine
        and not probe['installed'] and not probe['active_units'] and probe['authority_loaded'] is False,
        'guest is not the explicitly identified fresh inactive disposable tuple')


def ssh_base(args):
    ipaddress.ip_address(args.ssh_host)
    release.require(1 <= args.ssh_port <= 65535, 'SSH port')
    for path in (args.ssh_key, args.known_hosts):
        release.require(Path(path).is_file(), 'explicit SSH identity/known_hosts required')
    return ['/usr/bin/ssh', '-F', '/dev/null', '-i', str(args.ssh_key), '-p', str(args.ssh_port),
        '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'UserKnownHostsFile=' + str(args.known_hosts), '-o', 'ForwardAgent=no',
        '-o', 'ClearAllForwardings=yes', '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=10',
        '-o', 'ServerAliveCountMax=1', 'root@' + args.ssh_host]


def remote(ssh, argv, data=None, timeout=60):
    result = subprocess.run(ssh + [shlex.join(argv)], input=data, capture_output=True, timeout=timeout)
    release.require(result.returncode == 0, 'SSH step failed: ' + result.stderr[:4096].decode(errors='replace'))
    return result.stdout


def run(args):
    release.require(args.fresh_disposable_guest == MARKER, 'explicit disposable guest acknowledgement required')
    job = verify_prepared(args.prepared)
    release.require(args.image_sha512 == job['target']['image_sha512'], 'independent base image pin mismatch')
    boot = uuid.UUID(args.expected_boot_id).hex
    machine = args.expected_machine_id
    release.require(re.fullmatch('[0-9a-f]{32}', machine), 'expected machine ID')
    output = Path(args.output); output.mkdir(mode=0o700)
    write(output / 'campaign.json', release.canonical({'purpose': PURPOSE, 'release_qualification': False,
        'campaign': job['campaign'], 'job_sha256': release.digest((args.prepared / 'job.json').read_bytes()),
        'boot_id': boot, 'machine_id': machine, 'image_sha512_attestation': args.image_sha512}))
    ssh = ssh_base(args)
    probe_bytes = remote(ssh, ['/usr/bin/python3', '-B', '-E', '-s', '-c', PROBE])
    write(output / 'probe.json', probe_bytes)
    verify_probe(job, release.strict_json(probe_bytes), boot, machine)
    destination = '/var/tmp/actryn-release-fixture-' + job['campaign']
    remote(ssh, ['/usr/bin/python3', '-B', '-E', '-s', '-c',
        'import os,sys;os.mkdir(sys.argv[1],0o700)', destination])
    # Fixed generated paths only; private-test-key.pem is never in this allowlist.
    uploader = '''import os,pathlib,sys
p=pathlib.Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
f=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
with os.fdopen(f,'wb') as out:
 while True:
  block=sys.stdin.buffer.read(65536)
  if not block: break
  out.write(block)
'''
    for name in upload_files(args.prepared, job):
        with (args.prepared / name).open('rb') as stream:
            result = subprocess.run(ssh + [shlex.join(['/usr/bin/python3', '-B', '-E', '-s', '-c', uploader,
                destination + '/' + name])], stdin=stream, capture_output=True, timeout=180)
        release.require(result.returncode == 0, 'fixture upload failed; retain campaign directory')
    # A failure is retained once; there is no retry or alternative guest selection.
    result = subprocess.run(ssh + [shlex.join(['/usr/bin/python3', '-B', '-E', '-s', destination + '/guest.py',
        'guest', '--prepared', destination, '--expected-boot-id', boot, '--expected-machine-id', machine])],
        capture_output=True, timeout=1200)
    write(output / 'guest.stdout.jsonl', result.stdout)
    write(output / 'guest.stderr.log', result.stderr)
    release.require(result.returncode == 0, 'guest campaign failed; inspect retained phase diagnostics, never silently retry')
    return {'result': 'installation_transition_fixture_passed', 'release_qualification': False,
            'purpose': PURPOSE, 'guest_campaign_path': destination, 'authority_issued': False}


def guest(args):
    from install import Installer, SystemPlatform
    root = Path(args.prepared)
    job = verify_prepared(root)
    release.require(str(root) == '/var/tmp/actryn-release-fixture-' + job['campaign'], 'fixed guest campaign directory')
    probe = release.strict_json(subprocess.check_output(['/usr/bin/python3', '-B', '-E', '-s', '-c', PROBE], timeout=60))
    verify_probe(job, probe, uuid.UUID(args.expected_boot_id).hex, args.expected_machine_id)
    role = job['role']
    candidate = root / 'candidate'; candidate.mkdir(mode=0o700)
    sentinel_paths = [Path(f'/var/lib/actryn-{role}/INSTALL-TEST-STATE'),
                      Path(f'/var/lib/actryn-{role}/evidence/INSTALL-TEST-EVIDENCE'),
                      Path(f'/etc/actryn/INSTALL-TEST-SECRET-{role}')]
    sentinels = {}
    for path in sentinel_paths:
        write(path, (PURPOSE + ':' + job['campaign'] + ':' + path.name).encode())
        sentinels[str(path)] = release.digest(path.read_bytes())
    write(root / 'sentinels.json', release.canonical(sentinels))
    adapter = SystemPlatform()
    installer = Installer(Path('/'), adapter, role)
    common = root / 'payload.tar'
    log = (root / 'phases.jsonl').open('x')

    def record(name, **values):
        value = {'phase': name, 'purpose': PURPOSE, **values}
        line = json.dumps(value, sort_keys=True)
        print(line, flush=True); log.write(line + '\n'); log.flush(); os.fsync(log.fileno())

    def select(name):
        for entry in ('manifest.json', 'signature.ed25519'):
            target = candidate / entry
            if target.exists(): target.unlink()
            source = root / 'variants' / name / entry
            if source.exists(): write(target, source.read_bytes())
        if common.exists(): common.rename(candidate / 'payload.tar')

    def unchanged():
        for path, pin in sentinels.items():
            release.require(release.digest(release.read_file(path)) == pin, 'original sentinel changed')
        for unit in release.UNITS[role]:
            release.require(adapter.inactive(unit), 'installation unexpectedly started a service')
        release.require(not Path('/sys/module/actryn_authority').exists(), 'installation unexpectedly loaded authority')

    def pristine_install_paths():
        for selected_role in release.ARCH:
            selected = Installer(Path('/'), adapter, selected_role)
            paths = [selected.base, selected.state]
            paths += [Path('/') / path for path in selected.bindings({})]
            paths += [Path('/etc/systemd/system') / (unit + '.service.d') for unit in release.UNITS[selected_role]]
            release.require(all(not path.exists() and not path.is_symlink() for path in paths),
                            'rejected candidate mutated managed installation paths')

    def invoke(phase, action, variant='base', expected=0, requested_role=None):
        select(variant)
        command = ['/usr/bin/python3', '-B', '-E', '-s', str(root / 'tools/release.py'), action,
                   '--role', requested_role or role]
        if action != 'preflight': command += ['--bundle', str(candidate), '--public-key', str(root / 'public-test-key.pem'),
                                             '--key-sha256', job['key_fingerprint']]
        result = subprocess.run(command, capture_output=True, timeout=180)
        record(phase, returncode=result.returncode, stdout=result.stdout[:65536].decode(errors='replace'),
               stderr=result.stderr[:65536].decode(errors='replace'))
        release.require(result.returncode == expected, 'unexpected installation result at ' + phase)
        report = release.strict_json(result.stderr if expected else result.stdout)
        release.require(isinstance(report, dict) and report.get('authority_issued') is False,
                        'installation command did not provide its explicit no-authority report')
        if expected:
            release.require(report.get('result') == 'rejected', 'negative case reached mutation or failed unexpectedly')
        unchanged()
        return result

    try:
        record('fresh-identity-confirmed', probe=probe, release_qualification=False)
        for variant in ('unsigned', 'incomplete', 'wrong-host'):
            invoke('reject-' + variant, 'activate', variant, expected=1)
            pristine_install_paths()
        invoke('reject-wrong-role', 'activate', expected=1, requested_role='server' if role == 'robot' else 'robot')
        pristine_install_paths()
        invoke('stage-base', 'stage')
        release.require(installer.current() is None and installer.gate.is_file(), 'stage published or uninhibited')
        invoke('activate-base', 'activate')
        base = release.digest((root / 'variants/base/manifest.json').read_bytes())
        next_ = release.digest((root / 'variants/next/manifest.json').read_bytes())
        release.require(installer.current() == base and installer.gate.is_file(), 'base publication mismatch')
        select('next')
        script = '''import os,pathlib,sys
from install import Installer,SystemPlatform
def fault(name):
 if name=='pointer':
  print('INJECTED_PROCESS_EXIT_AFTER_DURABLE_POINTER',flush=True);os._exit(86)
Installer(pathlib.Path('/'),SystemPlatform(),sys.argv[1],fault).run('activate',pathlib.Path(sys.argv[2]),pathlib.Path(sys.argv[3]),sys.argv[4])
'''
        # Explicit separate process models abrupt exit at one actual durable boundary.
        child = subprocess.run(['/usr/bin/python3', '-B', '-E', '-s', '-c',
            'import sys;sys.path.insert(0,sys.argv.pop(1));' + script,
            str(root / 'tools'), role, str(candidate), str(root / 'public-test-key.pem'), job['key_fingerprint']],
            capture_output=True, timeout=180)
        record('injected-pointer-interruption', returncode=child.returncode,
               stdout=child.stdout[:65536].decode(errors='replace'), stderr=child.stderr[:65536].decode(errors='replace'))
        release.require(child.returncode == 86 and installer.current() == next_ and installer.gate.is_file(), 'interruption boundary not reached')
        unchanged()
        invoke('explicit-recover-next', 'recover', 'next')
        invoke('explicit-rollback-base', 'rollback')
        release.require(installer.current() == base and installer.gate.is_file(), 'rollback changed inhibition/tuple')
        invoke('gated-preflight-rejected', 'preflight', expected=1)
        invoke('missing-bootstrap-resume-rejected', 'resume', expected=1)
        release.require(installer.gate.is_file(), 'missing bootstrap cleared gate')
        record('installation-transitions-passed', release_qualification=False, authority_issued=False,
               services_started=False, module_loaded=False, installed_inhibited=True,
               successful_startup_tested=False, sentinel_sha256=sentinels)
    except BaseException as error:
        record('FAILED-PRESERVED-NO-RETRY', error=str(error), installed_state_unknown=True)
        raise
    finally:
        log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('prepare'); build.add_argument('--spec', type=Path, required=True); build.add_argument('--out', type=Path, required=True)
    run_parser = commands.add_parser('run')
    for name in ('prepared', 'output', 'ssh-key', 'known-hosts'): run_parser.add_argument('--' + name, type=Path, required=True)
    for name in ('ssh-host', 'expected-boot-id', 'expected-machine-id', 'image-sha512', 'fresh-disposable-guest'):
        run_parser.add_argument('--' + name, required=True)
    run_parser.add_argument('--ssh-port', type=int, required=True)
    internal = commands.add_parser('guest', help=argparse.SUPPRESS)
    internal.add_argument('--prepared', type=Path, required=True)
    internal.add_argument('--expected-boot-id', required=True); internal.add_argument('--expected-machine-id', required=True)
    args = parser.parse_args(); os.umask(0o077)
    if args.command == 'prepare': result = prepare(args.spec, args.out)
    elif args.command == 'run': result = run(args)
    else: guest(args); return
    print(json.dumps({'purpose': PURPOSE, 'release_qualification': False, 'result': result}, sort_keys=True))


if __name__ == '__main__':
    try: main()
    except (release.ReleaseError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'purpose': PURPOSE, 'result': 'FAILED-PRESERVED-NO-RETRY', 'error': str(error),
                          'release_qualification': False}), file=sys.stderr)
        sys.exit(1)
