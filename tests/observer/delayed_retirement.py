#!/usr/bin/env python3
"""Actual observer regression with a bounded, test-only persistence fault.

Run only in the disposable pinned Debian guest with installed services stopped.
No production binary, object, unit, or timeout is replaced. Raw evidence remains.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time
import uuid

SOCKET = Path('/run/actryn/observer.sock')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disposable-guest', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert os.geteuid() == 0 and os.uname().release == '6.12.111+deb13-amd64'
    assert args.output.is_absolute() and args.output.parent == Path('/var/tmp')
    assert args.output.name.startswith('actryn-observer-retirement-')
    for unit in ('actryn-serverd', 'actryn-launcher', 'actryn-observer'):
        state = subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True, timeout=5)
        assert state.stdout.strip() in ('inactive', 'failed'), (unit, state.stdout)
    assert not SOCKET.exists(), 'existing observer socket must be retired before this standalone test'
    args.output.mkdir(mode=0o700)
    source = Path(__file__).with_name('fsync_barrier.c')
    library = args.output / 'fsync_barrier.so'
    subprocess.run(['cc', '-std=c11', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-o', str(library), str(source)], check=True, timeout=30)
    target = uuid.uuid4().hex
    control = args.output / 'sync-control'
    control.mkdir(mode=0o700)
    env = dict(os.environ, LD_PRELOAD=str(library), ACTRYN_TEST_SYNC_TARGET=target,
               ACTRYN_TEST_SYNC_CONTROL=str(control))
    transcript = args.output / 'requests.jsonl'
    root = Path('/sys/fs/cgroup/actryn')
    root.mkdir(exist_ok=True)
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    groups = []
    registrations = []
    epoch = None
    socket_inode = None
    result = {'test': 'observer-delayed-persistence', 'status': 'NOT_COMPLETED',
              'target_attempt': target, 'boot_id': boot, 'authority_issued': False}
    result['sha256'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in
                        (source, library, Path('/usr/bin/actryn-observer'), Path('/usr/lib/actryn/observer.bpf.o'))}

    def exchange(request):
        data = json.dumps(request).encode()
        started = time.monotonic()
        reply = None
        with socket.socket(socket.AF_UNIX) as stream:
            stream.settimeout(3)
            stream.connect(str(SOCKET))
            stream.sendall(struct.pack('>I', len(data)) + data)
            header = stream.recv(4)
            if header:
                while len(header) < 4:
                    part = stream.recv(4 - len(header))
                    assert part, 'partial observer header'
                    header += part
                size, = struct.unpack('>I', header)
                assert 0 < size <= 65536
                data = b''
                while len(data) < size:
                    part = stream.recv(size - len(data))
                    assert part, 'partial observer reply'
                    data += part
                reply = json.loads(data)
        with transcript.open('a') as trace:
            trace.write(json.dumps({'request': request, 'reply': reply,
                                    'elapsed_ms': (time.monotonic() - started) * 1000}) + '\n')
        return reply

    def request(attempt=None):
        attempt = attempt or uuid.uuid4().hex
        cg = root / attempt
        cg.mkdir()
        groups.append(cg)
        return dict(op='register', attempt_id=attempt, boot_id=boot,
                    cgroup_id=cg.stat().st_ino, cgroup_path='/actryn/' + attempt)

    def until_health(identity):
        deadline = time.monotonic() + 5
        while True:
            health = exchange(dict(identity, op='health'))
            if health is not None:
                return health
            assert time.monotonic() < deadline, 'collector did not recover after barrier release'
            time.sleep(.02)

    def retire(identity):
        # These are the same immutable observer retirement identity, as used by
        # the launcher's existing cleanup loop; never a second operator cancel.
        deadline = time.monotonic() + 5
        while exchange(dict(identity, op='unregister')) is None:
            assert time.monotonic() < deadline, 'durable retirement did not converge'
            time.sleep(.02)

    with (args.output / 'observer.stderr').open('wb') as stderr:
        observer = subprocess.Popen(['/usr/bin/actryn-observer'], env=env, stderr=stderr)
        try:
            deadline = time.monotonic() + 10
            while not SOCKET.exists():
                assert observer.poll() is None, 'observer exited before readiness'
                assert time.monotonic() < deadline, 'observer did not become ready'
                time.sleep(.02)
            socket_inode = SOCKET.stat().st_ino
            for index in range(8):
                identity = request(target if index == 0 else None)
                status = exchange(identity)
                assert status is not None and status['ready'] and status['lost'] == 0, status
                epoch = epoch or status['collector_epoch']
                assert status['collector_epoch'] == epoch
                registrations.append(identity)
            log = Path('/var/lib/actryn-observer') / epoch / (target + '.jsonl')
            summary_path = log.with_suffix('.summary.json')

            # Real collector blocks in its JSONL fsync. Its IPC deadline must
            # fail closed without claiming a durable summary or releasing state.
            assert exchange(dict(registrations[0], op='unregister')) is None
            assert (control / 'entered').exists() and not (control / 'released').exists()
            assert not summary_path.exists()
            assert exchange(dict(registrations[1], op='health')) is None
            assert not summary_path.exists()

            # Make that delayed fsync fail once. Capacity must remain held:
            # releasing a registration before persistence is a caught mutation.
            (control / 'release').write_text('E')
            assert until_health(registrations[1])['ready']
            assert (control / 'released').exists() and not summary_path.exists()
            assert exchange(request()) is None, 'failed persistence released a registration slot'
            assert not until_health(registrations[0])['ready']
            assert 'collector capacity/health' in (args.output / 'observer.stderr').read_text()

            retire(registrations[0])
            summary = json.loads(summary_path.read_text())
            assert summary['status']['ready'] and summary['status']['lost'] == 0
            assert summary['local_lost'] == 0 and summary['retained_bytes'] == log.stat().st_size
            assert not until_health(registrations[0])['ready']
            replacement = request()
            assert exchange(replacement)['ready'], 'durable retirement did not release its one slot'
            assert exchange(request()) is None, 'durable retirement released more than one slot'
            for identity in registrations[1:] + [replacement]:
                retire(identity)
            result.update(status='PASS', collector_epoch=epoch, summary=summary,
                          delayed_sync_failed_once=True, capacity_retained_before_durability=True,
                          released_slots=1, original_identity_recovered=True,
                          production_binary_changed=False)
        finally:
            # No service is restarted and no incomplete log is deleted.
            observer.terminate()
            try:
                observer.wait(timeout=5)
            except subprocess.TimeoutExpired:
                observer.kill()
                observer.wait(timeout=5)
            if SOCKET.exists() and SOCKET.stat().st_ino == socket_inode:
                SOCKET.unlink()
            for cg in groups:
                if cg.exists():
                    assert 'populated 0' in (cg / 'cgroup.events').read_text(), str(cg)
                    cg.rmdir()
            (args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
