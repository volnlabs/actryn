"""Guest test helper: one ordinary capacity probe, then one reserved Cancel.

No kernel access or database access. Paths are fixed at the executable boundary.
The host supplies two already prepared bounded protobuf requests, without keys.
"""
import base64
import json
import os
import socket
import struct
import sys
import time


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
    assert os.geteuid() == 0 and len(sys.argv) == 3
    assert os.uname().machine == 'aarch64' and os.uname().release == '6.12.111+deb13-arm64'
    result = probe_cancel(['/run/actryn-robot/operator.sock', '/run/actryn-robot/closure.sock'],
                          *(base64.b64decode(arg, validate=True) for arg in sys.argv[1:]), 0)
    print(json.dumps(result), flush=True)
