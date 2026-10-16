#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent fixed-UAPI live checks; only the dedicated raw-TTY A16 guest."""
import array
import ctypes
import errno
import json
import os
import pathlib
import signal
import socket
import struct
import time

SOCKET = '/run/actryn-a16.sock'


def now():
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def request(opcode, role=0, nonce=bytes(16), deadline=0):
    if len(nonce) != 16:
        raise ValueError('nonce size')
    data = bytearray(192)
    struct.pack_into('<4I', data, 0, 1, opcode, 0, role)
    data[16:32] = nonce
    struct.pack_into('<Q', data, 80, deadline)
    return bytes(data)


def exchange(connection, action, payload=bytes(192)):
    if len(payload) != 192:
        raise ValueError('request size')
    connection.settimeout(2)
    command = struct.pack('<II', action, 0) + payload
    if connection.send(command) != 200:
        raise ValueError('short command')
    reply, _, flags, _ = connection.recvmsg(225)
    if len(reply) != 224 or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
        raise ValueError('reply size/truncation')
    error, reserved = struct.unpack_from('<iI', reply)
    if reserved:
        raise ValueError('reserved reply field')
    return error, reply[8:]


def decode_status(data):
    if len(data) < 192 or struct.unpack_from('<I', data)[0] != 1:
        raise ValueError('status ABI')
    result = {'state': struct.unpack_from('<I', data, 4)[0],
              'operation_state': struct.unpack_from('<I', data, 8)[0]}
    names = ('boot', 'session', 'grant', 'instance', 'operation', 'stream',
             'sequence', 'transaction', 'deadline_ns', 'now_ns', 'observation',
             'context', 'controller_ns')
    result.update(zip(names, struct.unpack_from('<13Q', data, 48)))
    result.update(zip(('left', 'right', 'reason', 'lost', 'flags'),
                      struct.unpack_from('<iiIII', data, 168)))
    return result


def bind(role):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    connection.connect(SOCKET)
    error, _ = exchange(connection, 1, request(1, role=role))
    assert error == 0, ('bind', role, error)
    return connection


def status(admin):
    error, data = exchange(admin, 3)
    assert error == 0, error
    return decode_status(data)


def emit(check, **data):
    print(json.dumps({'check': check, 'at_ns': now(), **data}), flush=True)


def wait_child(pid):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        got, result = os.waitpid(pid, os.WNOHANG)
        if got:
            assert os.waitstatus_to_exitcode(result) == 0, result
            return
        time.sleep(.005)
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    raise TimeoutError('qualification child deadline')


def transfer(channel, connection):
    assert channel.sendmsg([b'F'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                   array.array('i', [connection.fileno()]))]) == 1


def transferred(channel):
    channel.settimeout(2)
    data, ancillary, flags, _ = channel.recvmsg(1, socket.CMSG_SPACE(4), socket.MSG_CMSG_CLOEXEC)
    assert data == b'F' and not flags & socket.MSG_CTRUNC
    assert len(ancillary) == 1 and ancillary[0][:2] == (socket.SOL_SOCKET, socket.SCM_RIGHTS)
    fds = array.array('i')
    fds.frombytes(ancillary[0][2])
    assert len(fds) == 1
    return socket.socket(fileno=fds[0])


def deny_exec():
    # Fixed ARM64 trusted-client filter, inherited by all qualification children.
    class Filter(ctypes.Structure):
        _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                    ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ushort), ('filter', ctypes.POINTER(Filter))]
    code = (Filter * 5)(Filter(0x20, 0, 0, 0), Filter(0x15, 2, 0, 221),
                        Filter(0x15, 1, 0, 281), Filter(0x06, 0, 0, 0x7fff0000),
                        Filter(0x06, 0, 0, 0x00050000 | errno.EPERM))
    program = Program(5, code)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
    assert libc.prctl(38, 1, 0, 0, 0) == 0
    assert libc.prctl(22, 2, ctypes.addressof(program), 0, 0) == 0


def guard():
    assert os.geteuid() == 0 and os.uname().machine == 'aarch64'
    assert os.uname().release == '6.12.111+deb13-arm64'
    assert pathlib.Path('/etc/hostname').read_text().strip() == 'actryn-a16'
    assert b'linux,dummy-virt' in pathlib.Path('/proc/device-tree/compatible').read_bytes().split(b'\0')
    assert not pathlib.Path('/dev/actryn-authority').exists()
    assert 'actryn_authority ' not in pathlib.Path('/proc/modules').read_text()
    assert pathlib.Path('/dev/ttyAMA1').stat().st_mode & 0o777 == 0o600


def main():
    guard()
    signal.alarm(20)
    deny_exec()
    # An unrelated unprivileged process must not obtain the actual UART.
    child = os.fork()
    if not child:
        os.setgroups([])
        os.setgid(65534)
        os.setuid(65534)
        try:
            os.close(os.open('/dev/ttyAMA1', os.O_RDWR | os.O_NONBLOCK))
        except OSError as error:
            os._exit(0 if error.errno in (errno.EACCES, errno.EPERM) else 1)
        os._exit(1)
    wait_child(child)
    emit('unprivileged UART open denied')
    admin = bind(1)
    initial = status(admin)
    assert initial['state'] == 0 and initial['flags'] == 0 and initial['grant'] == 0, initial
    runtime = bind(2)
    # Real inherited and SCM_RIGHTS sockets retain their role but not authority.
    child = os.fork()
    if not child:
        error, _ = exchange(runtime, 3)
        os._exit(0 if error == -errno.EPERM else 1)
    wait_child(child)
    emit('inherited runtime denied')
    sender, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    child = os.fork()
    if not child:
        sender.close()
        runtime.close()
        received = transferred(receiver)
        error, _ = exchange(received, 3)
        os._exit(0 if error == -errno.EPERM else 1)
    receiver.close()
    transfer(sender, runtime)
    wait_child(child)
    sender.close()
    assert exchange(runtime, 3)[0] == 0
    emit('SCM_RIGHTS runtime denied; original owner still admitted')
    runtime.close()
    end = time.monotonic() + 2
    while status(admin)['state'] != 4 and time.monotonic() < end:
        time.sleep(.005)
    assert status(admin)['reason'] == 5
    # A new child owns a real runtime connection. Its FD remains in the parent
    # after death, so closure cannot be explained by final socket release.
    parent, offspring = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    child = os.fork()
    if not child:
        parent.close()
        offspring.settimeout(3)
        owned = bind(2)
        transfer(offspring, owned)
        assert offspring.recv(1) == b'Q'
        os._exit(0)
    offspring.close()
    retained = transferred(parent)
    assert exchange(retained, 3)[0] == -errno.EPERM
    assert exchange(admin, 2, request(12))[0] == 0  # explicit recovery, no grant/rearm
    end = time.monotonic() + 1.5
    while time.monotonic() < end:
        current = status(admin)
        if current['flags'] & 1:
            break
        assert current['state'] != 4, current
        time.sleep(.002)
    assert current['flags'] & 1 and current['state'] == 0, current
    emit('fresh inhibited baseline before owner exit', status=current)
    parent.send(b'Q')
    wait_child(child)
    end = time.monotonic() + 2
    while time.monotonic() < end:
        current = status(admin)
        if current['state'] == 4:
            break
        time.sleep(.005)
    assert current['state'] == 4 and current['reason'] == 5, current
    assert current['grant'] == 0 and not current['flags'] & 8, current
    assert exchange(retained, 3)[0] == -errno.EPERM
    emit('owner exit closed authority despite retained runtime FD', status=current)
    retained.close()
    parent.close()
    admin.close()
    emit('PASS live ownership qualification; operation cases are separate')


if __name__ == '__main__':
    main()
