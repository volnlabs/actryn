"""Disposable-guest SQLite writer contention, with a pidfd-supervised finite lease.

This takes an existing database write lock without modifying rows. It does not
simulate fsync, EIO or arbitrary media failure. No production injection API.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import socket
import sqlite3
import sys
import time

LEASE_NS = 3_000_000_000
DATABASE = Path('/var/lib/actryn-robot/runtime/intent.sqlite')


@contextlib.contextmanager
def writer_lease(path, released=lambda: None):
    db = sqlite3.connect('file:' + str(path) + '?mode=rw', uri=True, timeout=0)
    try:
        assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete', 'expected production DELETE journal'
        db.execute('BEGIN EXCLUSIVE')
        yield db
    finally:
        try:
            db.rollback()
        finally:
            db.close()
            released()


def clock_ns():
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def wait_release(control, deadline):
    remaining = deadline - clock_ns()
    if remaining <= 0 or not select.select([control], [], [], remaining / 1e9)[0]:
        raise TimeoutError('SQLite contention lease expired')
    command = control.recv(32)
    if not command:
        raise EOFError('lease controller disconnected')
    assert command == b'release\n', 'unexpected lease command'


def send_json(channel, value):
    data = json.dumps(value).encode() + b'\n'
    assert len(data) <= 4096
    channel.sendall(data)


def receive_json(channel, timeout):
    channel.settimeout(timeout)
    data = bytearray()
    while b'\n' not in data:
        block = channel.recv(4096 - len(data))
        if not block:
            raise EOFError('lease helper exited')
        data.extend(block)
        assert len(data) < 4096, 'helper response bound'
    assert data.endswith(b'\n') and data.count(b'\n') == 1, 'helper response framing'
    return json.loads(data)


def child(channel, output, manager, expected):
    result = {'format': 'actryn-sqlite-contention-1', 'helper_pid': os.getpid(),
              'manager_pid': manager, 'manager_sha256': expected, 'lease_ns': LEASE_NS,
              'data_modified': False, 'released': False, 'clock': 'CLOCK_BOOTTIME'}
    def released():
        result['released'] = True
        result['released_ns'] = clock_ns()
    def interrupted(number, _frame):
        raise RuntimeError('lease helper signal ' + str(number))
    for number in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        signal.signal(number, interrupted)
    try:
        with writer_lease(DATABASE, released) as db:
            result['locked_ns'] = clock_ns()
            result['records_before'] = db.execute('SELECT count(*) FROM records').fetchone()[0]
            send_json(channel, dict(result, phase='locked'))
            wait_release(channel, result['locked_ns'] + LEASE_NS)
            result['release_requested_ns'] = clock_ns()
    except BaseException as error:
        result['error'] = repr(error)
    finally:
        result['within_lease'] = (result['released'] and 'locked_ns' in result and
                                  result['released_ns'] - result['locked_ns'] <= LEASE_NS)
        with (output / 'contention.json').open('x') as stream:
            json.dump(result, stream)
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(output, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        send_json(channel, dict(result, phase='released'))


def main():
    assert len(sys.argv) == 4 and os.geteuid() == 0, 'root helper PID SHA256 OUTPUT'
    manager, expected, output = int(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    token = output.name.removeprefix('actryn-contention-')
    assert output.parent == Path('/var/tmp') and output.name.startswith('actryn-contention-')
    assert len(token) == 16 and all(c in '0123456789abcdef' for c in token)
    assert manager > 1 and len(expected) == 64 and all(c in '0123456789abcdef' for c in expected)
    assert os.uname().machine == 'aarch64' and os.uname().release == '6.12.111+deb13-arm64'
    assert Path('/proc/device-tree/compatible').read_bytes().startswith(b'linux,dummy-virt\0')
    assert DATABASE.is_file() and not DATABASE.is_symlink()
    meta = DATABASE.stat()
    assert meta.st_uid == 0 and meta.st_nlink == 1 and meta.st_mode & 0o077 == 0
    manager_fd = os.pidfd_open(manager)
    assert Path(f'/proc/{manager}/exe').resolve().name == 'actryn-robotd'
    assert hashlib.sha256(Path(f'/proc/{manager}/exe').read_bytes()).hexdigest() == expected
    signal.pidfd_send_signal(manager_fd, 0)
    output.mkdir(mode=0o700, exist_ok=False)
    parent, worker = socket.socketpair()
    worker_pid = os.fork()
    if worker_pid == 0:
        parent.close()
        os.close(manager_fd)
        try:
            child(worker, output, manager, expected)
        finally:
            worker.close()
        os._exit(0)
    worker.close()
    worker_fd = os.pidfd_open(worker_pid)
    sent = False
    try:
        ready = receive_json(parent, 2)
        assert ready['helper_pid'] == worker_pid and ready['phase'] == 'locked', ready
        ready['supervisor_pid'] = os.getpid()
        ready['helper_pidfd_pinned'] = True
        print(json.dumps(ready), flush=True)
        remaining = max(0, (ready['locked_ns'] + LEASE_NS - clock_ns()) / 1e9)
        readable = select.select([sys.stdin, parent, worker_fd, manager_fd], [], [], remaining)[0]
        if sys.stdin in readable:
            command = os.read(sys.stdin.fileno(), 32)
            assert command == b'release\n', 'host disconnected or invalid release'
            parent.sendall(command)
            sent = True
        final = receive_json(parent, 4)
        print(json.dumps(final), flush=True)
        assert final['released'] and final['within_lease'] and 'error' not in final, final
    finally:
        if not sent:
            try:
                parent.sendall(b'release\n')
            except OSError:
                pass
        parent.close()
        if not select.select([worker_fd], [], [], .5)[0]:
            signal.pidfd_send_signal(worker_fd, signal.SIGTERM)
            if not select.select([worker_fd], [], [], .5)[0]:
                signal.pidfd_send_signal(worker_fd, signal.SIGKILL)
        # A task stuck in uninterruptible I/O must remain explicitly unknown;
        # never turn its lease supervisor into an unbounded wait.
        exited = select.select([worker_fd], [], [], .5)[0]
        if exited:
            os.waitpid(worker_pid, os.WNOHANG)
        os.close(worker_fd)
        os.close(manager_fd)
        assert exited, 'helper termination unknown after bounded pidfd signals'


if __name__ == '__main__':
    main()
