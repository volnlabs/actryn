"""Guest test helper: one ordinary capacity probe, then one reserved Cancel.

No kernel access or database access. Paths are fixed at the executable boundary.
The host supplies two already prepared bounded protobuf requests, without keys.
"""
import base64
import json
import os
import select
import socket
import struct
import sys
import time


def wait_for_trigger(input_fd, output_fd, timeout=10):
    """One bounded preload gate. EOF/expiry/malformed input cannot call Cancel."""
    if not 0 < timeout <= 10:
        raise ValueError('preload wait must be positive and at most ten seconds')
    deadline = time.monotonic() + timeout
    if os.write(output_fd, b'READY\n') != 6:
        raise OSError('incomplete readiness reply')
    data = bytearray()
    while b'\n' not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([input_fd], [], [], remaining)[0]:
            raise TimeoutError('preloaded helper trigger deadline')
        part = os.read(input_fd, 5 - len(data))
        if not part:
            raise EOFError('preloaded helper abandoned before trigger')
        data.extend(part)
        if len(data) > 4:
            raise ValueError('one run trigger required')
    if data != b'run\n' or time.monotonic() >= deadline:
        raise ValueError('one timely run trigger required')


def probe_cancel(paths, describe, cancel, expected_uid):
    assert len(describe) <= 65536 and len(cancel) <= 4096
    clock = lambda: time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    result = {'started_ns': clock(), 'ordinary_rejected': False, 'cancel_sends': 0,
              'automatic_retry': False, 'clock': 'CLOCK_BOOTTIME'}
    def connect(path):
        peer = socket.socket(socket.AF_UNIX)
        try:
            peer.settimeout(.75)
            peer.connect(path)
            assert struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1] == expected_uid
            return peer
        except BaseException:
            peer.close()
            raise
    try:
        with connect(paths[0]) as peer:
            peer.sendall(struct.pack('!I', len(describe)) + describe)
            try:
                head = peer.recv(4)
            except ConnectionResetError:
                head = b''
            assert head == b'', 'ordinary request was not rejected before decoding'
            result['ordinary_rejected'] = True
            result['ordinary_rejected_ns'] = clock()
        with connect(paths[1]) as peer:
            result['cancel_sends'] = 1
            result['cancel_send_ns'] = clock()
            peer.sendall(struct.pack('!I', len(cancel)) + cancel)
            deadline = time.monotonic() + 1
            def read(n):
                data = bytearray()
                while len(data) < n:
                    remaining = deadline - time.monotonic()
                    assert remaining > 0, 'reserved reply deadline'
                    peer.settimeout(remaining)
                    chunk = peer.recv(n - len(data))
                    assert chunk, 'reserved reply EOF'
                    data.extend(chunk)
                return bytes(data)
            size = struct.unpack('!I', read(4))[0]
            assert 0 < size <= 65536, 'reserved reply capacity'
            result['reply_hex'] = read(size).hex()
    except BaseException as error:
        result['error'] = repr(error)
        result['cancel_outcome_unknown'] = result['cancel_sends'] == 1
    finally:
        result['finished_ns'] = clock()
    return result


if __name__ == '__main__':
    arguments = sys.argv[1:]
    preload = arguments[:1] == ['--preload']
    if preload:
        arguments = arguments[1:]
    assert os.geteuid() == 0 and len(arguments) == 2
    assert os.uname().machine == 'aarch64' and os.uname().release == '6.12.111+deb13-arm64'
    describe, cancel = (base64.b64decode(arg, validate=True) for arg in arguments)
    assert len(describe) <= 65536 and len(cancel) <= 4096
    if preload:
        wait_for_trigger(sys.stdin.fileno(), sys.stdout.fileno())
    result = probe_cancel(['/run/actryn-robot/operator.sock', '/run/actryn-robot/closure.sock'],
                          describe, cancel, 0)
    print(json.dumps(result), flush=True)
