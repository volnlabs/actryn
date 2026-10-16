#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""One fixed admin-only cold RECOVER; never load, unload, rearm or retry."""
import argparse
import fcntl
import json
import os
import pathlib
import platform
import signal
import stat
import struct
import time

import hello8

MODULE = pathlib.Path('/opt/actryn-a16/hello8/actryn_authority.ko')
SNAPSHOT = pathlib.Path('/sys/module/actryn_authority/parameters/hello8_snapshot')
NOTE = pathlib.Path('/sys/module/actryn_authority/notes/.note.gnu.build-id')
REQUEST = 0xc0c04101
STATUS = 0x80c04102


def now():
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def save(output, name, data):
    with (output / name).open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def status(fd):
    data = bytearray(192); fcntl.ioctl(fd, STATUS, data, True)
    return bytes(data)


def request_bytes(opcode, role=0):
    if (opcode, role) not in ((1, 1), (1, 4), (12, 0)):
        raise ValueError('diagnostic allows only admin/events bind and RECOVER')
    data = bytearray(192); struct.pack_into('<4I', data, 0, 1, opcode, 0, role)
    return data


def snapshot():
    raw = SNAPSHOT.read_bytes()
    if len(raw) != 3457 or not raw.endswith(b'\n'):
        raise ValueError('unexpected diagnostic8 snapshot encoding')
    return bytes.fromhex(raw[:-1].decode('ascii'))


def validate_status(data):
    if data is None or len(data) != 192:
        raise ValueError('complete status required')
    version = struct.unpack_from('<I', data)[0]
    reserved0, lost, reserved1 = (struct.unpack_from('<I', data, offset)[0]
                                 for offset in (12, 180, 188))
    if version != 1 or reserved0 or reserved1:
        raise ValueError('unsupported status version or reserved fields')
    if lost:
        raise ValueError('kernel events_lost is nonzero')


def validate_events(raw, before, after):
    validate_status(before); validate_status(after)
    if not raw or len(raw) % 216 or len(raw) > 128 * 216:
        raise ValueError('bounded complete event capture required')
    for index in range(len(raw) // 216):
        event = raw[index * 216:(index + 1) * 216]
        sequence, _, _, reserved = struct.unpack_from('<QQII', event)
        # A new unconsumed module has no earlier event stream to omit.
        if reserved or sequence != index + 1:
            raise ValueError('reserved event field or noncontiguous cold sequence')
        validate_status(event[24:])
    return {'events': len(raw) // 216, 'first_sequence': 1,
            'last_sequence': len(raw) // 216, 'events_lost': 0}


def diagnostic_success(result):
    complete = result['diagnostic'] in ('ACCEPTED_ACK', 'REJECTED_ACK', 'OTHER_CLOSURE')
    return (complete and result.get('recover_outcome') == 'RETURNED_ZERO'
            and result.get('recover_errno') == 0 and bool(result.get('event_validation'))
            and not any(key.endswith('error') for key in result))


def run(output, expected_boot, module_sha, note_sha):
    boot = pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if (boot != expected_boot or os.geteuid() != 0 or platform.node() != 'actryn-a16'
            or platform.machine() != 'aarch64' or platform.release() != '6.12.111+deb13-arm64'):
        raise ValueError('exact dedicated guest identity required')
    if MODULE.is_symlink() or not stat.S_ISREG(MODULE.stat().st_mode) or hello8.sha(MODULE.read_bytes()) != module_sha:
        raise ValueError('selected diagnostic binary changed')
    if hello8.sha(NOTE.read_bytes()) != note_sha:
        raise ValueError('loaded diagnostic build ID differs')
    if pathlib.Path('/sys/module/actryn_a16_capture').exists() or pathlib.Path('/dev/ttyAMA1').exists():
        raise ValueError('dedicated serdev-only case without other capture required')
    initial = snapshot(); initial_decoded = hello8.decode(initial)
    if any(initial_decoded[key] for key in ('count', 'attempts', 'armed', 'finished', 'dropped')):
        raise ValueError('cold diagnostic already consumed; never replay')
    output.mkdir(parents=True, exist_ok=False)
    save(output, 'initial.bin', initial)
    save(output, 'identity.json', (json.dumps(dict(boot=boot, module_sha256=module_sha,
          loaded_note_sha256=note_sha, client_sha256=hello8.sha(pathlib.Path(__file__).read_bytes()),
          decoder_sha256=hello8.sha(pathlib.Path(hello8.__file__).read_bytes()))) + '\n').encode())
    admin = events = before = after = None
    result = dict(case='cold-hello8', authority_requests=['ADMIN_BIND', 'EVENTS_BIND', 'RECOVER_ONCE'],
                  handshake='NOT_ISSUED', diagnostic='INCOMPLETE', automatic_retry=False,
                  recover_outcome='NOT_ISSUED', recover_errno=None,
                  module_unload='NOT_ATTEMPTED; operator retains identities before guarded unload')
    captured = []
    try:
        admin = os.open('/dev/actryn-authority', os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        events = os.open('/dev/actryn-authority', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        fcntl.ioctl(admin, REQUEST, request_bytes(1, 1), True)
        fcntl.ioctl(events, REQUEST, request_bytes(1, 4), True)
        before = status(admin); save(output, 'status-before.bin', before)
        validate_status(before)
        if (struct.unpack_from('<III', before) != (1, 0, 0)
                or any(before[48:112]) or any(before[168:188])):
            raise ValueError('module must have no previous session, operation, authority or fault')
        save(output, 'recover-intent.bin', request_bytes(12))
        start = now(); result['before_ns'] = start; result['handshake'] = 'OUTCOME_UNKNOWN'
        result['recover_outcome'] = 'OUTCOME_UNKNOWN'
        try:
            fcntl.ioctl(admin, REQUEST, request_bytes(12), True)
            result['recover_errno'] = 0
            result['recover_outcome'] = 'RETURNED_ZERO'
        except OSError as error:
            result['recover_errno'] = error.errno
            result['recover_exception'] = repr(error)
            # A process alarm raises TimeoutError without an errno. It is not
            # evidence of a known nonzero ioctl return or of no kernel change.
            result['recover_outcome'] = 'RETURNED_ERROR' if error.errno is not None else 'OUTCOME_UNKNOWN'
        result['after_ns'] = now()
        state = flags = 0
        deadline = start + 2_000_000_000
        while now() < deadline:
            for _ in range(128 - len(captured)):
                try:
                    event = os.read(events, 216)
                except BlockingIOError:
                    break
                if len(event) != 216:
                    raise ValueError('incomplete event or detached device')
                captured.append(event)
                state = struct.unpack_from('<I', event, 28)[0]
                flags = struct.unpack_from('<I', event, 208)[0]
            if len(captured) == 128:
                raise ValueError('event diagnostic bound exhausted')
            # No snapshot formatting or status mutex polling during HELLO.
            if state >= 4 or flags & 1 or result['recover_outcome'] != 'RETURNED_ZERO':
                break
            time.sleep(.002)
        result['handshake'] = 'ACCEPTED' if flags & 1 else ('FAULTED' if state >= 4 else 'NO_TERMINAL_STATUS')
    except BaseException as error:
        result['error'] = repr(error)
    finally:
        # No cancellation/recovery/reset is sent even on unknown ioctl outcome.
        if admin is not None:
            try:
                after = status(admin); save(output, 'status-after.bin', after)
            except BaseException as error:
                result['status_error'] = repr(error)
        try:
            save(output, 'events.bin', b''.join(captured))
        except BaseException as error:
            result['events_error'] = repr(error)
        try:
            result['event_validation'] = validate_events(b''.join(captured), before, after)
        except BaseException as error:
            result['event_validation_error'] = repr(error)
        try:
            raw = snapshot(); save(output, 'snapshot.bin', raw)
            decoded = hello8.decode(raw)
            save(output, 'decoded.json', (json.dumps(decoded, indent=2) + '\n').encode())
            result['assessment'] = hello8.qualify(decoded)
            result['diagnostic'] = result['assessment']['outcome']
        except BaseException as error:
            result['snapshot_error'] = repr(error)
        for fd in (events, admin):
            if fd is not None:
                os.close(fd)
        result['fds_closed'] = True
        save(output, 'result.json', (json.dumps(result, indent=2) + '\n').encode())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=pathlib.Path)
    parser.add_argument('expected_boot')
    parser.add_argument('module_sha256')
    parser.add_argument('loaded_note_sha256')
    args = parser.parse_args()
    def alarm(_number, _frame):
        raise TimeoutError('eight-second diagnostic process bound; never retry')
    signal.signal(signal.SIGALRM, alarm); signal.alarm(8)
    result = run(args.output, args.expected_boot, args.module_sha256, args.loaded_note_sha256)
    signal.alarm(0)
    print(json.dumps(result, indent=2))
    return 0 if diagnostic_success(result) else 1


if __name__ == '__main__':
    raise SystemExit(main())
