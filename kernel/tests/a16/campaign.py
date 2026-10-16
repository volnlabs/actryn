#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""One reviewed already-booted A16 pilot/block; never launches a VM or retries."""
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

import analyze
import capture_guest5
import dispatch
import environment3
from prepare import qemu_command

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fixture_bridge

ARMS = ('kernel', 'userspace', 'userspace', 'kernel')
BUILD = '/opt/actryn-a16/build-amendment2'
INSTRUMENT = '/opt/actryn-a16/instrumentation4'
SCENARIOS = ('normal', 'cancel', 'delayed-applied', 'owner-exit', 'normal',
             'cancel', 'delayed-applied', 'owner-exit', 'normal', 'normal')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    with path.open('x') as stream:
        json.dump(data, stream, indent=2); stream.write('\n')


def commands(root):
    labels = [(f'block{i:02d}', arm) for i, arm in enumerate(ARMS, 1)]
    labels += [('tracekernel01', 'kernel'), ('traceuserspace01', 'userspace')]
    result = {}
    for label, arm in labels:
        command = qemu_command(root, 'protected' if arm == 'kernel' else 'raw', label)
        if arm == 'userspace':
            command[command.index('-dtb') + 1] = str(root / 'boot/raw-compact-amendment3.dtb')
        result[label] = command
    return result


def fixture_snapshot(root):
    expected = [str(root / 'bin/controller-fixture'), '--socket', str(root / 'controller.sock'),
                '--state', str(root / 'fixture.state'), '--admin', str(root / 'fixture-admin.sock')]
    if json.loads((root / 'fixture-command.json').read_text()) != expected:
        raise ValueError('fixture launch manifest changed')
    pid = int(subprocess.check_output(['systemctl', '--user', 'show', '--property=MainPID', '--value',
                                      'actryn-a16-fixture.service'], text=True, timeout=5).strip())
    if pid <= 0:
        raise ValueError('dedicated fixture is not running')
    proc = pathlib.Path('/proc') / str(pid)
    actual = [arg.decode() for arg in (proc / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')]
    if actual != expected or sha(proc / 'exe') != sha(root / 'bin/controller-fixture'):
        raise ValueError('running fixture differs from pinned artifact')
    return {'pid': pid, 'argv': actual, 'start_ticks': (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]}


def successful_summary(report):
    return (report.get('planned_trials') == report.get('begun_trials') == report.get('ended_trials')
            == report.get('passed_trials') == 10 and report.get('complete_marker') is True
            and all(report.get(key) == 0 for key in ('failed_trials', 'unfinished_or_unstarted_trials',
                'new_event_loss_in_ended_trials', 'event_sequence_discontinuities', 'reversed_clock_pairs'))
            and report.get('loss_counter_saturated') is False)


def qualify_trials(rows, arm):
    manifests = [row for row in rows if row['type'] == 'manifest']
    if len(manifests) != 1 or any(manifests[0].get(key) != value for key, value in
            {'revision': 1, 'amendment': 2, 'arm': arm, 'planned_trials': 10}.items()):
        raise ValueError('unchanged amendment-2 workload required')
    begins = [row for row in rows if row['type'] == 'trial_begin']
    ends = [row for row in rows if row['type'] == 'trial_end']
    if ([row['trial'] for row in begins] != list(range(10))
            or tuple(row['scenario'] for row in begins) != SCENARIOS
            or [row['trial'] for row in ends] != list(range(10))
            or not all(row['pass'] is True for row in ends)):
        raise ValueError('every fixed trial must pass in order')
    complete = [row for row in rows if row['type'] == 'complete']
    if len(complete) != 1 or complete[0].get('trials') != 10 or complete[0].get('failures') != 0:
        raise ValueError('successful complete marker required')
    terminals = [row for row in rows if row['type'] == 'terminal']
    if [row['trial'] for row in terminals] != [i for i, scenario in enumerate(SCENARIOS)
                                              if scenario in ('normal', 'cancel')]:
        raise ValueError('normal/cancel terminal evidence missing')
    for row in terminals:
        reason = 1 if SCENARIOS[row['trial']] == 'normal' else 2
        if (row['state'] != 2 or row['operation_state'] != 4 or row['reason'] != reason
                or row['flags'] & 9 != 9 or row['left'] or row['right']
                or any(row[key] <= 0 or row[key] != row['expected_' + key]
                       for key in ('grant', 'operation', 'stream'))):
            raise ValueError('terminal reason/output/retained authority differs')


def verify_campaign_inputs():
    manifest = tomllib.loads((HERE / 'campaign.toml').read_text())
    if manifest['revision'] != 1 or manifest['arms'] != list(ARMS) or manifest['runs_per_boot'] != 2:
        raise ValueError('frozen four-boot/eight-run campaign required')
    for name, expected in manifest['sources'].items():
        if sha(HERE / name) != expected:
            raise ValueError('campaign source changed: ' + name)
    return manifest


def check_history(block, history, boot, source, manifest):
    if len(history) != block - 1 or len({row['boot'] for row in history} | {boot}) != block:
        raise ValueError('ordered separate boot history required')
    if any(row['runner_sha256'] != source or row['campaign_sha256'] != manifest
           or row['completed_runs'] != 2 for row in history):
        raise ValueError('previous block incomplete or runner changed')


def guarded(label, script, close=False):
    # Both delayed start and retirement linearize under this fixed run lock.
    fence = f'/run/actryn-a16-{label}.closed'
    prefix = ': > ' + fence if close else 'test ! -e ' + fence
    return f'flock -w 5 /run/actryn-a16-{label}.lock sh -c ' + shlex.quote('set -eu; ' + prefix + '; ' + script)


class Remote:
    def __init__(self, root):
        self.argv = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=yes',
                     '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=3',
                     '-o', 'UserKnownHostsFile=' + str(root / 'known_hosts'), '-i', str(root / 'id_ed25519'),
                     '-p', '26224', 'root@127.0.0.1']

    def run(self, command, output, name, check=True, timeout=30):
        try:
            result = subprocess.run(self.argv + [command], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            (output / name).write_bytes(error.stdout or b'')
            (output / (name + '.exit')).write_text('TIMEOUT\n')
            raise
        (output / name).write_bytes(result.stdout)
        (output / (name + '.exit')).write_text(str(result.returncode) + '\n')
        if check:
            result.check_returncode()
        return result


def unpack(path, prefix, destination):
    destination.mkdir()
    total = 0
    with tarfile.open(path) as archive:
        for member in archive:
            parts = pathlib.PurePosixPath(member.name).parts
            if member.isdir() and parts == (prefix,):
                continue
            if not member.isfile() or len(parts) != 2 or parts[0] != prefix or parts[1] in ('.', '..'):
                raise ValueError('unexpected evidence archive member')
            total += member.size
            if total > 16 * 1024 * 1024:
                raise ValueError('evidence archive cap exceeded')
            with (destination / parts[1]).open('xb') as stream:
                stream.write(archive.extractfile(member).read())


def prerequisites(root, block):
    verify_campaign_inputs()
    environment3.verify(root)
    capture_guest5.verify_inputs()
    base = tomllib.loads((root / 'manifest.toml').read_text())
    for name, local in (('kernel', 'boot/vmlinuz'), ('initrd', 'boot/initrd'),
                         ('protected_dtb', 'boot/protected.dtb'), ('fixture', 'bin/controller-fixture')):
        if sha(root / local) != base['assets'][name]['sha256']:
            raise ValueError('frozen environment asset changed: ' + name)
    version = subprocess.check_output(['qemu-system-aarch64', '--version'], text=True, timeout=5)
    if not version.splitlines()[0].endswith(' ' + base['vm']['qemu_version']):
        raise ValueError('QEMU version changed')
    expected_amendment = sha(HERE / 'amendment3.toml')
    environment = json.loads((root / 'qualification/environment3-userspace01/environment.json').read_text())
    if environment.get('status') != 'PASS' or environment.get('amendment3_sha256') != expected_amendment:
        raise ValueError('amended userspace correctness pilot required')
    for name in ('protected01', 'userspace01', 'environment3-userspace01'):
        if not (root / 'qualification' / name / 'PASS').is_file():
            raise ValueError('correctness pilot missing: ' + name)
    manifest = tomllib.loads((HERE / 'instrumentation4.toml').read_text())
    for name, expected in manifest['sources'].items():
        if sha(HERE / name) != expected:
            raise ValueError('instrumentation source changed: ' + name)
    if block:
        for arm in ('kernel', 'userspace'):
            directory = root / 'qualification' / ('instrumentation-' + arm + '01')
            report = json.loads((directory / 'completed.json').read_text())
            if (not (directory / 'PASS').is_file() or report['runner_sha256'] != sha(HERE / 'campaign.py')
                    or report['instrumentation4_sha256'] != sha(HERE / 'instrumentation4.toml')
                    or report['instrumentation5_sha256'] != sha(HERE / 'instrumentation5.toml')
                    or report['campaign_sha256'] != sha(HERE / 'campaign.toml')):
                raise ValueError('matching instrumentation pilot required: ' + arm)


def one_run(root, remote, parent, label, arm, traced):
    output = parent / label; output.mkdir()
    guest = 'actryn-a16-' + label
    capture = '/var/tmp/actryn-a16-capture-' + label
    result = {'label': label, 'arm': arm, 'traced': traced, 'planned_trials': 10,
              'status': 'FAILED', 'workload_error': None, 'cleanup_error': None}
    rows = None
    report = None
    evidence_errors = []
    try:
        if traced:
            remote.run(guarded(label, f'python3 {INSTRUMENT}/capture_guest5.py start {capture}'),
                       output, 'capture-start.log')
        with (output / 'workload.log').open('w') as log, contextlib.redirect_stdout(log):
            fixture_bridge.run(str(root / 'fixture-admin.sock'), remote.argv + [guarded(label,
                f'timeout --kill-after=2 55 {BUILD}/a16-workload {arm} /var/tmp/{guest}')], 60)
    except BaseException as error:
        result['workload_error'] = repr(error)
    finally:
        # Always retire the start fence, including a lost initial SSH response.
        retire = "if pgrep -x a16-workload >/dev/null; then pkill -KILL -x a16-workload; fi; "
        if traced:
            retire += f'if test -f {capture}/state.json; then python3 {INSTRUMENT}/capture_guest5.py stop {capture}; '
            retire += 'else test ! -e /dev/actryn-a16-capture; fi'
        else:
            retire += 'test ! -e /dev/actryn-a16-capture'
        try:
            remote.run(guarded(label, retire, close=True), output, 'retire.log')
        except BaseException as error:
            result['cleanup_error'] = repr(error)
    try:
        remote.run(f'tar -C /var/tmp -czf - {guest}', output, 'workload.tar.gz')
        unpack(output / 'workload.tar.gz', guest, output / 'workload')
        rows = [json.loads(line) for line in (output / 'workload/events.jsonl').read_text().splitlines()]
        report = analyze.summarize(rows)
        if report['arm'] != arm:
            raise ValueError('workload arm changed')
        result['summary'] = report
        qualify_trials(rows, arm)
    except BaseException as error:
        evidence_errors.append({'phase': 'workload-export', 'error': repr(error)})
    if traced:
        try:
            remote.run(f'tar -C /var/tmp -czf - {pathlib.Path(capture).name}', output, 'capture.tar.gz')
            unpack(output / 'capture.tar.gz', pathlib.Path(capture).name, output / 'capture')
            capture_result = json.loads((output / 'capture/result.json').read_text())
            capture_amendment = json.loads((output / 'capture/instrumentation5.json').read_text())
            if (capture_result['module_unloaded'] is not True or capture_result['start_failed'] is not False
                    or capture_result['capture_sha256'] != sha(output / 'capture/capture.bin')
                    or capture_amendment['instrumentation4_sha256'] != sha(HERE / 'instrumentation4.toml')
                    or capture_amendment['instrumentation5_sha256'] != sha(HERE / 'instrumentation5.toml')
                    or (report is not None and capture_result['boot_id'] != report['boot'])):
                raise ValueError('capture provenance, successful lifecycle or boot mismatch')
            captured = dispatch.decode_capture((output / 'capture/capture.bin').read_bytes())
            correlated = dispatch.correlate(captured, rows) if rows is not None else None
            save(output / 'dispatch.json', {'capture': captured, 'correlation': correlated})
            if correlated is not None:
                result['eligible_requests'] = correlated['eligible_successful_requests']
                result['matched_requests'] = correlated['matched_requests']
        except BaseException as error:
            evidence_errors.append({'phase': 'capture-export-decode', 'error': repr(error)})
    try:
        remote.run('dmesg', output, 'kernel.log')
    except BaseException as error:
        evidence_errors.append({'phase': 'kernel-log', 'error': repr(error)})
    result['evidence_errors'] = evidence_errors
    if (report is not None and successful_summary(report) and not evidence_errors
            and not result['workload_error'] and not result['cleanup_error']
            and (not traced or result.get('matched_requests') == result.get('eligible_requests', 0) > 0)):
        result['status'] = 'PASS'
    save(output / 'result.json', result)
    (output / result['status']).write_text(result['status'] + '\n')
    if result['cleanup_error']:
        raise RuntimeError('unknown cleanup blocks the remaining paired run')
    return result


def execute(root, label, arm, block):
    parent = root / ('comparison' if block else 'qualification')
    parent.mkdir(exist_ok=True)
    output = parent / (f'block{block:02d}' if block else 'instrumentation-' + arm + '01')
    output.mkdir()  # A failed setup consumes this labeled attempt too.
    record = {'runner_sha256': sha(HERE / 'campaign.py'), 'label': label, 'arm': arm,
              'instrumentation4_sha256': sha(HERE / 'instrumentation4.toml'), 'completed_runs': 0,
              'instrumentation5_sha256': sha(HERE / 'instrumentation5.toml'),
              'campaign_sha256': sha(HERE / 'campaign.toml'),
              'planned_runs': 2 if block else 1, 'comparison': bool(block)}
    remote = Remote(root)
    runs = []
    gateway_attempted = False
    record['planned_labels'] = [label + ('trace' if traced else 'evidence')
                                for traced in ((False, True) if block else (True,))]
    try:
        prerequisites(root, block)
        record['process_before'] = environment3.running_snapshot(commands(root)[label])
        record['fixture_before'] = fixture_snapshot(root)
        expected_instrument = record['instrumentation4_sha256']
        expected_guard = record['instrumentation5_sha256']
        binary_pins = tomllib.loads((HERE / 'campaign.toml').read_text())['guest_binaries']
        checksum_lines = [shlex.quote(value + '  ' + BUILD + '/' + name) for name, value in binary_pins.items()]
        verify_binaries = "printf '%s\\n' " + ' '.join(checksum_lines) + ' | sha256sum -c -; '
        command = ('set -eu; test "$(cat /etc/hostname)" = actryn-a16; '
                   'test "$(uname -r)" = 6.12.111+deb13-arm64; test "$(uname -m)" = aarch64; '
                   'test ! -e /dev/actryn-a16-capture; test ! -e /sys/module/actryn_a16_capture; ! pgrep -x a16-workload; '
                   '! systemctl is-active --quiet actryn-robotd; ! systemctl is-active --quiet actryn-gatewayd; '
                   f'test -f {BUILD}/AMENDMENT2; ' + verify_binaries +
                   f'test "$(sha256sum {INSTRUMENT}/instrumentation4.toml | cut -d" " -f1)" = {expected_instrument}; '
                   f'test "$(sha256sum {INSTRUMENT}/instrumentation5.toml | cut -d" " -f1)" = {expected_guard}; '
                   f'python3 -c "import sys,json,pathlib; sys.path.insert(0, \'{INSTRUMENT}\'); import capture_guest,capture_guest5; capture_guest.guard(); capture_guest.verify_inputs(); capture_guest5.verify_inputs(); print(json.dumps(capture_guest5.passive_idle_state(capture_guest.TraceFS(pathlib.Path(\'/sys/kernel/tracing\')))))"; '
                   'cat /proc/sys/kernel/random/boot_id')
        preflight = remote.run(command, output, 'preflight.log')
        record['boot'] = preflight.stdout.decode().splitlines()[-1]
        if block:
            history = [json.loads((root / f'comparison/block{i:02d}/completed.json').read_text()) for i in range(1, block)]
            check_history(block, history, record['boot'], record['runner_sha256'], record['campaign_sha256'])
        save(output / 'manifest.json', record)
        if arm == 'kernel':
            remote.run('set -eu; test ! -e /dev/ttyAMA1; test ! -e /dev/actryn-authority; '
                       f'insmod {BUILD}/kernel/actryn_authority.ko; test -e /dev/actryn-authority', output, 'authority-load.log')
        else:
            remote.run('set -eu; test -e /dev/ttyAMA1; test ! -e /dev/actryn-authority; '
                       'test ! -e /run/actryn-a16.sock; '
                       'test "$(systemctl show --property=LoadState --value actryn-a16-gateway)" = not-found',
                       output, 'raw-preflight.log')
            gateway_attempted = True
            remote.run(guarded(label, 'systemd-run --unit=actryn-a16-gateway --collect --property=Restart=no '
                       f'--property=TimeoutStopSec=5 {BUILD}/a16-gateway'), output, 'gateway-start.log')
            remote.run("timeout 5 sh -c 'until test -S /run/actryn-a16.sock; do sleep .05; done'", output, 'gateway-ready.log')
        with tempfile.TemporaryDirectory(prefix='actryn-a16-campaign-') as directory:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as control:
                control.bind(str(pathlib.Path(directory) / 'reply')); control.connect(str(root / 'fixture-admin.sock'))
                control.settimeout(2)
                for command in ('drop 0', 'pause-rx 0', 'delay 0'):
                    control.send(command.encode()); reply = control.recv(512).decode()
                    with (output / 'fixture-controls.jsonl').open('a') as stream:
                        stream.write(json.dumps({'command': command, 'reply': reply}) + '\n')
                    if reply != 'OK\n':
                        raise ValueError('fixture control failed')
        for traced in ((False, True) if block else (True,)):
            run_label = label + ('trace' if traced else 'evidence')
            runs.append(one_run(root, remote, output, run_label, arm, traced))
            if runs[-1].get('summary', {}).get('boot') != record['boot']:
                raise ValueError('workload boot changed or missing; retain unfinished denominator')
        record['process_after'] = environment3.running_snapshot(commands(root)[label])
        record['fixture_after'] = fixture_snapshot(root)
        if record['process_before'] != record['process_after'] or record['fixture_before'] != record['fixture_after']:
            raise ValueError('QEMU or fixture process changed')
        record['completed_runs'] = len(runs)
    except BaseException as error:
        record['error'] = repr(error)
        (output / 'FAILED').write_text(repr(error) + '\n')
    finally:
        if gateway_attempted:
            try:
                remote.run(guarded(label, 'systemctl stop actryn-a16-gateway; '
                           'if systemctl is-active --quiet actryn-a16-gateway; then exit 70; fi; '
                           'journalctl -u actryn-a16-gateway --no-pager -n 1000', close=True), output, 'gateway-final.log')
            except BaseException as error:
                record['cleanup_error'] = repr(error)
        record['runs'] = runs
        record['unstarted_or_unreturned_runs'] = [planned for planned in record['planned_labels']
                                                   if planned not in [run['label'] for run in runs]]
        save(output / 'attempt.json', record)
    if record.get('error') or record.get('cleanup_error'):
        raise RuntimeError('pilot/block setup, evidence identity or cleanup failed; no retry')
    record['status'] = 'PASS' if all(run['status'] == 'PASS' for run in runs) else 'FAILED'
    save(output / 'completed.json', record)
    if record['status'] == 'PASS':
        (output / 'PASS').write_text('PASS recorded pilot/block only\n')
    else:
        (output / 'FAILED').write_text('FAILED recorded workload/capture; preserve every trial\n')
        if not block:
            raise RuntimeError('instrumentation pilot failed; comparison blocked')
    print(json.dumps({'output': str(output), 'runs': [run['status'] for run in runs]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    command_parser = sub.add_parser('commands'); command_parser.add_argument('directory', type=pathlib.Path)
    pilot_parser = sub.add_parser('trace-pilot'); pilot_parser.add_argument('arm', choices=['kernel', 'userspace'])
    pilot_parser.add_argument('directory', type=pathlib.Path)
    block_parser = sub.add_parser('block'); block_parser.add_argument('block', type=int, choices=range(1, 5))
    block_parser.add_argument('directory', type=pathlib.Path)
    args = parser.parse_args(); root = args.directory.resolve()
    if root.parts[-3:] != ('.cache', 'qemu', 'a16'):
        parser.error('dedicated prepared A16 directory required')
    if args.action == 'commands':
        print(json.dumps(commands(root), indent=2)); return
    block = args.block if args.action == 'block' else 0
    arm = ARMS[block - 1] if block else args.arm
    label = f'block{block:02d}' if block else 'trace' + arm + '01'
    execute(root, label, arm, block)


if __name__ == '__main__':
    main()
