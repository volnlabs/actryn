#!/usr/bin/env python3
"""Opt-in installed-server capacity campaign on a disposable pinned Debian guest."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import time
import uuid

NAMES = {'attempt', 'runtime_binding', 'runtime_facts', 'stdout', 'stderr', 'broker'}
COVERAGE = {'process.lifecycle', 'syscall.openat', 'syscall.connect', 'syscall.bpf',
            'syscall.perf_event_open', 'syscall.mount', 'syscall.unshare', 'syscall.setns'}
COUNTERS = {'cpu.stat', 'io.stat', 'memory.current', 'memory.events', 'memory.peak',
            'pids.current', 'pids.events', 'pids.peak'}


def require(value, reason):
    if not value:
        raise AssertionError(reason)


def capacity_rejection(reply, reason):
    require(reply.get('result') == 'error' and reason in reply.get('message', ''), reply)


def active_identity(inspection, expected):
    attempt = inspection['attempt']
    snapshot = json.loads(attempt['binding'])['snapshot']
    require(attempt['state'] == 'running' and attempt['outcome'] == 'pending'
            and (attempt['id'], snapshot['pid'], snapshot['start_ticks']) == expected,
            'capacity rejection changed the active attempt')


def read_bounded(path, limit):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW), 'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'nonregular evidence file')
        data = stream.read(limit + 1)
    require(len(data) <= limit, 'evidence file exceeds bound')
    return data


def observer_health(health, initial):
    require(health['ready'] is True and health['lost'] == 0
            and health['collector_epoch'] == initial['collector_epoch']
            and type(health['sequence']) is int and health['sequence'] >= initial['sequence']
            and COVERAGE <= set(health['coverage']), 'observer loss, coverage or epoch changed')


def validate_export(bundle, attempt, artifact, binding, inspection, logs, summary, trace_bytes, started,
                    agent_check=None, expected_outcome='cancelled'):
    """Correlate exported descriptors with retained identities and independent raw files."""
    require(bundle.get('schema') == 'actryn.server.evidence.v1'
            and bundle.get('attempt_id') == attempt
            and bundle.get('execution_replay_eligible') is False
            and bundle.get('omissions') == [], 'export envelope or omission')
    entries = bundle.get('artifacts', [])
    require(len(entries) == len(NAMES) and {item['name'] for item in entries} == NAMES,
            'export needs exactly six unique artifacts')
    for item in entries:
        raw = json.dumps(item['content'], sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        require(item['bytes'] == len(raw) and item['sha256'] == 'sha256:' + hashlib.sha256(raw).hexdigest(),
                'export artifact hash')
    contents = {item['name']: item['content'] for item in entries}
    outcome = contents['attempt']
    require(outcome['id'] == attempt and outcome['artifact_digest'] == artifact
            and outcome['state'] == 'reaped' and outcome['outcome'] == expected_outcome
            and outcome['binding'] is None, 'export terminal attempt identity')
    require(contents['runtime_binding'] == binding
            and json.loads(inspection['attempt']['binding']) == binding
            and inspection['attempt']['artifact_digest'] == artifact
            and inspection['attempt']['state'] == 'reaped'
            and inspection['attempt']['outcome'] == expected_outcome
            and inspection['evidence_gaps'] == []
            and inspection['robot_binding'] is None and inspection['robot_requests'] == [],
            'retained binding or terminal inspection changed')
    require(binding['ambiguous_create'] is False and binding['cgroup_id'] > 0
            and str(uuid.UUID(binding['boot_id'])) == binding['boot_id'], 'ambiguous runtime binding')
    initial = binding['observer']
    require(str(uuid.UUID(initial['collector_epoch'])) == initial['collector_epoch'], 'observer epoch syntax')
    observer_health(initial, initial)
    snapshot = binding['snapshot']
    require(snapshot['pid'] > 1 and snapshot['start_ticks'] > 0
            and snapshot['cgroup'] == '/actryn/' + attempt
            and snapshot['uid'] == snapshot['gid'] == 65532 and snapshot['capabilities'] == 0
            and snapshot['no_new_privileges'] is True and snapshot['seccomp_mode'] == 2
            and snapshot['private_namespaces'] is True and snapshot['root_readonly'] is True
            and snapshot['network_routes'] == 0 and snapshot['unexpected_mounts'] == []
            and snapshot['device_programs'] and snapshot['memory_max'] == 268435456
            and snapshot['pids_max'] == 64 and snapshot['cpu_max'].strip() == '50000 100000'
            and snapshot['io_max'].strip() == '254:0 rbps=1048576 wbps=1048576 riops=128 wiops=128',
            'retained runtime isolation differs from selected profile')
    facts = contents['runtime_facts']
    require(facts['observer_health_unavailable'] is False, 'final observer health unavailable')
    observer_health(facts['observer'], initial)
    resources = facts['resources']
    require(resources['classification'] == 'observed_cgroup_v2_counters'
            and resources['stage'] == 'after_descendants_empty_before_runtime_delete'
            and resources['captured_boottime_ms'] >= 0 and resources['unavailable'] == []
            and set(resources['counters']) == COUNTERS
            and resources['counters']['pids.current'].strip() == '0', 'final resource evidence incomplete')
    observer_health(summary['status'], facts['observer'])
    require(summary['local_lost'] == 0 and summary['retained_bytes'] == trace_bytes <= 16 * 1024 * 1024,
            'retained observer trace incomplete')
    for name in ('stdout', 'stderr'):
        descriptor, raw = contents[name], logs[name]
        require(descriptor['classification'] == 'untrusted_agent_output_not_policy_attribution'
                and descriptor['file_complete'] is True and descriptor['source_truncated'] is False
                and descriptor['retained_bytes'] == len(raw)
                and descriptor['retained_sha256'] == 'sha256:' + hashlib.sha256(raw).hexdigest()
                and descriptor['tail_encoding'] == 'hex' and descriptor['tail'] == raw[-2048:].hex()
                and descriptor['tail_omitted_bytes'] == max(0, len(raw) - 2048), 'raw log integrity')
    broker = contents['broker']
    require(broker['classification'] == 'broker_application_policy_and_delegated_accounting'
            and broker['attempt_state'] == 'reaped' and broker['attempt_outcome'] == expected_outcome
            and broker['evidence_gaps'] == [] and broker['policy_denials'] == []
            and broker['policy_denials_retained'] == 0 and inspection['denials'] == []
            and inspection['denials_omitted'] == 0 and broker['calls'] == inspection['calls'],
            'broker evidence incomplete or changed')
    calls = broker['calls']
    if agent_check is not None:
        agent_check(logs, inspection)
        return
    require(len(calls) == (1 if started else 0)
            and all(call['publication_closed'] is True and call['state'] == 'settled'
                    and call['request_key'] == 'preview-1' and call['consumed_tokens'] == 0 for call in calls),
            'offline call not durably closed or unexpectedly dispatched')
    require(not logs['stderr'], 'unexpected agent stderr')
    if started:
        lines = logs['stdout'].splitlines()
        require(len(lines) == 1, 'original offline stdout record count changed')
        proposal = json.loads(lines[0])
        require(proposal['event'] == 'preview_proposal' and proposal['authority_issued'] is False
                and proposal['value']['origin'] == 'server_attested'
                and proposal['value']['attempt_id'] == attempt
                and proposal['value']['model'] == 'offline-fixture'
                and proposal['value']['robot_handle'] is None, 'unexpected offline proposal')
    else:
        require(not logs['stdout'], 'cancelled preparation executed')


class Campaign:
    def __init__(self, output, artifact):
        self.output, self.artifact = output, artifact
        self.known, self.cancel_sent = [], set()
        self.bindings, self.active_stdout = {}, {}
        self.index = 0

    def record(self, label, value):
        name = f'{self.index:03}-{label}.json'
        self.index += 1
        with (self.output / name).open('x') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())

    def cli(self, *arguments, rejected=False):
        command = ['/usr/bin/actryn', 'server', *arguments]
        self.record('intent', {'command': command, 'automatic_retry': False})
        try:
            result = subprocess.run(command, capture_output=True, timeout=20)
        except subprocess.TimeoutExpired as error:
            self.record('unknown', {'command': command, 'error': repr(error),
                        'stdout': (error.stdout or b'')[:65536].decode(errors='replace'),
                        'stderr': (error.stderr or b'')[:65536].decode(errors='replace')})
            raise
        self.record('reply', {'command': command, 'returncode': result.returncode,
                    'stdout': result.stdout[:65536].decode(errors='replace'),
                    'stderr': result.stderr[:65536].decode(errors='replace')})
        require(len(result.stdout) <= 65536 and len(result.stderr) <= 65536, 'CLI output bound')
        reply = json.loads(result.stdout)
        require(result.returncode == (1 if rejected else 0), reply)
        return reply

    def prepare(self):
        reply = self.cli('prepare', '--artifact', self.artifact)
        inspection = reply['inspection']
        attempt = inspection['attempt']['id']
        require(re.fullmatch('[0-9a-f]{32}', attempt) and attempt not in self.known, 'new attempt identity')
        self.known.append(attempt)
        self.record('known-attempts', self.known)
        require(inspection['attempt']['state'] == 'prepared', inspection)
        binding = json.loads(inspection['attempt']['binding'])
        require(binding['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
                and inspection['attempt']['artifact_digest'] == self.artifact, 'preparation identity')
        self.bindings[attempt] = binding
        self.record('prepared-binding', {'attempt': attempt, 'binding': binding})
        return attempt

    def status(self, attempt):
        return self.cli('status', '--attempt', attempt)['inspection']

    def cancel(self, attempt):
        if attempt in self.cancel_sent:
            return False
        self.cancel_sent.add(attempt)  # Lost replies must not cause cleanup to resend.
        self.cli('cancel', '--attempt', attempt)
        return True

    def stores(self):
        result = {}
        for name, path in [('launcher', '/var/lib/actryn-server/launcher.sqlite'),
                           ('broker', '/var/lib/actryn-server/broker/state.sqlite')]:
            with contextlib.closing(sqlite3.connect('file:' + path + '?mode=ro', uri=True, timeout=1)) as db:
                result[name] = dict(db.execute('SELECT id,state FROM attempts'))
        return result

    def retired(self, attempt):
        deadline = time.monotonic() + 20
        while True:
            state = self.stores()
            if all(rows.get(attempt) == 'reaped' for rows in state.values()):
                require(not Path('/sys/fs/cgroup/actryn', attempt).exists(), 'retained cgroup')
                self.record('retired', {'attempt': attempt, 'stores': state})
                return
            require(time.monotonic() < deadline, {'retirement_timeout': attempt, 'stores': state})
            time.sleep(.1)

    def stable(self, identity):
        inspection = self.status(identity[0])
        active_identity(inspection, identity)
        require(json.loads(inspection['attempt']['binding']) == self.bindings[identity[0]],
                'immutable active binding changed')
        stat = Path(f'/proc/{identity[1]}/stat').read_text().rsplit(')', 1)[1].split()
        require(int(stat[19]) == identity[2], 'active process replaced')
        raw = read_bounded(Path('/var/lib/actryn-server', identity[0], 'stdout.log'), 524288)
        require(raw == self.active_stdout.setdefault(identity[0], raw), 'original active stdout changed')
        rows = [json.loads(line) for line in raw.splitlines()]
        proposals = [row for row in rows if row.get('event') == 'preview_proposal']
        require(len(proposals) == 1 and proposals[0]['value']['origin'] == 'server_attested',
                'active agent output changed or repeated')

    def export(self, attempt, agent_check=None):
        path = self.output / (attempt + '-export.json')
        self.cli('export', '--attempt', attempt, '--out', str(path))
        bundle_bytes = read_bounded(path, 60 * 1024)
        bundle = json.loads(bundle_bytes)
        # Check the envelope before reading identities or files chosen by it.
        require(bundle.get('schema') == 'actryn.server.evidence.v1'
                and len(bundle.get('artifacts', [])) == 6, 'incomplete export')
        binding = self.bindings[attempt]
        epoch = binding['observer']['collector_epoch']
        require(str(uuid.UUID(epoch)) == epoch, 'observer epoch path')
        logs = {name: read_bounded(Path('/var/lib/actryn-server', attempt, name + '.log'), 524288)
                for name in ('stdout', 'stderr')}
        require(not any(Path('/var/lib/actryn-server', attempt, name + '.truncated').exists()
                        for name in logs), 'raw source truncated')
        if attempt in self.active_stdout:
            require(logs['stdout'] == self.active_stdout[attempt], 'original stdout changed at retirement')
        trace = Path('/var/lib/actryn-observer', epoch, attempt + '.jsonl')
        trace_raw = read_bounded(trace, 16 * 1024 * 1024)
        summary = json.loads(read_bounded(trace.with_suffix('.summary.json'), 4096))
        validate_export(bundle, attempt, self.artifact, binding, self.status(attempt), logs,
                        summary, len(trace_raw), attempt in self.active_stdout, agent_check)
        require(not Path('/sys/fs/cgroup/actryn', attempt).exists(), 'export retained cgroup')
        self.record('export-verified', {'attempt': attempt,
                    'bundle_sha256': hashlib.sha256(bundle_bytes).hexdigest(),
                    'observer_trace_sha256': hashlib.sha256(trace_raw).hexdigest(),
                    'summary': summary, 'binding': binding,
                    'logs': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                             for name, raw in logs.items()}, 'execution_replay_eligible': False})

    def run(self):
        before = self.stores()
        require(all(state == 'reaped' for rows in before.values() for state in rows.values()),
                'existing outstanding attempts prohibit this campaign')
        first = self.prepare()
        capacity_rejection(self.cli('prepare', '--artifact', self.artifact, rejected=True),
                           'preparation capacity exhausted')
        require(self.status(first)['attempt']['state'] == 'prepared', 'preparation changed')
        launched = self.cli('launch', '--attempt', first)['inspection']
        snapshot = json.loads(launched['attempt']['binding'])['snapshot']
        identity = (first, snapshot['pid'], snapshot['start_ticks'])
        deadline = time.monotonic() + 12
        stdout = Path('/var/lib/actryn-server', first, 'stdout.log')
        while True:
            raw = stdout.read_bytes()
            if b'preview_proposal' in raw and raw.endswith(b'\n'):
                break
            require(time.monotonic() < deadline, 'offline proposal unavailable')
            time.sleep(.05)
        self.stable(identity)
        second = self.prepare()
        capacity_rejection(self.cli('prepare', '--artifact', self.artifact, rejected=True),
                           'preparation capacity exhausted')
        capacity_rejection(self.cli('launch', '--attempt', second, rejected=True), 'active capacity exhausted')
        require(self.status(second)['attempt']['state'] == 'prepared', 'rejected start changed preparation')
        require(not Path('/var/lib/actryn-server', second, 'stdout.log').read_bytes(), 'rejected agent ran')
        self.stable(identity)
        self.cancel(second); self.retired(second)
        third = self.prepare()
        self.stable(identity)
        self.cancel(third); self.retired(third)
        self.stable(identity)
        self.cancel(first); self.retired(first)
        for attempt in self.known:
            self.export(attempt)
        after = self.stores()
        for name in before:
            require(set(after[name]) - set(before[name]) == set(self.known), 'denied request leaked accounting')
            require(all(state == 'reaped' for state in after[name].values()), 'outstanding accounting')
        self.record('PASS', {'test': 'installed-preparation-and-active-capacity', 'attempts': self.known,
                    'active_identity': identity, 'automatic_mutation_retries': 0,
                    'scope': 'one active plus one staged; refusal preserves running identity; explicit cleanup',
                    'retirement_stall_injected': False, 'broker_call_pressure_tested': False,
                    'physical_acceptance': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0 and os.uname().release == '6.12.111+deb13-amd64'
            and os.uname().machine == 'x86_64'
            and Path('/etc/hostname').read_text().strip().startswith('actryn-install-server'), 'disposable installed guest required')
    require(re.fullmatch('sha256:[0-9a-f]{64}', args.artifact)
            and re.fullmatch('[0-9a-f]{64}', args.manifest), 'artifact/manifest pins')
    slot = Path('/opt/actryn/server/current').resolve()
    require(slot.parent.name == args.manifest and slot.name == 'payload', 'installed slot changed')
    manifest = json.loads((slot.parent / 'manifest.json').read_bytes())
    require(hashlib.sha256((slot.parent / 'manifest.json').read_bytes()).hexdigest() == args.manifest,
            'manifest digest')
    require(manifest['role'] == 'server', 'installed role changed')
    entries = {item['path']: item for item in manifest['files']}
    pins = {}
    for unit, name in [('actryn-serverd', 'actryn-serverd'), ('actryn-launcher', 'actryn-launcher'),
                       ('actryn-observer', 'actryn-observer')]:
        pid = int(subprocess.check_output(['systemctl', 'show', '--value', '-p', 'MainPID', unit]))
        require(pid > 1, 'installed service not running')
        require(Path(f'/proc/{pid}/exe').resolve() == slot / 'bin' / name,
                'service executable is outside immutable selected slot')
        pins[unit] = hashlib.sha256(Path(f'/proc/{pid}/exe').read_bytes()).hexdigest()
        require(pins[unit] == entries['bin/' + name]['sha256'], 'service differs from installed manifest')
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    run = Campaign(args.output, args.artifact)
    run.record('campaign', {'manifest': args.manifest, 'artifact': args.artifact, 'binaries': pins,
               'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    try:
        run.run()
    except BaseException as error:
        run.record('FAILED', {'error': repr(error), 'known_attempts': run.known,
                   'cancel_already_attempted': sorted(run.cancel_sent), 'automatic_retry': False})
        for attempt in reversed(run.known):
            try:
                run.cancel(attempt)
                run.retired(attempt)
            except BaseException as cleanup:
                run.record('cleanup-unconfirmed', {'attempt': attempt, 'error': repr(cleanup)})
        raise


if __name__ == '__main__':
    main()
