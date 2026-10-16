"""Guarded disposable-guest test helper retaining actual installed gateway FDs.

pidfd_getfd uses existing root permissions, never changes ptrace or capabilities.
No payload is read, no shared descriptor flags change, and only a pinned process
may be signalled once. EOF/timeout closes all owned duplicate descriptors.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import struct
import sys
import time

HOLD_NS = 8_000_000_000
PATHS = {'/run/actryn-robot/gateway-control.sock': 'control', '/run/actryn-robot/relay.sock': 'relay'}


def now():
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def classify_socket(peer, manager_pid, manager_uid, paths=PATHS, tcp_port=7443):
    if peer.family == socket.AF_UNIX:
        try:
            path = peer.getpeername()
        except OSError:
            return None
        if path not in paths:
            return None
        pid, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        assert pid == manager_pid and uid == manager_uid, 'retained Unix peer is not exact root manager'
        return {'role': paths[path], 'peer_path': path, 'peer_pid': pid, 'peer_uid': uid}
    if peer.family == socket.AF_INET and not peer.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN):
        try:
            local, remote = peer.getsockname(), peer.getpeername()
        except OSError:
            return None
        if local[1] == tcp_port:
            return {'role': 'tcp', 'local': local, 'remote': remote}
    return None


def validate_roles(roles):
    assert len(roles) == 3 and {r['role'] for r in roles} == {'control', 'relay', 'tcp'}, 'ambiguous/missing gateway FDs'
    assert len({r['inode'] for r in roles}) == 3, 'retained FD aliases'


class SignalOnce:
    def __init__(self, pidfd, send=signal.pidfd_send_signal):
        self.pidfd, self.send, self.attempts = pidfd, send, 0

    def kill(self):
        assert self.attempts == 0, 'gateway signal is never retried'
        self.attempts = 1
        self.send(self.pidfd, signal.SIGKILL, None, 0)


class Retained:
    def __init__(self, pid, digest, manager_pid):
        self.pid, self.digest, self.manager_pid = pid, digest, manager_pid
        self.pidfd, self.sockets, self.roles = None, [], []
        self.closed = True

    def alive(self):
        return not select.select([self.pidfd], [], [], 0)[0]

    def unchanged(self):
        assert self.alive(), 'pinned gateway exited before signal'
        assert hashlib.sha256(Path(f'/proc/{self.pid}/exe').read_bytes()).hexdigest() == self.digest, 'gateway executable changed'

    def __enter__(self):
        try:
            self.pidfd = os.pidfd_open(self.pid)
            self.closed = False
            self.unchanged()
            assert Path(f'/proc/{self.pid}').stat().st_uid != 0, 'installed gateway must be unprivileged'
            descriptors = list(Path(f'/proc/{self.pid}/fd').iterdir())
            assert len(descriptors) <= 64, 'gateway descriptor bound'
            libc = ctypes.CDLL(None, use_errno=True)
            libc.syscall.restype = ctypes.c_long
            for path in descriptors:
                if not os.readlink(path).startswith('socket:['):
                    continue
                # Linux arm64 syscall 438. No retry, fallback /proc open, or permission changes.
                fd = libc.syscall(ctypes.c_long(438), ctypes.c_int(self.pidfd), ctypes.c_int(int(path.name)), ctypes.c_uint(0))
                if fd < 0:
                    error = ctypes.get_errno()
                    raise OSError(error, os.strerror(error), 'pidfd_getfd')
                try:
                    peer = socket.socket(fileno=fd)
                except BaseException:
                    os.close(fd)
                    raise
                try:
                    role = classify_socket(peer, self.manager_pid, 0)
                    if role:
                        inode = os.fstat(fd).st_ino
                        assert os.readlink(path) == f'socket:[{inode}]', 'descriptor replaced during capture'
                        role.update(source_fd=int(path.name), inode=inode, held_fd=fd)
                        self.roles.append(role)
                        self.sockets.append(peer)
                        peer = None
                finally:
                    if peer:
                        peer.close()
            validate_roles(self.roles)
            self.unchanged()
            self.no_eof()
            return self
        except BaseException:
            self.close()
            raise

    def no_eof(self):
        for peer in self.sockets:
            try:
                data = peer.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT)
                assert data != b'', 'retained peer already ended before signal'
            except BlockingIOError:
                pass

    def heartbeat_once(self):
        index = next(i for i, role in enumerate(self.roles) if role['role'] == 'control')
        result = {'sends': 1, 'started_ns': now()}
        try:
            result['bytes'] = self.sockets[index].send(b'H', socket.MSG_DONTWAIT | socket.MSG_NOSIGNAL)
        except OSError as error:
            result['error'] = repr(error)
        return result

    def close(self):
        for peer in self.sockets:
            peer.close()
        self.sockets.clear()
        if self.pidfd is not None:
            os.close(self.pidfd)
            self.pidfd = None
        self.closed = True

    def __exit__(self, *_):
        self.close()


def command(expected, deadline, fd=None):
    fd = sys.stdin.fileno() if fd is None else fd
    data = bytearray()
    while b'\n' not in data:
        remaining = (deadline - now()) / 1e9
        assert remaining > 0 and select.select([fd], [], [], remaining)[0], 'helper command lease expired'
        chunk = os.read(fd, 32 - len(data))
        assert chunk and len(data) + len(chunk) < 32, 'helper command EOF/capacity'
        data.extend(chunk)
    # One bounded line; EOF never means permission to kill.
    assert data == expected, 'missing/invalid one-shot helper command'


def main():
    assert len(sys.argv) == 6 and os.geteuid() == 0
    mode, pid, digest, manager_pid, destination = sys.argv[1:]
    assert mode in ('probe', 'retain') and re.fullmatch('[0-9a-f]{64}', digest)
    assert re.fullmatch('/var/tmp/actryn-gateway-fd-[0-9a-f]{16}', destination)
    assert os.uname().machine == 'aarch64' and os.uname().release == '6.12.111+deb13-arm64'
    assert Path('/proc/device-tree/compatible').read_bytes().startswith(b'linux,dummy-virt\0')
    os.umask(0o077)
    root = Path(destination); root.mkdir(mode=0o700)
    result = {'mode': mode, 'gateway_pid': int(pid), 'manager_pid': int(manager_pid),
        'gateway_sha256': digest, 'clock': 'CLOCK_BOOTTIME', 'started_ns': now(),
        'signal_attempts': 0, 'released': False, 'automatic_retry': False, 'permission_changes': False}
    signaller, retained = None, Retained(int(pid), digest, int(manager_pid))
    try:
        with retained:
            result.update(roles=retained.roles, ready_ns=now(), pidfd_pinned=True)
            if mode == 'probe':
                result['nonmutating_fd_preflight'] = True
            else:
                deadline = now() + HOLD_NS
                print(json.dumps(dict(result, phase='retained', lease_ns=HOLD_NS)), flush=True)
                command(b'kill\n', min(deadline, now() + 3_000_000_000))
                retained.unchanged(); retained.no_eof()
                assert now() < deadline, 'retention lease expired before signal'
                signaller = SignalOnce(retained.pidfd)
                result['signal_ns'] = now()
                signaller.kill()
                assert select.select([retained.pidfd], [], [], .5)[0], 'pinned gateway death unconfirmed'
                result.update(death_ns=now(), pidfd_dead=True, held_after_death=len(retained.sockets))
                result['synthetic_heartbeat'] = retained.heartbeat_once()
                print(json.dumps(dict(result, phase='killed')), flush=True)
                command(b'release\n', deadline)
                result['release_command_ns'] = now()
        result['released'] = True
    except BaseException as error:
        result['error'] = repr(error)
    finally:
        result['signal_attempts'] = signaller.attempts if signaller else 0
        result['finished_ns'] = now()
        result['within_lease'] = mode == 'probe' or result['finished_ns'] - result.get('ready_ns', result['started_ns']) <= HOLD_NS
        # Even failed checks close the context's owned FDs; do not claim a release command occurred.
        result['owned_fds_closed'] = retained.closed
        path = root / 'retained.json'
        with path.open('x') as stream:
            json.dump(result, stream, indent=2); stream.flush(); os.fsync(stream.fileno())
        print(json.dumps(result), flush=True)
    return 1 if 'error' in result else 0


if __name__ == '__main__':
    sys.exit(main())
