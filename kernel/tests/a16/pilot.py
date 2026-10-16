#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""One labeled qualification per mode, only on the dedicated already-booted VM."""
import argparse
import contextlib
import hashlib
import json
import pathlib
import shlex
import socket
import subprocess
import sys
import tarfile
import tempfile
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fixture_bridge

SCENARIOS = ['normal', 'cancel', 'delayed-applied', 'owner-exit', 'normal',
             'cancel', 'delayed-applied', 'owner-exit', 'normal', 'normal']
BUILD = '/opt/actryn-a16/build-amendment2'
GUEST_OUTPUT = 'actryn-a16-pilot-userspace-01'


def gateway_command(script):
    return 'flock -w 5 /run/actryn-a16-pilot01.lock sh -c ' + shlex.quote('set -eu; ' + script)


@contextlib.contextmanager
def gateway_session(remote, output):
    # The caller has confirmed no prior unit. A lost start reply can still mean
    # this attempt created the unit, so cleanup is required before any retry.
    try:
        remote(gateway_command('test ! -e /run/actryn-a16-pilot01.closed; '
               'systemd-run --unit=actryn-a16-gateway --collect --property=Restart=no '
               f'--property=TimeoutStopSec=5 {BUILD}/a16-gateway'), 'gateway-start.log')
        yield
    finally:
        try:
            # Retire the start under the same lock before stopping. Even an SSH
            # command that begins late cannot create the unit after cleanup.
            remote(gateway_command(': > /run/actryn-a16-pilot01.closed; '
                   'systemctl stop actryn-a16-gateway; '
                   'if systemctl is-active --quiet actryn-a16-gateway; then exit 70; fi; '
                   'journalctl -u actryn-a16-gateway --no-pager --output=short-monotonic -n 1000'),
                   'gateway-final.log')
        except BaseException as error:
            with (output / 'FAILED').open('a') as stream:
                stream.write('cleanup: ' + repr(error) + '\n')
            raise


def qualify_workload(rows):
    manifests = [r for r in rows if r['type'] == 'manifest']
    begins = [r for r in rows if r['type'] == 'trial_begin']
    ends = [r for r in rows if r['type'] == 'trial_end']
    done = [r for r in rows if r['type'] == 'complete']
    if len(manifests) != 1 or any(manifests[0].get(k) != v for k, v in
            {'revision': 1, 'amendment': 2, 'arm': 'userspace', 'planned_trials': 10}.items()):
        raise ValueError('fixed userspace workload manifest required')
    if [r['trial'] for r in begins] != list(range(10)) or [r['scenario'] for r in begins] != SCENARIOS:
        raise ValueError('all ten fixed trials must begin in order')
    if [r['trial'] for r in ends] != list(range(10)) or not all(r['pass'] is True for r in ends):
        raise ValueError('missing or failed qualification trial')
    if len(done) != 1 or done[0].get('trials') != 10 or done[0].get('failures') != 0:
        raise ValueError('successful complete marker required')
    if any(a['lost_baseline'] != b['lost_final'] for a, b in zip(begins, ends)):
        raise ValueError('new event loss blocks qualification')
    terminals = [r for r in rows if r['type'] == 'terminal']
    expected = [i for i, scenario in enumerate(SCENARIOS) if scenario in ('normal', 'cancel')]
    if [r['trial'] for r in terminals] != expected:
        raise ValueError('each normal/cancel trial needs its original terminal status')
    for row in terminals:
        reason = 1 if SCENARIOS[row['trial']] == 'normal' else 2
        if (row['state'] != 2 or row['operation_state'] != 4 or row['reason'] != reason
                or row['flags'] & 9 != 9 or row['left'] != 0 or row['right'] != 0
                or any(row[key] <= 0 or row[key] != row['expected_' + key]
                       for key in ('grant', 'operation', 'stream'))):
            raise ValueError('terminal reason/output/retained authority differs from request')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['protected', 'userspace'])
    parser.add_argument('directory', type=pathlib.Path, help='prepared .cache/qemu/a16 directory')
    args = parser.parse_args()
    root = args.directory.resolve()
    assert root.parts[-3:] == ('.cache', 'qemu', 'a16')
    manifest = tomllib.loads((root / 'manifest.toml').read_text())
    prepared = json.loads((root / 'prepared.json').read_text())
    assert hashlib.sha256((root / 'manifest.toml').read_bytes()).hexdigest() == prepared['manifest_sha256']
    amendment = tomllib.loads((HERE / 'amendment2.toml').read_text())
    assert amendment['revision'] == 2 and prepared['manifest_sha256'] == amendment['base_manifest_sha256']
    assert prepared['source_sha256'] == amendment['base_source_archive_sha256']
    for name, expected in amendment['sources'].items():
        assert hashlib.sha256((HERE.parents[2] / name).read_bytes()).hexdigest() == expected, name
    assert manifest['name'] == 'actryn-a16' and manifest['vm']['ssh_port'] == 26224
    assert hashlib.sha256((root / 'bin/controller-fixture').read_bytes()).hexdigest() == manifest['assets']['fixture']['sha256']
    output = root / 'qualification' / (args.mode + '01')
    output.mkdir()  # Preserve every failed attempt; never retry in this directory.
    (output / 'amendment2.toml').write_bytes((HERE / 'amendment2.toml').read_bytes())
    amendment_sha256 = hashlib.sha256((HERE / 'amendment2.toml').read_bytes()).hexdigest()
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=3',
           '-o', 'UserKnownHostsFile=' + str(root / 'known_hosts'), '-i', str(root / 'id_ed25519'),
           '-p', '26224', 'root@127.0.0.1']

    def remote(command, filename, check=True, timeout=30):
        try:
            result = subprocess.run(ssh + [command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=timeout)
        except subprocess.TimeoutExpired as error:
            (output / filename).write_bytes(error.stdout or b'')
            (output / (filename + '.exit')).write_text('TIMEOUT\n')
            raise
        (output / filename).write_bytes(result.stdout)
        (output / (filename + '.exit')).write_text(str(result.returncode) + '\n')
        if check and result.returncode:
            raise RuntimeError(filename + ': exit ' + str(result.returncode))
        return result

    # Keep Unix socket paths below sockaddr_un's limit even for a long checkout.
    with tempfile.TemporaryDirectory(prefix='actryn-a16-control-') as directory:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as control, contextlib.ExitStack() as cleanup:
            try:
                control.bind(str(pathlib.Path(directory) / 'reply'))
                control.connect(str(root / 'fixture-admin.sock'))
                control.settimeout(2)
            except BaseException as error:
                (output / 'FAILED').write_text(repr(error) + '\n')
                raise

            def admin(command):
                control.send(command.encode())
                reply = control.recv(512).decode()
                with (output / 'fixture.jsonl').open('a') as stream:
                    stream.write(json.dumps({'command': command, 'reply': reply}) + '\n')
                if command != 'status' and reply != 'OK\n':
                    raise RuntimeError('fixture command rejected')

            try:
                remote("set -eu; test \"$(cat /etc/hostname)\" = actryn-a16; "
                       "test \"$(uname -r)\" = 6.12.111+deb13-arm64; test \"$(uname -m)\" = aarch64; "
                       "tr '\\0' '\\n' < /proc/device-tree/compatible | grep -qx linux,dummy-virt; "
                       "if systemctl is-active --quiet actryn-robotd || systemctl is-active --quiet actryn-gatewayd; then exit 70; fi; "
                       f"test -f {BUILD}/BUILD_PASS; test -f {BUILD}/AMENDMENT2; cat /proc/sys/kernel/random/boot_id; uname -a; "
                       f"test \"$(sha256sum {BUILD}/amendment2.toml | cut -d' ' -f1)\" = {amendment_sha256}; "
                       f"cat {BUILD}/binaries.sha256; sha256sum -c {BUILD}/binaries.sha256; "
                       f"cat {BUILD}/build-ids.txt", 'environment.log')
                admin('status')
                if args.mode == 'protected':
                    remote('test ! -e /dev/ttyAMA1', 'protected-ownership.log')
                    command = [sys.executable, str(HERE.parent / 'run_guest_campaign.py'),
                               '--identity', str(root / 'id_ed25519'), '--known-hosts', str(root / 'known_hosts'),
                               '--admin', str(root / 'fixture-admin.sock'), '--port', '26224',
                               '--build', BUILD, '--output', str(output / 'campaign'),
                               'selftest', 'controller-restart']
                    with (output / 'campaign.log').open('w') as log:
                        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=80)
                else:
                    remote('set -eu; test -e /dev/ttyAMA1; test ! -e /dev/actryn-authority; '
                           "! grep -q '^actryn_authority ' /proc/modules; test ! -e /run/actryn-a16.sock; "
                           'test "$(systemctl show --property=LoadState --value actryn-a16-gateway)" = not-found; '
                           'test ! -e /run/actryn-a16-pilot01.closed; '
                           f'test ! -e /var/tmp/{GUEST_OUTPUT}', 'raw-ownership.log')
                    for command in ('delay 0', 'drop 0', 'pause-rx 0', 'restart'):
                        admin(command)
                    cleanup.enter_context(gateway_session(remote, output))
                    remote("timeout 5 sh -c 'until test -S /run/actryn-a16.sock; do sleep .05; done'",
                           'gateway-ready.log')
                    remote('timeout --kill-after=2 25 python3 /opt/actryn-a16/src-amendment2/kernel/tests/a16/live_qualify.py',
                           'live-ownership.jsonl')
                    with (output / 'workload.log').open('w') as log, contextlib.redirect_stdout(log):
                        fixture_bridge.run(str(root / 'fixture-admin.sock'), ssh + [
                            f'timeout --kill-after=2 55 {BUILD}/a16-workload userspace /var/tmp/{GUEST_OUTPUT}'], 60)
                    remote(f'tar -C /var/tmp -czf - {GUEST_OUTPUT}', 'workload.tar.gz')
                    with tarfile.open(output / 'workload.tar.gz') as archive:
                        rows = [json.loads(line) for line in archive.extractfile(GUEST_OUTPUT + '/events.jsonl')]
                    qualify_workload(rows)
                admin('status')
                remote('dmesg', 'kernel.log')
            except BaseException as error:
                (output / 'FAILED').write_text(repr(error) + '\n')
                remote('dmesg', 'failure.kernel.log', check=False)
                if args.mode == 'userspace':
                    remote(f'tar -C /var/tmp -czf - {GUEST_OUTPUT}', 'partial-workload.tar.gz', check=False)
                raise
    (output / 'PASS').write_text('PASS correctness pilot only; excluded from comparison\n')
    print('PASS', args.mode, 'pilot; no comparison executed')


if __name__ == '__main__':
    main()
