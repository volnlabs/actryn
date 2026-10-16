#!/usr/bin/env python3
"""Eight fixed standalone observer OFF/ON trials; opt-in disposable guest only."""
import argparse
import contextlib
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import select
import socket
import sqlite3
import statistics
import struct
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'apps/server/tests'))
import guest_observer_gap as gap
import guest_capacity as common

require = common.require
ORDER = ('OFF', 'ON', 'ON', 'OFF', 'ON', 'OFF', 'OFF', 'ON')
WORKLOAD = """import json,os,resource,signal,sys,time
signal.alarm(15)
print(json.dumps({'phase':'READY','pid':os.getpid()}),flush=True)
assert sys.stdin.buffer.read(1)==b'G'
before=resource.getrusage(resource.RUSAGE_SELF);start=time.monotonic_ns()
for _ in range(30000):
 with open('/dev/null','rb'):pass
wall=time.monotonic_ns()-start;after=resource.getrusage(resource.RUSAGE_SELF)
print(json.dumps({'phase':'DONE','pid':os.getpid(),'opens':30000,'wall_ns':wall,
 'user_cpu_ns':round((after.ru_utime-before.ru_utime)*1e9),
 'system_cpu_ns':round((after.ru_stime-before.ru_stime)*1e9)}),flush=True)
assert sys.stdin.buffer.read(1)==b'X'
"""
WORKLOAD_SHA256 = hashlib.sha256(WORKLOAD.encode()).hexdigest()


def analyze(trials):
    require(len(trials) == 8 and all(v['index'] == i and v['mode'] == ORDER[i]
            and v['status'] in ('complete', 'failed', 'not_run', 'started') for i, v in enumerate(trials)),
            'all eight fixed trial outcomes required in original order')
    complete = [v for v in trials if v['status'] == 'complete']
    cohorts = ('workload_sha256', 'profile', 'boot_id', 'manifest')
    if complete:
        require(all(all(v[k] == complete[0][k] for k in cohorts) for v in complete), 'cohort mismatch')
    require(len({v['attempt'] for v in complete}) == len(complete), 'reused trial cgroup identity')
    for trial in complete:
        require(trial['workload_sha256'] == WORKLOAD_SHA256 and trial['profile'] == 'fixed-standalone-30k'
                and trial['opens'] == 30000 and trial['retired'] is True
                and type(trial['wall_ns']) is int and trial['wall_ns'] > 0
                and all(type(trial[k]) is int and trial[k] >= 0 for k in ('user_cpu_ns', 'system_cpu_ns')),
                'invalid timing/completion sample')
        loss = trial['loss']
        if trial['mode'] == 'OFF':
            require(loss is None, 'OFF has no reader; loss is unavailable, not zero')
        else:
            require(type(loss['lost']) is int and type(loss['sequence']) is int
                    and 0 <= loss['lost'] <= loss['sequence'] and type(loss['ready']) is bool
                    and loss['ready'] == (loss['lost'] == 0), 'loss/readiness inconsistent')
    pairs = []
    for i in range(0, 8, 2):
        pair = {'indices': [i, i + 1], 'wall_delta_ns': None, 'wall_relative_delta': None,
                'user_cpu_delta_ns': None, 'system_cpu_delta_ns': None}
        if all(v['status'] == 'complete' for v in trials[i:i + 2]):
            off, on = sorted(trials[i:i + 2], key=lambda v: v['mode'])
            pair.update(wall_delta_ns=on['wall_ns'] - off['wall_ns'],
                        wall_relative_delta=(on['wall_ns'] - off['wall_ns']) / off['wall_ns'],
                        user_cpu_delta_ns=on['user_cpu_ns'] - off['user_cpu_ns'],
                        system_cpu_delta_ns=on['system_cpu_ns'] - off['system_cpu_ns'])
        pairs.append(pair)
    distribution = {}
    for mode in ('OFF', 'ON'):
        values = [v['wall_ns'] for v in complete if v['mode'] == mode]
        distribution[mode] = {'n': len(values), 'wall_ns': None if not values else {
            'min': min(values), 'median': statistics.median(values), 'max': max(values)}}
    return {'planned': 8, 'complete': len(complete), 'trials': trials, 'pairs': pairs,
            'distribution': distribution, 'superiority_inference': False, 'wcet_claim': False,
            'full_installed_agent_overhead_established': False}


def read_line(fd, deadline):
    raw = bytearray()
    while True:
        left = deadline - time.monotonic()
        require(left > 0 and select.select([fd], [], [], left)[0] and time.monotonic() < deadline,
                'workload framing deadline')
        chunk = os.read(fd, 2049 - len(raw)); require(chunk, 'workload framing EOF')
        require(time.monotonic() < deadline, 'workload framing deadline')
        raw.extend(chunk); require(len(raw) <= 2048, 'workload frame too large')
        if b'\n' in raw:
            require(raw.count(b'\n') == 1 and raw.endswith(b'\n'), 'one workload frame required')
            value = json.loads(raw)
            require(time.monotonic() < deadline, 'workload framing deadline')
            return value
        require(len(raw) < 2048, 'workload frame too large')


def program_ids(pid):
    entries = list(Path('/proc', str(pid), 'fdinfo').iterdir())
    require(len(entries) <= 64, 'observer FD inventory exceeds installed bound')
    ids = set()
    for entry in entries:
        try: raw = common.read_bounded(entry, 8192).decode()
        except FileNotFoundError: continue  # An unrelated, transient accepted IPC FD.
        for value in re.findall(r'^prog_id:\s*([0-9]+)$', raw, re.M): ids.add(int(value))
    require(len(ids) == 5 and all(0 < value <= 0xffffffff for value in ids), 'five actual observer programs required')
    return sorted(ids)


def observer_program_absent(program_id):
    # Exact Debian amd64 Linux ABI: read-only BPF_PROG_GET_FD_BY_ID, not detach.
    attr = ctypes.create_string_buffer(struct.pack('III', program_id, 0, 0))
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(321, 13, ctypes.byref(attr), 12)
    if result >= 0:
        os.close(result)
        return False  # Conservative: even an unattached object held elsewhere blocks OFF.
    error = ctypes.get_errno()
    require(error == errno.ENOENT, 'cannot establish observer program absence: errno=' + str(error))
    return True


def cpu_ticks(pid):
    fields = common.read_bounded(Path('/proc', str(pid), 'stat'), 8192).decode().rsplit(')', 1)[1].split()
    return {'user': int(fields[11]), 'system': int(fields[12]), 'start': int(fields[19])}


class Campaign(gap.Campaign):
    def __init__(self, args, slot, entries):
        args.artifact = 'standalone-30k-open-workload-not-an-agent'
        super().__init__(args, slot, entries)
        self.deadline = time.monotonic() + 360
        self.observer = None
        self.observer_ids = set()
        self.trials = [{'index': i, 'mode': mode, 'status': 'not_run'} for i, mode in enumerate(ORDER)]

    def command(self, argv, timeout=20):
        self.record('command-intent', {'argv': argv, 'automatic_retry': False})
        # Journal latency does not extend eligibility to issue the command.
        left = min(timeout, self.deadline - time.monotonic())
        require(left > 0, 'absolute campaign deadline')
        try:
            result = subprocess.run(argv, capture_output=True, timeout=left)
        except subprocess.SubprocessError as error:
            self.record('command-unknown', {'argv': argv, 'error': repr(error), 'automatic_retry': False})
            raise
        require(len(result.stdout) <= 65536 and len(result.stderr) <= 65536, 'command output bound')
        self.record('command-reply', {'argv': argv, 'exit': result.returncode,
                    'stdout': result.stdout.decode(errors='replace'), 'stderr': result.stderr.decode(errors='replace')})
        require(time.monotonic() < self.deadline, 'absolute campaign deadline')
        return result

    def service_states(self):
        result = {}
        for unit in ('actryn-serverd', 'actryn-launcher', 'actryn-observer'):
            raw = self.systemctl('show', '--property=LoadState,ActiveState,SubState,MainPID,NRestarts', unit)
            result[unit] = dict(line.split('=', 1) for line in raw.decode().splitlines())
        return result

    def accounting(self):
        result = {}
        for name, path in [('launcher', '/var/lib/actryn-server/launcher.sqlite'),
                           ('broker', '/var/lib/actryn-server/broker/state.sqlite')]:
            with contextlib.closing(sqlite3.connect('file:' + path + '?mode=ro', uri=True, timeout=.5)) as db:
                result[name] = {'open_or_unresolved_calls': db.execute(
                    "SELECT count(*) FROM calls WHERE publication_closed=0 OR state IN ('reserved','dispatched','unknown')").fetchone()[0],
                    'robot_debits': db.execute('SELECT count(*) FROM robot_requests WHERE outstanding=1').fetchone()[0]}
        return result

    def observer_pin(self):
        pid = int(self.systemctl('show', '--value', '-p', 'MainPID', 'actryn-observer'))
        require(pid > 1, 'observer not running')
        identity = gap.process_identity(pid)
        require(identity['executable'] == str(self.slot / 'bin/actryn-observer')
                and hashlib.sha256(common.read_bounded(self.slot / 'bin/actryn-observer', 64 * 1024 * 1024)).hexdigest()
                == self.entries['bin/actryn-observer']['sha256'], 'observer executable changed')
        for thread in Path('/proc', str(pid), 'task').iterdir():
            fields = dict(line.split(':', 1) for line in common.read_bounded(thread / 'status', 8192).decode().splitlines())
            require(int(fields['CapEff'], 16) == int(fields['CapPrm'], 16) == 0
                    and fields['NoNewPrivs'].strip() == '1', 'observer still holds loading capabilities')
        return identity

    def set_mode(self, mode):
        state = self.service_states()
        require(all(state[unit]['ActiveState'] == 'inactive' and state[unit]['MainPID'] == '0'
                    for unit in ('actryn-serverd', 'actryn-launcher')), 'server/launcher resumed during measurement')
        active = state['actryn-observer']['ActiveState']
        require(active in ('active', 'inactive'), 'unexpected observer service transition/failure')
        if mode == 'OFF':
            if active == 'active':
                require(self.observer_pin() == self.observer, 'observer process changed before planned stop')
                self.systemctl('stop', 'actryn-observer')
            final = self.service_states()['actryn-observer']
            require(final['ActiveState'] == 'inactive' and final['MainPID'] == '0', 'observer did not stop')
            def absent():
                return {str(value): observer_program_absent(value) for value in sorted(self.observer_ids)}
            checks = gap.wait_until(absent, lambda v: bool(v) and all(v.values()),
                                    min(self.deadline, time.monotonic() + 5))
            self.record('observer-only-programs-absent', checks)
            self.observer = None
        else:
            if active == 'inactive':
                self.systemctl('start', 'actryn-observer')
                def ready():
                    pid = int(self.systemctl('show', '--value', '-p', 'MainPID', 'actryn-observer'))
                    return pid if pid > 1 and gap.observer_socket_ready(pid) else None
                gap.wait_until(ready, bool, min(self.deadline, time.monotonic() + 10))
                self.observer = self.observer_pin()
                ids = program_ids(self.observer['pid'])
                self.observer_ids.update(ids)
                self.record('observer-program-identity', {'process': self.observer, 'program_ids': ids})
            require(self.observer_pin() == self.observer, 'observer lifetime changed')

    def exchange(self, identity, op):
        request = dict(identity, op=op)
        deadline = min(self.deadline, time.monotonic() + 1)
        self.record('observer-request', request)
        rpc_start = time.monotonic_ns()
        with socket.socket(socket.AF_UNIX) as stream:
            def read(count):
                raw = b''
                while len(raw) < count:
                    left = deadline - time.monotonic(); require(left > 0, 'observer RPC deadline')
                    stream.settimeout(left)
                    part = stream.recv(count - len(raw)); require(part, 'observer RPC EOF')
                    raw += part
                return raw
            left = deadline - time.monotonic(); require(left > 0, 'observer RPC deadline')
            stream.settimeout(left)
            stream.connect('/run/actryn/observer.sock')
            peer = struct.unpack('3i', stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            require(peer[0] == self.observer['pid'] and peer[1] == 0, 'observer RPC lifetime mismatch')
            raw = json.dumps(request).encode()
            left = deadline - time.monotonic(); require(left > 0, 'observer RPC deadline')
            stream.settimeout(left)
            stream.sendall(struct.pack('!I', len(raw)) + raw)
            count, = struct.unpack('!I', read(4)); require(0 < count <= 65536, 'observer reply bound')
            result = json.loads(read(count))
        require(time.monotonic() < deadline, 'observer RPC deadline')
        self.last_rpc_ns = time.monotonic_ns() - rpc_start
        self.record('observer-reply', result)
        return result

    def helper(self, cg, identity, on, row=None):
        def enter():
            require(cg.stat().st_ino == identity['cgroup_id'], 'workload cgroup identity changed')
            (cg / 'cgroup.procs').write_text(str(os.getpid()))
        require(time.monotonic() < self.deadline, 'absolute campaign deadline')
        process = subprocess.Popen(['/usr/bin/python3', '-B', '-I', '-c', WORKLOAD], preexec_fn=enter,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        try:
            ready = read_line(process.stdout.fileno(), min(self.deadline, time.monotonic() + 5))
            self.record('workload-ready', {'identity': identity, 'frame': ready})
            require(ready == {'phase': 'READY', 'pid': process.pid}, 'unexpected workload READY')
            child = gap.process_identity(process.pid)
            require(child['cgroup'] == '0::' + identity['cgroup_path'] and child['start_ticks'] > 0
                    and common.read_bounded(cg / 'cgroup.procs', 4096).decode().split() == [str(process.pid)],
                    'workload is not sole member of original cgroup')
            self.record('workload-identity', child)
            initial = self.exchange(identity, 'health') if on else None
            if on: common.observer_health(initial, initial)
            observer_cpu = cpu_ticks(self.observer['pid']) if on else None
            before = {name: common.read_bounded(cg / name, 4096).decode() for name in ('cpu.stat', 'memory.events')}
            guest_before = {'cpu': common.read_bounded(Path('/proc/stat'), 65536).decode().partition('\n')[0],
                            'cpu_pressure': common.read_bounded(Path('/proc/pressure/cpu'), 4096).decode()}
            require(time.monotonic() < self.deadline, 'absolute campaign deadline')
            process.stdin.write(b'G'); process.stdin.flush()
            done = read_line(process.stdout.fileno(), min(self.deadline, time.monotonic() + 16))
            self.record('workload-done', {'identity': identity, 'frame': done})
            if row is not None: row['timing_prefix'] = done
            require(done['phase'] == 'DONE' and done['pid'] == process.pid and done['opens'] == 30000,
                    'fixed workload did not complete')
            post = self.exchange(identity, 'health') if on else None
            post_health_ns = self.last_rpc_ns if on else None
            if row is not None: row['source_prefix'] = {'pre': initial, 'post': post}
            if on:
                require(post['collector_epoch'] == initial['collector_epoch']
                        and post['sequence'] - initial['sequence'] == 60000
                        and post['lost'] >= initial['lost'], 'loop source identity/count changed')
            raw, errors = process.communicate(b'X', timeout=min(2, max(.001, self.deadline - time.monotonic())))
            require(process.returncode == 0 and not raw and not errors, 'workload exit/output mismatch')
            after = {name: common.read_bounded(cg / name, 4096).decode() for name in ('cpu.stat', 'memory.events')}
            guest_after = {'cpu': common.read_bounded(Path('/proc/stat'), 65536).decode().partition('\n')[0],
                           'cpu_pressure': common.read_bounded(Path('/proc/pressure/cpu'), 4096).decode()}
            return done, {'child': child, 'pre': initial, 'post': post, 'observer_cpu_before': observer_cpu,
                          'post_loop_health_rpc_ns': post_health_ns,
                          'guest_scheduling_before': guest_before, 'guest_scheduling_after': guest_after,
                          'cgroup_counters_before': before, 'cgroup_counters_after': after}
        except BaseException:
            process.kill()
            try: process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                self.record('helper-reap-unknown', {'pid': process.pid, 'automatic_retry': False})
            raise
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None: stream.close()

    def trial(self, row):
        on = row['mode'] == 'ON'
        self.set_mode(row['mode'])
        row.update(status='started', attempt=uuid.uuid4().hex, opens=30000,
                   workload_sha256=WORKLOAD_SHA256, profile='fixed-standalone-30k',
                   boot_id=self.args.boot_id, manifest=self.args.manifest)
        self.record('trial-started', row)
        require(time.monotonic() < self.deadline, 'absolute campaign deadline')
        cg = Path('/sys/fs/cgroup/actryn', row['attempt']); cg.mkdir()
        for name, value in [('memory.max', '268435456'), ('memory.swap.max', '0'), ('pids.max', '64'),
                            ('cpu.max', '50000 100000'), ('io.max', '254:0 rbps=1048576 wbps=1048576 riops=128 wiops=128')]:
            (cg / name).write_text(value)
            require(common.read_bounded(cg / name, 4096).decode().strip() == value, 'resource profile readback')
        identity = {'attempt_id': row['attempt'], 'boot_id': self.args.boot_id,
                    'cgroup_id': cg.stat().st_ino, 'cgroup_path': '/actryn/' + row['attempt']}
        registered = self.exchange(identity, 'register') if on else None
        if on: common.observer_health(registered, registered)
        done, diagnostics = self.helper(cg, identity, on, row)
        require('populated 0' in common.read_bounded(cg / 'cgroup.events', 4096).decode().splitlines(),
                'workload descendants remain; retirement not established')
        final = self.exchange(identity, 'unregister') if on else None  # One request; never retry a lost reply.
        retirement_ns = self.last_rpc_ns if on else None
        if on:
            require(final['collector_epoch'] == registered['collector_epoch'], 'collector epoch changed at retirement')
            epoch = str(uuid.UUID(final['collector_epoch']))
            path = Path('/var/lib/actryn-observer', epoch, row['attempt'] + '.jsonl')
            raw = common.read_bounded(path, 16 * 1024 * 1024)
            summary = json.loads(common.read_bounded(path.with_suffix('.summary.json'), 4096))
            require(summary['status'] == final and summary['retained_bytes'] == len(raw), 'summary/raw frontier mismatch')
            records = [json.loads(line) for line in raw.splitlines()]
            require(all(v['attempt_id'] == row['attempt'] and v['boot_id'] == self.args.boot_id
                        and v['collector_epoch'] == epoch and v['event']['cgroup_id'] == identity['cgroup_id']
                        and v['event']['origin'] == 'linux.tracepoint' for v in records), 'raw trace identity mismatch')
            sequences = [v['event']['sequence'] for v in records]
            require(len(set(sequences)) == len(sequences) and all(type(v) is int and 0 < v <= final['sequence']
                        for v in sequences) and final['sequence'] - len(sequences) == final['lost'], 'loss/raw count mismatch')
            cpu_after = cpu_ticks(self.observer['pid']); cpu_before = diagnostics['observer_cpu_before']
            require(cpu_after['start'] == cpu_before['start'] == self.observer['start_ticks']
                    and all(cpu_after[k] >= cpu_before[k] for k in ('user', 'system')), 'observer CPU lifetime changed')
            row.update(loss={k: final[k] for k in ('lost', 'sequence', 'ready')},
                       retirement_rpc_ns=retirement_ns, observer_cpu_ticks={
                           k: cpu_after[k] - cpu_before[k] for k in ('user', 'system')},
                       clock_ticks_per_second=os.sysconf('SC_CLK_TCK'),
                       trace_sha256=hashlib.sha256(raw).hexdigest(), summary=summary)
        else:
            row.update(loss=None, retirement_rpc_ns=None, observer_cpu_ticks=None)
        cg.rmdir()
        row.update(status='complete', retired=True,
                   **{k: done[k] for k in ('wall_ns', 'user_cpu_ns', 'system_cpu_ns')}, diagnostics=diagnostics)
        analyze(self.trials)  # Reject malformed completed samples before recording them as usable.
        self.record('trial-complete', row)

    def run(self):
        initial = self.service_states()
        self.record('initial-services', initial)
        require(all(v['LoadState'] == 'loaded' and v['ActiveState'] == 'active' and int(v['MainPID']) > 1
                    for v in initial.values()), 'begin with three explicitly started, healthy installed services')
        self.loaded_pins()
        self.observer = self.observer_pin()
        self.observer_ids.update(program_ids(self.observer['pid']))
        before = self.stores()
        accounting = self.accounting()
        require(all(state == 'reaped' for rows in before.values() for state in rows.values()) and not self.tasks()
                and all(count == 0 for values in accounting.values() for count in values.values()),
                'server work is not quiescent')
        self.record('initial-observer-identity', {'process': self.observer, 'program_ids': sorted(self.observer_ids),
                                                'quiescent_accounting': accounting})
        self.systemctl('stop', 'actryn-serverd')
        require(self.stores() == before and not self.tasks() and self.accounting() == accounting,
                'work changed before launcher stop')
        self.systemctl('stop', 'actryn-launcher')
        for row in self.trials:
            try:
                self.trial(row)
            except BaseException as error:
                row.update(status='failed', error=repr(error))
                raise
        self.set_mode('OFF')  # Explicit final observer stop; no implicit service restoration.
        final = self.service_states()
        require(all(v['ActiveState'] == 'inactive' and v['MainPID'] == '0' for v in final.values())
                and self.stores() == before and not self.tasks() and self.accounting() == accounting,
                'final quiescence/accounting changed')
        require(time.monotonic() < self.deadline, 'absolute campaign deadline')
        self.record('MEASUREMENTS_COMPLETE', dict(analyze(self.trials), initial_services=initial, final_services=final,
                    release_qualified=False, physical_acceptance=False, services_left_stopped=True))


def terminal_states():
    """A separate bounded read-only failure snapshot; never extends experiment eligibility."""
    deadline = time.monotonic() + 5
    result = {}
    for unit in ('actryn-serverd', 'actryn-launcher', 'actryn-observer'):
        try:
            left = min(2, deadline - time.monotonic()); require(left > 0, 'terminal state snapshot cutoff')
            reply = subprocess.run(['systemctl', 'show',
                    '--property=LoadState,ActiveState,SubState,MainPID,NRestarts', unit], capture_output=True, timeout=left)
            require(reply.returncode == 0 and len(reply.stdout) <= 8192 and len(reply.stderr) <= 8192,
                    'terminal state read failed')
            result[unit] = dict(line.split('=', 1) for line in reply.stdout.decode().splitlines())
        except BaseException as error:
            result[unit] = {'unknown': repr(error)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-disposable-guest', action='store_true', required=True)
    for name in ('machine-id', 'boot-id', 'manifest'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(os.geteuid() == 0 and re.fullmatch('[0-9a-f]{32}', args.machine_id)
            and str(uuid.UUID(args.boot_id)) == args.boot_id
            and re.fullmatch('[0-9a-f]{64}', args.manifest), 'explicit exact guest pins required')
    actual = {'debian': common.read_bounded(Path('/etc/debian_version'), 64).decode().strip(),
              'kernel': os.uname().release, 'arch': os.uname().machine,
              'machine': common.read_bounded(Path('/etc/machine-id'), 64).decode().strip(),
              'boot': common.read_bounded(Path('/proc/sys/kernel/random/boot_id'), 64).decode().strip()}
    gap.check_guest(actual, {'debian': '13.7', 'kernel': '6.12.111+deb13-amd64', 'arch': 'x86_64',
                            'machine': args.machine_id, 'boot': args.boot_id})
    require(common.read_bounded(Path('/etc/hostname'), 256).decode().strip().startswith('actryn-install-server'),
            'not the selected disposable installation guest')
    slot = Path('/opt/actryn/server/current').resolve()
    require(slot.name == 'payload' and slot.parent.name == args.manifest, 'installed slot mismatch')
    raw = common.read_bounded(slot.parent / 'manifest.json', 262144)
    require(hashlib.sha256(raw).hexdigest() == args.manifest, 'manifest hash mismatch')
    manifest = json.loads(raw); require(manifest['role'] == 'server', 'wrong installed role')
    entries = {v['path']: v for v in manifest['files']}
    for fixed, relative in [('/usr/bin/actryn', 'bin/actryn'),
                            ('/usr/lib/actryn/observer.bpf.o', 'lib/observer.bpf.o')]:
        path = Path(fixed)
        require(path.resolve() == slot / relative and hashlib.sha256(
                common.read_bounded(slot / relative, 64 * 1024 * 1024)).hexdigest() == entries[relative]['sha256'],
                'installed CLI/BPF identity mismatch')
    require(args.output.is_absolute() and args.output.parent == Path('/var/tmp')
            and args.output.name.startswith('actryn-observer-overhead-'), 'new protected guest output required')
    os.umask(0o077); args.output.mkdir(mode=0o700, exist_ok=False)
    run = Campaign(args, slot, entries)
    try:
        run.record('preflight', {'guest': actual, 'manifest': args.manifest, 'order': ORDER,
                   'driver_python': sys.version, 'workload_python': {
                       'path': str(Path('/usr/bin/python3').resolve()),
                       'sha256': hashlib.sha256(common.read_bounded(Path('/usr/bin/python3').resolve(), 64 * 1024 * 1024)).hexdigest()},
                   'source_sha256': hashlib.sha256(common.read_bounded(Path(__file__), 131072)).hexdigest(),
                   'helper_sha256': {Path(module.__file__).name: hashlib.sha256(common.read_bounded(Path(module.__file__), 131072)).hexdigest()
                                     for module in (gap, common)}, 'workload_sha256': WORKLOAD_SHA256,
                   'workload': WORKLOAD, 'bpf_absence_api': 'amd64 bpf(321), BPF_PROG_GET_FD_BY_ID(13)',
                   'no_bpf_detach_or_device_policy_write': True, 'no_discarded_warmups': True})
        config = json.loads(common.read_bounded(Path('/etc/actryn/server.json'), 65536))
        require(config['io_device'] == '254:0', 'selected resource profile differs')
        cg_root = Path('/sys/fs/cgroup/actryn')
        mode = cg_root.stat()
        require(cg_root.is_dir() and not cg_root.is_symlink() and mode.st_uid == 0 and not mode.st_mode & 0o022,
                'untrusted existing cgroup parent')
        run.run()
    except BaseException as error:
        run.record('FAILED', dict(analyze(run.trials), error=repr(error), final_services=terminal_states(),
                   cleanup_unconfirmed=True, services_restored=False, automatic_retry=False,
                   next_action='preserve output/state/traces; inspect exact cgroup and observer before explicit recovery'))
        raise


if __name__ == '__main__':
    main()
