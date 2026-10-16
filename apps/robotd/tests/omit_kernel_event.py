#!/usr/bin/env python3
"""Disposable-guest test helper: omit one real event from the shared EVENTS FIFO.

No Runtime/Acquisition role, authority command, frame injection or writable
production API. Invocation is exclusively through the reviewed A11 harness.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import struct
import sys
import time

REQUEST_IOCTL = 0xc0c04101
STATUS_IOCTL = 0x80c04102
STATUS = struct.Struct('<IIII16s16s13QqqiiIIII')
EVENT_HEAD = struct.Struct('<QQII')
EVENT_BYTES = 216
PAUSE_LIMIT_NS = 500_000_000
FIELDS = ('version state operation_state reserved0 runtime_nonce device_identity '
          'controller_boot controller_session grant instance operation stream sequence '
          'transaction deadline_ns now_ns observation context_revision controller_ns '
          'left_encoder right_encoder left_permille right_permille reason events_lost '
          'flags reserved1').split()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def decode_status(raw):
    require(len(raw) == STATUS.size == 192, 'UAPI status size')
    value = dict(zip(FIELDS, STATUS.unpack(raw)))
    for field in ('runtime_nonce', 'device_identity'):
        value[field] = list(value[field])
    require(value['version'] == 1 and value['reserved0'] == value['reserved1'] == 0
            and value['state'] <= 5 and value['operation_state'] <= 6
            and value['reason'] <= 9 and value['flags'] & ~15 == 0, 'UAPI status fields')
    return value


def decode_event(raw):
    require(len(raw) == EVENT_BYTES, 'UAPI event size')
    sequence, captured, kind, reserved = EVENT_HEAD.unpack(raw[:24])
    require(sequence > 0 and captured > 0 and reserved == 0, 'UAPI event header')
    return dict(sequence=sequence, captured_ns=captured, kind=kind, reserved=reserved,
                status=decode_status(raw[24:]))


def no_authority(value):
    require(value['state'] == 1 and value['flags'] == 1 and value['grant'] == 0
            and value['operation'] == 0 and value['operation_state'] == 0
            and value['left_permille'] == value['right_permille'] == 0,
            'helper requires handshaken Ready with no grant, operation or outputs')


def consume_one(fd, deadline_ns, now=time.monotonic_ns, poll_factory=select.poll, read=os.read):
    poll = poll_factory()
    poll.register(fd, select.POLLIN)
    remaining = deadline_ns - now()
    require(remaining > 0, 'pause budget exhausted before event wait')
    ready = poll.poll(max(1, (remaining + 999_999) // 1_000_000))
    require(ready and ready[0][0] == fd and ready[0][1] == select.POLLIN,
            'one event unavailable or source closed')
    require(now() < deadline_ns, 'pause budget exhausted before event read')
    # Exactly one consuming read. EAGAIN/short read/error is final, never retried.
    return read(fd, EVENT_BYTES)


def paused_once(pidfd, action, send=signal.pidfd_send_signal, now=time.monotonic_ns):
    result = {'stop_requested_ns': now(), 'resume_attempted': False, 'resumed': False}
    try:
        send(pidfd, signal.SIGSTOP)
        result.update(action())
    except BaseException as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        result['resume_attempted'] = True
        try:
            send(pidfd, signal.SIGCONT)
            result['resumed'] = True
        except BaseException as error:
            result['resume_error'] = type(error).__name__ + ': ' + str(error)
        result['resume_completed_ns'] = now()
        result['stopped_duration_ns'] = result['resume_completed_ns'] - result['stop_requested_ns']
    return result


def main():
    require(len(sys.argv) == 4 and os.geteuid() == 0, 'root helper PID SHA256 OUTPUT arguments')
    pid, expected = int(sys.argv[1]), sys.argv[2]
    output = Path(sys.argv[3])
    token = output.name.removeprefix('actryn-a11-')
    require(output.parent == Path('/var/tmp') and output.name.startswith('actryn-a11-')
            and len(token) == 16 and all(c in '0123456789abcdef' for c in token), 'test output path')
    output.mkdir(mode=0o700, exist_ok=False)
    require(pid > 1 and len(expected) == 64 and all(c in '0123456789abcdef' for c in expected),
            'invalid manager identity')
    require(os.uname().machine == 'aarch64' and os.uname().release == '6.12.111+deb13-arm64'
            and Path('/proc/device-tree/compatible').read_bytes().startswith(b'linux,dummy-virt\0'),
            'supported disposable non-actuating guest required')
    pidfd = os.pidfd_open(pid)
    events = None
    try:
        image = Path(f'/proc/{pid}/exe')
        require(image.resolve().name == 'actryn-robotd'
                and hashlib.sha256(image.read_bytes()).hexdigest() == expected, 'manager binary mismatch')
        signal.pidfd_send_signal(pidfd, 0)
        events = os.open('/dev/actryn-authority', os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK)
        request = bytearray(struct.pack('<IIII', 1, 1, 0, 4) + bytes(176))
        fcntl.ioctl(events, REQUEST_IOCTL, request, True)
        before_raw = bytearray(192)
        fcntl.ioctl(events, STATUS_IOCTL, before_raw, True)
        before = decode_status(before_raw)
        no_authority(before)
        signal.pidfd_send_signal(pidfd, 0)

        def interrupted(number, _frame):
            raise RuntimeError(f'helper interrupted by signal {number}')

        for number in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            signal.signal(number, interrupted)

        captured = {}

        def omit_read():
            nonlocal events
            deadline = time.monotonic_ns() + PAUSE_LIMIT_NS
            while True:
                states = [next(line for line in path.read_text().splitlines() if line.startswith('State:'))
                          for path in Path(f'/proc/{pid}/task').glob('*/status')]
                require(states, 'manager vanished')
                if all(line.split()[1] in ('T', 't') for line in states):
                    break
                require(time.monotonic_ns() < deadline, 'manager did not stop within pause budget')
                time.sleep(.001)
            all_stopped = time.monotonic_ns()
            raw = consume_one(events, deadline)
            captured.update(all_threads_stopped_ns=all_stopped, thread_count=len(states),
                            event_read_completed_ns=time.monotonic_ns(), event_hex=raw.hex(),
                            event_sha256=hashlib.sha256(raw).hexdigest())
            event = decode_event(raw)
            return {'event': event}

        def omit():
            nonlocal events
            try:
                return omit_read()
            finally:
                fd = events
                events = None
                os.close(fd)

        result = paused_once(pidfd, omit)
        result.update(captured)
        result.update(format='actryn-a11-omission-1', pid=pid, manager_sha256=expected,
                      event_size=EVENT_BYTES, pause_limit_ns=PAUSE_LIMIT_NS, before=before)
        # Persist only after SIGCONT, outside the bounded pause. Retain evidence
        # locally even if the invoking SSH connection loses the reply.
        with (output / 'omission.json').open('x') as stream:
            json.dump(result, stream)
            stream.flush()
            os.fsync(stream.fileno())
        directory = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        print(json.dumps(result), flush=True)
        require(result['resumed'] and 'error' not in result and 'resume_error' not in result
                and result['stopped_duration_ns'] <= PAUSE_LIMIT_NS, 'omission/resume failed or exceeded bound')
    finally:
        if events is not None:
            os.close(events)
        os.close(pidfd)


if __name__ == '__main__':
    main()
