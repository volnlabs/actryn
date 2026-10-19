#!/usr/bin/env python3
"""One installed-server attempt: existing harmless forbidden device, then real cgroup OOM."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import select
import sqlite3
import stat
import subprocess
import time
import uuid

import guest_capacity as common
import pressure_fixture as fixture

require = common.require
DEVICE = 'actryn-denied-full'
ABSENT = 'actryn-intentionally-absent'
TABLES = ('attempts', 'calls', 'gaps', 'runtime_evidence', 'denials', 'robot_bindings', 'robot_requests')
DATABASES = {'launcher': Path('/var/lib/actryn-server/launcher.sqlite'),
             'broker': Path('/var/lib/actryn-server/broker/state.sqlite')}


def counters(raw):
    result = {}
    for line in raw.splitlines():
        parts = line.split()
        require(len(parts) == 2 and parts[0] not in result and parts[1].isdigit(), 'malformed memory.events')
        result[parts[0]] = int(parts[1])
    require({'max', 'oom', 'oom_kill'} <= result.keys(), 'missing OOM counters')
    return result


def validate_oom(initial, final, outcome, limit, swap):
    before, after = counters(initial), counters(final)
    require(limit.strip() == '268435456' and swap.strip() == '0', 'memory profile changed')
    require(all(before[key] == 0 and after[key] > 0 for key in ('max', 'oom', 'oom_kill'))
            and outcome == 'exited:137', 'no fresh cgroup-limit OOM kill and natural SIGKILL exit')


def validate_node(node):
    require(node['mode'] == stat.S_IFCHR | 0o666 and node['uid'] == node['gid'] == 0
            and node['major'] == 1 and node['minor'] == 7 and node['nlink'] == 1,
            'dummy must be existing root-owned char 1:7 mode0666, not a DAC/missing-path fixture')


def validate_trace(rows, attempt, binding, final_sequence=None):
    require(0 < len(rows) <= 32768, 'trace record bound')
    # Different CPUs can reserve ring-buffer records after assigning sequence IDs.
    # Check the complete set, not an invented global delivery/timestamp order.
    sequence = [row['event']['sequence'] for row in rows]
    require(sorted(sequence) == list(range(1, len(rows) + 1))
            and (final_sequence is None or final_sequence == len(rows)), 'source sequence gap/duplicate/tail')
    for row in rows:
        e = row['event']
        require(row['attempt_id'] == attempt and row['boot_id'] == binding['boot_id']
                and row['collector_epoch'] == binding['observer']['collector_epoch']
                and e['cgroup_id'] == binding['cgroup_id'] and e['origin'] == 'linux.tracepoint'
                and type(e['monotonic_ns']) is int and e['monotonic_ns'] >= 0,
                'trace identity, ordering or source gap')
    rows = sorted(rows, key=lambda row: row['event']['sequence'])
    parent = binding['snapshot']['pid']
    execs = [row['event']['sequence'] for row in rows
             if row['event']['kind'] == 4 and row['event']['pid'] == parent]
    require(execs, 'agent exec not retained')
    children = [row['event']['related_pid'] for row in rows
                if row['event']['kind'] == 3 and row['event']['pid'] == parent
                and row['event']['sequence'] > execs[-1]]
    require(len(children) == 1 and children[0] > 1, 'expected exactly one reviewed probe child')
    child = children[0]
    observed = [row['event'] for row in rows if row['event']['pid'] == child]
    opens = [e for e in observed if e['syscall'] == 257]
    require(len(opens) == 6 and [e['kind'] for e in opens] == [1, 2, 1, 2, 1, 2]
            and all(e['tid'] == child for e in opens)
            and [e['monotonic_ns'] for e in opens] == sorted(e['monotonic_ns'] for e in opens),
            'child openat sequence incomplete')
    results = [e['result'] for e in opens if e['kind'] == 2]
    require(results[0] >= 0 and results[1:] == [-2, -1]
            and [e['classification'] for e in opens if e['kind'] == 2]
            == ['observed', 'access_failed', 'access_failed'], 'control/ENOENT/EPERM not distinguished')
    exits = [e for e in observed if e['kind'] == 5]
    require(len(exits) == 1 and exits[0]['sequence'] > opens[-1]['sequence'], 'probe child did not exit')
    parent_exits = [row['event'] for row in rows if row['event']['pid'] == parent
                    and row['event']['tid'] == parent and row['event']['kind'] == 5]
    require(len(parent_exits) == 1 and parent_exits[0]['sequence'] > execs[-1]
            and parent_exits[0]['sequence'] > exits[0]['sequence'],
            'natural parent leader exit not retained after agent exec and child')
    return {'child_host_pid': child, 'results': results,
            'classification': 'access_failed_not_policy_origin_event'}


def validate_agent(logs, inspection):
    require(not logs['stderr'] and not inspection['calls'], 'unexpected stderr/broker work')
    lines = [json.loads(line) for line in logs['stdout'].splitlines()]
    require(len(lines) == 2 and lines[0]['event'] == 'device_probe'
            and lines[0]['major'] == 1 and lines[0]['minor'] == 7 and lines[0]['mode'] == 438
            and lines[0]['results'][0] >= 0 and lines[0]['results'][1:] == [-2, -1]
            and lines[1] == {'event': 'memory_begin', 'bytes': 536870912, 'page_bytes': 4096},
            'reviewed agent stages incomplete')
    return lines[0]['results']


def snapshot(paths=DATABASES):
    """Read the common schema in BOTH stores; retain every old row, including output bytes."""
    result = {}
    for name, path in paths.items():
        require(stat.S_ISREG(path.lstat().st_mode), 'nonregular database')
        with contextlib.closing(sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            end = time.monotonic() + 2
            db.set_progress_handler(lambda: time.monotonic() >= end, 1000)
            db.execute('BEGIN')
            require(db.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'database integrity')
            tables = {}
            for table in TABLES:
                rows = db.execute(f'SELECT * FROM {table} ORDER BY rowid LIMIT 8193').fetchall()
                require(len(rows) <= 8192, 'table row bound')
                tables[table] = [{key: {'blob_hex': value.hex()} if isinstance(value, bytes) else value
                                  for key, value in dict(row).items()} for row in rows]
            result[name] = tables
    require(len(json.dumps(result).encode()) <= 16 * 1024 * 1024, 'history byte bound')
    return result


def quiescent(rows):
    for tables in rows.values():
        require(len(tables['attempts']) <= 128 and all(a['state'] == 'reaped' for a in tables['attempts'])
                and all(c['state'] in ('settled', 'cancelled') and c['publication_closed'] == 1
                        for c in tables['calls'])
                and all(r['outstanding'] == 0 for r in tables['robot_requests']), 'outstanding work')
    require(not fixture.command(['ctr', '--namespace', 'actryn', 'tasks', 'list', '--quiet']).strip(),
            'containerd task remains')
    for path in (Path('/sys/fs/cgroup/actryn'), Path('/run/actryn/brokers')):
        require(path.is_dir(), 'runtime root absent')
        require(not any(v.is_dir() for v in path.iterdir()), 'runtime child directory remains')


def validate_history(before, after, attempt):
    require(set(before) == set(after) == {'launcher', 'broker'}, 'store inventory changed')
    for name, old in before.items():
        new = after[name]
        require(set(new) == set(old) == set(TABLES), 'table inventory changed')
        old_ids = {r['id'] for r in old['attempts']}
        require(attempt not in old_ids and len(new['attempts']) == len(old_ids) + 1
                and {r['id'] for r in new['attempts']} == old_ids | {attempt}, 'unexpected attempt allocation')
        require([r for r in new['attempts'] if r['id'] in old_ids] == old['attempts'], 'old attempt changed')
        current = next(r for r in new['attempts'] if r['id'] == attempt)
        require(current['state'] == 'reaped' and current['outcome'] == 'exited:137', 'unexpected final outcome')
        for table in old.keys() - {'attempts'}:
            if table == 'runtime_evidence':
                require([r for r in new[table] if r['attempt_id'] != attempt] == old[table], 'old evidence changed')
                require(sum(r['attempt_id'] == attempt for r in new[table]) == (1 if name == 'launcher' else 0),
                        'runtime evidence inventory')
            else:
                require(new[table] == old[table], 'old rows changed or unexpected broker/Robot work')


def task_alive(pidfd, snapshot):
    poll = select.poll(); poll.register(pidfd, select.POLLIN)
    require(not poll.poll(0), 'prepared task exited')
    proc = Path('/proc', str(snapshot['pid']))
    require(int(proc.joinpath('stat').read_text().rsplit(')', 1)[1].split()[19]) == snapshot['start_ticks']
            and proc.joinpath('cgroup').read_text().strip() == '0::' + snapshot['cgroup'], 'task lifetime changed')


def expose_device(binding):
    """No new mount/policy: insert only this harmless node in the stopped task's existing tmpfs."""
    s = binding['snapshot']; pidfd = os.pidfd_open(s['pid'])
    try:
        task_alive(pidfd, s)
        mountinfo = Path('/proc', str(s['pid']), 'mountinfo').read_text()
        dev = [line.split() for line in mountinfo.splitlines() if line.split()[4] == '/dev']
        require(len(dev) == 1 and dev[0][dev[0].index('-')+1] == 'tmpfs'
                and 'rw' in dev[0][5].split(',') and 'nodev' not in dev[0][5].split(','), 'unexpected /dev mount')
        # Deliberately follow only the kernel procfs magic root for the pinned task.
        rootfd = os.open(f'/proc/{s["pid"]}/root', os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            devfd = os.open('dev', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=rootfd)
            try:
                task_alive(pidfd, s)
                for name in (DEVICE, ABSENT):
                    try: os.stat(name, dir_fd=devfd, follow_symlinks=False)
                    except FileNotFoundError: pass
                    else: raise AssertionError('probe path already exists')
                os.mknod(DEVICE, stat.S_IFCHR | 0o666, os.makedev(1, 7), dir_fd=devfd)
                os.chmod(DEVICE, 0o666, dir_fd=devfd, follow_symlinks=False)
                m = os.stat(DEVICE, dir_fd=devfd, follow_symlinks=False)
                node = dict(mode=m.st_mode, uid=m.st_uid, gid=m.st_gid, nlink=m.st_nlink,
                            major=os.major(m.st_rdev), minor=os.minor(m.st_rdev), ino=m.st_ino, dev=m.st_dev)
                validate_node(node)
                control = subprocess.run(['/usr/bin/python3', '-c',
                    'import os,sys; assert os.getuid()==os.getgid()==65532; '
                    'fd=os.open("actryn-denied-full",os.O_RDONLY|os.O_NOFOLLOW,dir_fd=int(sys.argv[1])); '
                    'assert os.read(fd,1)==b"\\0"; os.close(fd); print("CONTROL_OPEN_PASS")', str(devfd)],
                    pass_fds=(devfd,), user=65532, group=65532, extra_groups=[],
                    capture_output=True, timeout=2)
                require(control.returncode == 0 and control.stdout == b'CONTROL_OPEN_PASS\n'
                        and not control.stderr, 'same-UID outside-cgroup control open failed')
                task_alive(pidfd, s)
                return {'node': node, 'mountinfo': mountinfo, 'control_uid': 65532,
                        'control_open': 'PASS', 'policy_modified': False, 'extra_mounts': False}
            finally: os.close(devfd)
        finally: os.close(rootfd)
    finally: os.close(pidfd)


class Campaign(common.Campaign):
    def __init__(self, output, artifact):
        super().__init__(output, artifact)
        self.results = {'existing_device': 'NOT_RUN', 'memory_limit_kill': 'NOT_RUN'}

    def cleanup_failure(self):
        for attempt in self.known:
            try:
                state = self.status(attempt)['attempt']['state']
                if state not in ('retiring', 'reaped'):
                    try: self.cancel(attempt)
                    except BaseException as error:
                        self.record('cleanup-unconfirmed', {'attempt': attempt, 'error': repr(error),
                                    'cancel_already_attempted': True, 'automatic_retry': False})
                # A lost mutation acknowledgement still permits bounded read-only convergence.
                self.retired(attempt)
                self.record('cleanup-observed', {'attempt': attempt, 'reaped': True})
            except BaseException as error:
                self.record('cleanup-unconfirmed', {'attempt': attempt, 'error': repr(error),
                            'cancel_already_attempted': attempt in self.cancel_sent, 'automatic_retry': False})

    def run(self):
        before = snapshot(); self.record('baseline', before); quiescent(before)
        require(all(len(v['attempts']) < 128 for v in before.values()), 'retained history full')
        attempt = self.prepare(); binding = self.bindings[attempt]
        cg = Path('/sys/fs/cgroup/actryn', attempt)
        require(cg.stat().st_ino == binding['cgroup_id'], 'cgroup lifetime changed')
        initial = {name: common.read_bounded(cg/name, 2048).decode()
                   for name in ('memory.events', 'memory.max', 'memory.swap.max')}
        require(all(v == 0 for v in counters(initial['memory.events']).values())
                and initial['memory.max'].strip() == '268435456' and initial['memory.swap.max'].strip() == '0',
                'unexpected prepared memory limits/events')
        self.record('initial-memory', initial)
        device = expose_device(binding); self.record('device-exposed', device)
        self.results = {key: 'PENDING_FINAL_EVIDENCE' for key in self.results}
        self.cli('launch', '--attempt', attempt)
        self.retired(attempt)  # Bounded read-only polling; success sends no Cancel.
        final = self.status(attempt)
        path = self.output / (attempt + '-export.json')
        self.cli('export', '--attempt', attempt, '--out', str(path))
        bundle = json.loads(common.read_bounded(path, 60 * 1024))
        logs = {name: common.read_bounded(Path('/var/lib/actryn-server', attempt, name + '.log'), 524288)
                for name in ('stdout', 'stderr')}
        epoch = binding['observer']['collector_epoch']
        require(str(uuid.UUID(epoch)) == epoch, 'observer path identity')
        trace = Path('/var/lib/actryn-observer', epoch, attempt + '.jsonl')
        raw = common.read_bounded(trace, 16 * 1024 * 1024)
        summary_raw = common.read_bounded(trace.with_suffix('.summary.json'), 4096)
        summary = json.loads(summary_raw)
        for name, data in {'observer.jsonl': raw, 'observer.summary.json': summary_raw,
                           **{name+'.log': value for name, value in logs.items()}}.items():
            fixture.write_new(self.output/name, data)
        self.record('retained-files', {'observer_trace': str(trace), 'trace_sha256': hashlib.sha256(raw).hexdigest(),
                    'summary': summary, 'summary_sha256': hashlib.sha256(summary_raw).hexdigest(),
                    'logs': {name: {'bytes': len(v), 'sha256': hashlib.sha256(v).hexdigest()} for name, v in logs.items()}})
        outcome = final['attempt']['outcome']
        require(re.fullmatch('exited:[0-9]{1,3}', outcome), 'not a natural task exit')
        common.validate_export(bundle, attempt, self.artifact, binding, final, logs, summary, len(raw), True,
                               validate_agent, expected_outcome=outcome)
        require(raw.endswith(b'\n'), 'truncated observer JSONL')
        proof = validate_trace([json.loads(line) for line in raw.splitlines()], attempt, binding,
                               summary['status']['sequence'])
        require(proof['results'] == validate_agent(logs, final), 'agent/kernel open results disagree')
        self.results['existing_device'] = 'PASS'
        self.record('device-PASS', {**proof, 'node': device['node'], 'stdout_is_untrusted': True})
        facts = next(v['content'] for v in bundle['artifacts'] if v['name'] == 'runtime_facts')
        try:
            validate_oom(initial['memory.events'], facts['resources']['counters']['memory.events'],
                         outcome, initial['memory.max'], initial['memory.swap.max'])
        except BaseException:
            self.results['memory_limit_kill'] = 'FAILED'
            raise
        self.results['memory_limit_kill'] = 'PASS'
        self.record('memory-PASS', {'initial': initial, 'final_resources': facts['resources'],
                                  'outcome': final['attempt']['outcome'], 'cancel_sent': False})
        after = snapshot(); self.record('final-state', after)
        validate_history(before, after, attempt); quiescent(after)
        return attempt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('artifact', 'manifest', 'boot-id', 'agent-sha256'): p.add_argument('--'+key, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    require(re.fullmatch('sha256:[0-9a-f]{64}', args.artifact)
            and re.fullmatch('[0-9a-f]{64}', args.agent_sha256), 'artifact/agent pin')
    initial = fixture.preflight(args.manifest)
    require(initial['boot_id'] == args.boot_id and all(not initial[k] for k in
            ('library_users', 'library_executable_users', 'legacy_library_users'))
            and not fixture.DROPIN.exists() and not (fixture.CONTROL/'control').exists(), 'boot or instrumented launcher')
    slot = Path('/opt/actryn/server/current').resolve()
    manifest = json.loads(fixture.protected_file(slot.parent/'manifest.json', 1024*1024))
    cli = next(v for v in manifest['files'] if v['path'] == 'bin/actryn')
    require(Path('/usr/bin/actryn').resolve() == slot/'bin/actryn'
            and hashlib.sha256(fixture.protected_file(slot/'bin/actryn', 32*1024*1024)).hexdigest() == cli['sha256'],
            'installed CLI mismatch')
    config = json.loads(fixture.protected_file('/etc/actryn/server.json', 65536))
    approved = config['artifacts'][args.artifact]
    root = Path('/var/lib/actryn-artifacts', args.artifact[7:], 'rootfs')
    require(approved == {'rootfs': str(root), 'argv': ['/bin/agent']}
            and hashlib.sha256(fixture.protected_file(root/'bin/agent', 8*1024*1024)).hexdigest() == args.agent_sha256,
            'approved diagnosis payload mismatch')
    fixture.protected_directory(args.output.parent)
    os.umask(0o077); args.output.mkdir(mode=0o700, exist_ok=False)
    run = Campaign(args.output, args.artifact)
    run.record('campaign', {'initial': initial, 'agent_sha256': args.agent_sha256, 'artifact': args.artifact,
               'sources': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                           for name in ('guest_diagnosis.py', 'guest_capacity.py', 'pressure_fixture.py', 'diagnosis_agent.c')}})
    try:
        attempt = run.run()
        current = fixture.preflight(args.manifest)
        require(current == initial, 'installed services/configuration changed during diagnosis')
        run.record('installed-state-unchanged', current)
        run.record('PASS', {'attempt': attempt, 'results': run.results, 'automatic_retry': False,
                   'test_only_dev_tmpfs_node': True, 'physical_qualification': False,
                   'execution_replay_eligible': False})
    except BaseException as error:
        run.record('FAILED', {'error': repr(error), 'results': run.results, 'known_attempts': run.known,
                    'cancel_already_attempted': sorted(run.cancel_sent), 'automatic_retry': False})
        run.cleanup_failure()
        try: run.record('failure-state', snapshot())
        except BaseException as error: run.record('failure-state-unavailable', {'error': repr(error)})
        raise


if __name__ == '__main__': main()
