#!/usr/bin/env python3
"""Opt-in installed-server observer failure campaign; no VM orchestration."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import sqlite3
import struct
import subprocess
import time
import uuid
import guest_capacity as common

require = common.require


def wait_until(function, ready, deadline):
    while True:
        require(time.monotonic() < deadline, 'absolute campaign deadline')
        value = function()
        require(time.monotonic() < deadline, 'absolute campaign deadline')
        if ready(value):
            return value
        time.sleep(.02)


def validate_fault_export(bundle, attempt, artifact, binding, inspection, logs, mode, fault, summary):
    require(mode in ('prestart', 'death', 'loss'), 'unknown fault case')
    require(bundle['schema'] == 'actryn.server.evidence.v1' and bundle['attempt_id'] == attempt
            and bundle['execution_replay_eligible'] is False, 'evidence envelope')
    entries = bundle['artifacts']
    require(len(entries) == 6 and {v['name'] for v in entries} == common.NAMES, 'six unique artifacts required')
    for item in entries:
        raw = json.dumps(item['content'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        require(item['bytes'] == len(raw) and item['sha256'] == 'sha256:' + hashlib.sha256(raw).hexdigest(),
                'canonical artifact hash')
    values = {item['name']: item['content'] for item in entries}
    gaps = [] if mode == 'prestart' else ['observer_unavailable']
    require(bundle['omissions'] == [{'artifact': 'runtime_facts', 'reason': reason, 'omitted_records': 1}
                                   for reason in gaps], 'diagnostic gap omission not explicit')
    record, broker = values['attempt'], values['broker']
    require(record['id'] == attempt and record['artifact_digest'] == artifact
            and record['state'] == 'reaped' and record['outcome'] == 'cancelled'
            and record['binding'] is None, 'terminal launcher identity/outcome')
    require(values['runtime_binding'] == binding and json.loads(inspection['attempt']['binding']) == binding
            and inspection['attempt']['id'] == attempt and inspection['attempt']['artifact_digest'] == artifact
            and inspection['attempt']['state'] == 'reaped'
            and inspection['attempt']['outcome'] == ('start_rejected' if mode == 'prestart' else 'cancelled')
            and inspection['evidence_gaps'] == gaps
            and inspection['robot_binding'] is None and inspection['robot_requests'] == [], 'immutable broker binding')
    initial = binding['observer']
    common.observer_health(initial, initial)
    require(str(uuid.UUID(binding['boot_id'])) == binding['boot_id'] and binding['cgroup_id'] > 0
            and binding['snapshot']['pid'] > 1 and binding['snapshot']['start_ticks'] > 0
            and binding['snapshot']['cgroup'] == '/actryn/' + attempt
            and binding['ambiguous_create'] is False, 'prepared lifetime identity')
    facts = values['runtime_facts']; health = facts['observer']; resources = facts['resources']
    require(facts['observer_health_unavailable'] is (health is None), 'unavailable health mislabeled')
    if mode == 'loss':
        for status in (fault, health, summary['status'] if summary else None):
            require(status is not None and status['ready'] is False and type(status['lost']) is int
                    and status['lost'] > 0 and status['collector_epoch'] == initial['collector_epoch']
                    and status['sequence'] >= initial['sequence']
                    and common.COVERAGE <= set(status['coverage']), 'loss not observed in original epoch')
        require(health['lost'] >= fault['lost'] and summary['status']['lost'] >= health['lost']
                and health['sequence'] >= fault['sequence']
                and summary['status']['sequence'] >= health['sequence']
                and 0 <= summary['local_lost'] <= summary['status']['lost'], 'loss frontier regressed')
    else:
        require(fault is None and summary is None, 'dead collector cannot produce a final old-epoch summary')
        require(health is None or (health['ready'] is False
                and health['collector_epoch'] != initial['collector_epoch']), 'dead observer claimed continuous readiness')
    require(resources['classification'] == 'observed_cgroup_v2_counters'
            and resources['stage'] == 'after_descendants_empty_before_runtime_delete'
            and set(resources['counters']) == common.COUNTERS and resources['unavailable'] == []
            and resources['counters']['pids.current'].strip() == '0', 'final local resources unavailable')
    require(broker['classification'] == 'broker_application_policy_and_delegated_accounting'
            and broker['attempt_state'] == 'reaped' and broker['attempt_outcome'] == inspection['attempt']['outcome']
            and broker['evidence_gaps'] == gaps and broker['policy_denials'] == []
            and broker['policy_denials_retained'] == 0 and inspection['denials'] == []
            and inspection['denials_omitted'] == 0 and broker['calls'] == inspection['calls'], 'durable gap/accounting')
    require(len(broker['calls']) == (0 if mode == 'prestart' else 1)
            and all(v['publication_closed'] is True and v['state'] == 'settled'
                    and v['request_key'] == 'preview-1' and v['consumed_tokens'] == 0
                    for v in broker['calls']), 'publication still open or unexpected call')
    for name, raw in logs.items():
        item = values[name]
        require(item['classification'] == 'untrusted_agent_output_not_policy_attribution'
                and item['file_complete'] is True and item['source_truncated'] is False
                and item['retained_bytes'] == len(raw)
                and item['retained_sha256'] == 'sha256:' + hashlib.sha256(raw).hexdigest()
                and item['tail_encoding'] == 'hex' and item['tail'] == raw[-2048:].hex()
                and item['tail_omitted_bytes'] == max(0, len(raw) - 2048), 'raw log integrity')
    require(set(logs) == {'stdout', 'stderr'} and not logs['stderr'], 'raw source inventory')
    require(not logs['stdout'] if mode == 'prestart' else len(logs['stdout'].splitlines()) == 1,
            'agent executed early or reexecuted')
    if mode != 'prestart':
        proposal = json.loads(logs['stdout'])
        require(proposal['event'] == 'preview_proposal' and proposal['authority_issued'] is False
                and proposal['value']['origin'] == 'server_attested'
                and proposal['value']['attempt_id'] == attempt
                and proposal['value']['model'] == 'offline-fixture'
                and proposal['value']['robot_handle'] is None, 'original offline proposal attribution')


def task_rows(raw):
    lines = raw.decode().splitlines()
    require(lines and lines[0].split() == ['TASK', 'PID', 'STATUS'], 'containerd task table changed')
    rows = {}
    for line in lines[1:]:
        key, pid, status = line.split()
        require(re.fullmatch('[0-9a-f]{32}', key) and key not in rows and pid.isdecimal()
                and status in ('CREATED', 'RUNNING', 'STOPPED', 'PAUSED', 'PAUSING', 'UNKNOWN'),
                'ambiguous container task identity')
        rows[key] = {'pid': int(pid), 'status': status}
    return rows


def process_identity(pid):
    stat = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': pid, 'start_ticks': int(stat[19]),
            'cgroup': Path('/proc', str(pid), 'cgroup').read_text().strip(),
            'executable': str(Path('/proc', str(pid), 'exe').resolve())}


def check_guest(actual, expected):
    require(actual == expected and actual['debian'] == '13.7'
            and actual['kernel'] == '6.12.111+deb13-amd64' and actual['arch'] == 'x86_64',
            'exact guest/boot identity mismatch')


def observer_socket_ready(pid):
    try:
        with socket.socket(socket.AF_UNIX) as stream:
            stream.settimeout(.2)
            stream.connect('/run/actryn/observer.sock')
            peer = struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            require(peer[0] == pid and peer[1] == 0, 'observer readiness peer identity mismatch')
        return True
    except OSError:
        return False


class Campaign(common.Campaign):
    def __init__(self, args, slot, entries):
        super().__init__(args.output, args.artifact)
        self.args, self.slot, self.entries = args, slot, entries
        self.deadline = time.monotonic() + 240
        self.faults, self.restored, self.original_logs = set(), set(), {}

    def record(self, label, value):
        require(self.index < 512, 'finite campaign record inventory')
        super().record(label, value)

    def command(self, argv, timeout=20):
        left = min(timeout, self.deadline - time.monotonic())
        require(left > 0, 'absolute campaign deadline')
        self.record('command-intent', {'argv': argv, 'automatic_retry': False})
        try:
            result = subprocess.run(argv, capture_output=True, timeout=left)
        except subprocess.SubprocessError as error:
            self.record('command-unknown', {'argv': argv, 'error': repr(error), 'automatic_retry': False})
            raise
        require(len(result.stdout) <= 65536 and len(result.stderr) <= 65536, 'command output bound')
        self.record('command-reply', {'argv': argv, 'exit': result.returncode,
                    'stdout': result.stdout.decode(errors='replace'),
                    'stderr': result.stderr.decode(errors='replace')})
        require(time.monotonic() < self.deadline, 'absolute campaign deadline')
        return result

    def cli(self, *arguments, rejected=False):
        result = self.command(['/usr/bin/actryn', 'server', *arguments])
        value = json.loads(result.stdout)
        require(result.returncode == (1 if rejected else 0), value)
        return value

    def systemctl(self, *arguments):
        result = self.command(['systemctl', *arguments], 15)
        require(result.returncode == 0, 'service operation failed')
        return result.stdout

    def tasks(self):
        result = self.command(['ctr', '--namespace', 'actryn', 'tasks', 'list'], 5)
        require(result.returncode == 0, 'containerd task inspection failed')
        return task_rows(result.stdout)

    def loaded_pins(self):
        pins = {}
        for unit in ('actryn-observer', 'actryn-launcher', 'actryn-serverd'):
            pid = int(self.systemctl('show', '--value', '-p', 'MainPID', unit))
            require(pid > 1, 'selected installed service is not running')
            identity = process_identity(pid)
            require(identity['executable'] == str(self.slot / 'bin' / unit)
                    and hashlib.sha256(Path('/proc', str(pid), 'exe').read_bytes()).hexdigest()
                    == self.entries['bin/' + unit]['sha256'], 'loaded executable differs from immutable slot')
            if unit == 'actryn-observer':
                for thread in Path('/proc', str(pid), 'task').iterdir():
                    fields = dict(line.split(':', 1) for line in (thread / 'status').read_text().splitlines())
                    require(int(fields['CapEff'], 16) == int(fields['CapPrm'], 16) == 0
                            and fields['NoNewPrivs'].strip() == '1', 'observer retained loading privilege')
            pins[unit] = identity
        return pins

    def health(self, attempt):
        binding = self.bindings[attempt]
        deadline = min(self.deadline, time.monotonic() + 1)
        request = {'op': 'health', 'attempt_id': attempt, 'boot_id': binding['boot_id'],
                   'cgroup_id': binding['cgroup_id'], 'cgroup_path': '/actryn/' + attempt}
        with socket.socket(socket.AF_UNIX) as stream:
            def read(count):
                raw = b''
                while len(raw) < count:
                    left = deadline - time.monotonic(); require(left > 0, 'observer RPC deadline')
                    stream.settimeout(left)
                    chunk = stream.recv(count - len(raw)); require(chunk, 'observer RPC EOF')
                    raw += chunk
                return raw
            stream.settimeout(max(.001, deadline - time.monotonic()))
            stream.connect('/run/actryn/observer.sock')
            require(struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1] == 0,
                    'observer IPC peer is not root')
            raw = json.dumps(request).encode()
            stream.sendall(struct.pack('!I', len(raw)) + raw)
            size, = struct.unpack('!I', read(4)); require(0 < size <= 65536, 'observer response cap')
            result = json.loads(read(size))
        require(time.monotonic() < deadline, 'observer RPC deadline')
        return result

    def gaps(self, attempt):
        result = {}
        for name, path in [('launcher', '/var/lib/actryn-server/launcher.sqlite'),
                           ('broker', '/var/lib/actryn-server/broker/state.sqlite')]:
            with contextlib.closing(sqlite3.connect('file:' + path + '?mode=ro', uri=True, timeout=.5)) as db:
                result[name] = [v[0] for v in db.execute('SELECT reason FROM gaps WHERE attempt_id=? ORDER BY reason',
                                                      (attempt,))]
        return result

    def cancel_once(self, attempt):
        require(attempt not in self.cancel_sent, 'operator cancellation retry forbidden')
        self.cancel_sent.add(attempt)
        try:
            self.cli('cancel', '--attempt', attempt)
        except (ValueError, AssertionError, subprocess.SubprocessError) as error:
            self.record('cancel-acknowledgement-unknown', {'attempt': attempt, 'error': repr(error),
                                                       'automatic_retry': False})
        wait_until(self.stores, lambda rows: all(v.get(attempt) == 'reaped' for v in rows.values()),
                   min(self.deadline, time.monotonic() + 25))
        require(attempt not in self.tasks() and not Path('/sys/fs/cgroup/actryn', attempt).exists(),
                'local resources remain charged')

    def restore_observer_once(self, mode, old, attempt):
        require(mode not in self.restored, 'observer restoration retry forbidden')
        self.restored.add(mode)
        self.systemctl('start', 'actryn-observer')
        # The actual observer binds this socket only after all fixed programs
        # attach and both threads drop capabilities. The old cgroup may already
        # be reaped, so an old registration's health is not a startup probe.
        def replacement():
            pid = int(self.systemctl('show', '--value', '-p', 'MainPID', 'actryn-observer'))
            return pid if pid > 1 and pid != old['actryn-observer']['pid'] and observer_socket_ready(pid) else None
        ready_pid = wait_until(replacement, bool, min(self.deadline, time.monotonic() + 10))
        pins = self.loaded_pins()
        require(pins['actryn-observer']['pid'] == ready_pid, 'ready observer replaced before verification')
        require(all(pins[name] == old[name] for name in ('actryn-launcher', 'actryn-serverd')),
                'observer case unexpectedly replaced another trusted service')
        self.record('observer-restored', {'case': mode, 'attempt': attempt, 'pins': pins, 'old': old})

    def fault(self, mode, attempt):
        require(mode not in self.faults, 'fault retry forbidden')
        pins = self.loaded_pins()  # All selected identities are checked immediately before mutation.
        observer = pins['actryn-observer']
        with os.fdopen(os.pidfd_open(observer['pid']), 'rb') as handle:
            require(process_identity(observer['pid']) == observer, 'observer PID changed before pinned fault')
            self.faults.add(mode)
            self.record('observer-fault-intent', {'case': mode, 'attempt': attempt, 'pins': pins,
                                                'at_monotonic_ns': time.monotonic_ns()})
            if mode == 'prestart':
                self.systemctl('stop', 'actryn-observer')
            else:
                signal.pidfd_send_signal(handle.fileno(), signal.SIGKILL)
            require(select.select([handle], [], [], min(5, max(0, self.deadline - time.monotonic())))[0],
                    'original observer death not confirmed')
        self.record('observer-death-confirmed', {'case': mode, 'original_process': observer})
        return pins

    def loss_workload(self, attempt):
        binding = self.bindings[attempt]
        cg = Path('/sys/fs/cgroup/actryn', attempt)
        require(cg.stat().st_ino == binding['cgroup_id'], 'loss workload cgroup reused')
        def enter():
            require(cg.stat().st_ino == binding['cgroup_id'], 'loss workload cgroup changed')
            (cg / 'cgroup.procs').write_text(str(os.getpid()))
        # Same fixed 30k open workload as tests/observer/guest.py. This trusted
        # helper is attributed to the cgroup; it is not claimed to be the agent.
        program = """import json,os,signal,sys
signal.alarm(15)
assert sys.stdin.buffer.read(1)==b'G'
for _ in range(30000):
 with open('/dev/null','rb'):pass
print(json.dumps({'completed_opens':30000,'pid':os.getpid()}),flush=True)
"""
        self.record('loss-workload-intent', {'attempt': attempt, 'opens': 30000, 'wall_seconds': 15,
                                           'trusted_test_helper_not_agent': True})
        process = subprocess.Popen(['/usr/bin/python3', '-c', program], preexec_fn=enter,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            identity = process_identity(process.pid)
            require(identity['cgroup'] == '0::/actryn/' + attempt, 'loss helper entered wrong cgroup')
            self.record('loss-helper-identity', identity)
            raw, errors = process.communicate(b'G', timeout=min(18, max(.001, self.deadline - time.monotonic())))
        except BaseException:
            process.kill()
            try: process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                self.record('loss-helper-cleanup-unknown', {'pid': process.pid, 'automatic_retry': False})
            raise
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None: stream.close()
        require(len(raw) <= 4096 and len(errors) <= 4096 and not errors and process.returncode == 0,
                'fixed loss workload failed; no escalation')
        require(json.loads(raw) == {'completed_opens': 30000, 'pid': identity['pid']}, 'workload did not complete')
        self.record('loss-workload-complete', {'identity': identity, 'opens': 30000})

    def evidence(self, mode, attempt, fault):
        path = self.output / (mode + '-export.json')
        self.cli('export', '--attempt', attempt, '--out', str(path))
        raw = common.read_bounded(path, 60 * 1024)
        bundle, binding = json.loads(raw), self.bindings[attempt]
        logs = {name: common.read_bounded(Path('/var/lib/actryn-server', attempt, name + '.log'), 524288)
                for name in ('stdout', 'stderr')}
        require(logs == self.original_logs[attempt], 'agent output changed after fault/cleanup')
        epoch = binding['observer']['collector_epoch']; require(str(uuid.UUID(epoch)) == epoch, 'observer epoch syntax')
        trace = Path('/var/lib/actryn-observer', epoch, attempt + '.jsonl')
        trace_raw = common.read_bounded(trace, 16 * 1024 * 1024)
        summary_path = trace.with_suffix('.summary.json')
        summary = json.loads(common.read_bounded(summary_path, 4096)) if summary_path.exists() else None
        validate_fault_export(bundle, attempt, self.artifact, binding, self.status(attempt), logs, mode, fault, summary)
        lines = trace_raw.splitlines(keepends=True)
        tail_unknown = bool(lines and not lines[-1].endswith(b'\n'))
        require(mode != 'loss' or not tail_unknown, 'synced loss trace has incomplete frame')
        records = [json.loads(line) for line in (lines[:-1] if tail_unknown else lines)]
        require(all(v['attempt_id'] == attempt and v['boot_id'] == binding['boot_id']
                    and v['collector_epoch'] == epoch and v['event']['cgroup_id'] == binding['cgroup_id']
                    and v['event']['origin'] == 'linux.tracepoint'
                    and v['event']['classification'] in ('observed', 'access_failed') for v in records),
                'raw observer trace attribution changed')
        sequences = [v['event']['sequence'] for v in records]
        require(all(type(v) is int and v > 0 for v in sequences)
                and len(sequences) == len(set(sequences)), 'raw observer sequence malformed or duplicated')
        if summary is not None:
            require(summary['retained_bytes'] == len(trace_raw)
                    and max(sequences, default=0) <= summary['status']['sequence'], 'summary/trace frontier mismatch')
        self.record('fault-evidence-verified', {'case': mode, 'attempt': attempt, 'binding': binding,
                    'gaps': self.gaps(attempt), 'export_sha256': hashlib.sha256(raw).hexdigest(),
                    'trace_sha256': hashlib.sha256(trace_raw).hexdigest(), 'trace_bytes': len(trace_raw),
                    'records': len(records), 'max_retained_sequence': max(sequences, default=0),
                    'out_of_order_pairs': sum(b < a for a, b in zip(sequences, sequences[1:])),
                    'trace_partial_tail': tail_unknown, 'summary': summary,
                    'old_trace_durability_unknown': mode != 'loss', 'execution_replay_eligible': False})

    def run(self):
        before = self.stores()
        require(all(state == 'reaped' for rows in before.values() for state in rows.values())
                and all(len(rows) <= 125 for rows in before.values()) and not self.tasks(),
                'existing active work or insufficient retained attempt inventory')
        for mode in ('prestart', 'death', 'loss'):
            attempt = self.prepare()
            binding = self.bindings[attempt]
            require(self.tasks()[attempt] == {'pid': binding['snapshot']['pid'], 'status': 'CREATED'},
                    'task already running before application start')
            common.observer_health(self.health(attempt), binding['observer'])
            stdout = Path('/var/lib/actryn-server', attempt, 'stdout.log')
            stderr = stdout.with_name('stderr.log')
            require(not common.read_bounded(stdout, 524288) and not common.read_bounded(stderr, 524288),
                    'application output before launch')
            fault = None
            if mode == 'prestart':
                old = self.fault(mode, attempt)
                reply = self.cli('launch', '--attempt', attempt, rejected=True)
                require(reply['result'] == 'error' and 'observer' in reply['message'].lower(),
                        'launch refused for unrelated cause')
                require(self.tasks().get(attempt, {}).get('status') != 'RUNNING', 'unready task started')
                self.restore_observer_once(mode, old, attempt)
            else:
                self.cli('launch', '--attempt', attempt)
                raw = wait_until(lambda: common.read_bounded(stdout, 524288),
                                 lambda value: value.endswith(b'\n') and b'preview_proposal' in value,
                                 min(self.deadline, time.monotonic() + 12))
                require(len(raw.splitlines()) == 1 and self.tasks()[attempt] == {
                        'pid': binding['snapshot']['pid'], 'status': 'RUNNING'}, 'original task identity changed')
                self.original_logs[attempt] = {'stdout': raw, 'stderr': common.read_bounded(stderr, 524288)}
                if mode == 'death':
                    old = self.fault(mode, attempt)
                else:
                    self.loaded_pins()
                    require(mode not in self.faults, 'loss workload retry forbidden')
                    self.faults.add(mode)
                    self.loss_workload(attempt)
                    fault = self.health(attempt)
                    require(fault['ready'] is False and fault['lost'] > 0
                            and fault['collector_epoch'] == binding['observer']['collector_epoch'],
                            'fixed workload did not produce actual loss; no escalation')
                gaps = wait_until(lambda: self.gaps(attempt), lambda v: all(
                        reasons == ['observer_unavailable'] for reasons in v.values()),
                        min(self.deadline, time.monotonic() + 8))
                self.record('durable-diagnostic-gap', {'case': mode, 'gaps': gaps, 'fault_health': fault})
                if mode == 'death':
                    self.restore_observer_once(mode, old, attempt)
            current_logs = {'stdout': common.read_bounded(stdout, 524288),
                            'stderr': common.read_bounded(stderr, 524288)}
            require(current_logs == self.original_logs.setdefault(attempt, current_logs),
                    'original output changed across observer fault')
            self.cancel_once(attempt)
            if mode != 'prestart':
                require(self.cli('result', '--attempt', attempt, '--key', 'preview-1')['value'] is None,
                        'closed result republished')
            self.evidence(mode, attempt, fault)
        after = self.stores()
        require(not self.tasks() and all(set(after[name]) - set(before[name]) == set(self.known)
                and all(state == 'reaped' for state in after[name].values()) for name in before),
                'automatic attempt creation or retained cleanup')
        require(time.monotonic() < self.deadline, 'absolute campaign deadline')
        self.record('PASS', {'attempts': self.known, 'scope': 'installed observer readiness/death/actual loss',
                    'automatic_launch_or_fault_retries': 0, 'diagnostic_uncertainty_not_unknown_attempt': True,
                    'overhead_measured': False, 'physical_acceptance': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-disposable-guest', action='store_true', required=True)
    for field in ('manifest', 'artifact', 'machine-id', 'boot-id'):
        parser.add_argument('--' + field, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0 and re.fullmatch('[0-9a-f]{64}', args.manifest)
            and re.fullmatch('[0-9a-f]{32}', args.machine_id)
            and str(uuid.UUID(args.boot_id)) == args.boot_id
            and args.artifact == 'sha256:c3013959f5cca4a2275fa5f26de6f030dcc011241dbbe5961993a406e2e53d45',
            'explicit reviewed disposable target pins required')
    actual = {'debian': Path('/etc/debian_version').read_text().strip(), 'kernel': os.uname().release,
              'arch': os.uname().machine, 'machine': Path('/etc/machine-id').read_text().strip(),
              'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    check_guest(actual, {'debian': '13.7', 'kernel': '6.12.111+deb13-amd64', 'arch': 'x86_64',
                        'machine': args.machine_id, 'boot': args.boot_id})
    require(Path('/etc/hostname').read_text().strip().startswith('actryn-install-server'), 'not an install guest')
    slot = Path('/opt/actryn/server/current').resolve()
    require(slot.name == 'payload' and slot.parent.name == args.manifest, 'selected installed slot changed')
    raw = common.read_bounded(slot.parent / 'manifest.json', 262144)
    manifest = json.loads(raw)
    require(hashlib.sha256(raw).hexdigest() == args.manifest and manifest['role'] == 'server', 'manifest pin')
    entries = {item['path']: item for item in manifest['files']}
    for fixed, relative in [('/usr/bin/actryn', 'bin/actryn'),
                            ('/usr/lib/actryn/observer.bpf.o', 'lib/observer.bpf.o')]:
        path = Path(fixed)
        require(path.resolve() == slot / relative and hashlib.sha256(path.read_bytes()).hexdigest()
                == entries[relative]['sha256'], 'installed CLI/BPF asset mismatch')
    require(args.output.is_absolute() and args.output.parent == Path('/var/tmp')
            and args.output.name.startswith('actryn-observer-gap-'), 'new bounded guest output required')
    os.umask(0o077); args.output.mkdir(mode=0o700, exist_ok=False)
    run = Campaign(args, slot, entries)
    try:
        run.record('preflight', {'guest': actual, 'manifest': args.manifest,
                   'loaded': run.loaded_pins(), 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   'helper_sha256': hashlib.sha256(Path(common.__file__).read_bytes()).hexdigest(),
                   'faults_authorized': ['one observer stop before start', 'one observer SIGKILL', 'one fixed 30k loop']})
        config = json.loads(common.read_bounded(Path('/etc/actryn/server.json'), 65536))
        require(args.artifact in config['artifacts'] and config['io_device'] == '254:0'
                and config['operator_uid'] == 1000, 'selected approved profile changed')
        checked = run.command(['/usr/bin/actryn-serverd', '--check-config'])
        require(checked.returncode == 0 and json.loads(checked.stdout)['result'] == 'configuration_valid',
                'installed configuration validation failed')
        run.run()
    except BaseException as error:
        run.record('FAILED', {'error': repr(error), 'attempts': run.known, 'faults_sent': sorted(run.faults),
                   'cancels_sent': sorted(run.cancel_sent), 'restorations_sent': sorted(run.restored),
                   'automatic_retry': False, 'cleanup_or_observer_restoration_unconfirmed': True})
        # Failure is retained. No hidden service restart, launch, repeated cancel or fault escalation.
        raise


if __name__ == '__main__':
    main()
