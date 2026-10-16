#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Strict UART accepted-fragment decoder and external request correlation."""
import argparse
import json
import pathlib
import struct
import zlib

HEADER = struct.Struct('<8s4I11Q16s')
RECORD = struct.Struct('<6Qq4I158s26s')


def frame_decode(encoded):
    plain = bytearray()
    pos = 0
    while pos < len(encoded):
        code = encoded[pos]; pos += 1
        if not code or pos + code - 1 > len(encoded):
            raise ValueError('malformed COBS frame')
        plain += encoded[pos:pos + code - 1]; pos += code - 1
        if code < 255 and pos < len(encoded):
            plain.append(0)
    if len(plain) != 156 or zlib.crc32(plain[:152]) != struct.unpack_from('<I', plain, 152)[0]:
        raise ValueError('frame size or CRC mismatch')
    version, kind, flags = struct.unpack_from('<HHI', plain)
    if version != 2 or kind not in (1, 3, 5, 7, 9) or flags or any(plain[148:152]):
        raise ValueError('unsupported host command frame')
    device = bytes(plain[8:24]).hex(); boot, session = struct.unpack_from('<QQ', plain, 24)
    nonce = bytes(plain[40:56]).hex()
    grant, operation, stream, sequence, transaction, expiry, controller = struct.unpack_from('<7Q', plain, 56)
    left, right, enc_left, enc_right, context, status = struct.unpack_from('<iiqqQI', plain, 112)
    if not transaction or controller or enc_left or enc_right or status:
        raise ValueError('noncanonical command reply/status fields')
    if kind == 1:
        if not any(plain[40:56]) or any(plain[8:40]) or any(plain[56:88]) or any(plain[96:152]):
            raise ValueError('noncanonical HELLO')
    else:
        if not any(plain[8:24]) or not boot or not session or not any(plain[40:56]) or context != 1:
            raise ValueError('missing command epoch/context')
        if kind == 3 and (grant or operation or stream or sequence or expiry or left or right):
            raise ValueError('noncanonical REARM')
        if kind in (5, 7, 9) and not (grant and operation and stream):
            raise ValueError('missing operation identity')
        if kind == 5 and (sequence or not expiry or left or right):
            raise ValueError('noncanonical START')
        if kind == 7 and (not sequence or not expiry or abs(left) > 200 or abs(right) > 200):
            raise ValueError('noncanonical SAMPLE')
        if kind == 9 and (sequence or expiry or left or right):
            raise ValueError('noncanonical QUIESCE')
    return {'kind': kind, 'device': device, 'boot': boot, 'session': session, 'nonce': nonce,
            'grant': grant, 'operation': operation, 'stream': stream, 'sequence': sequence,
            'transaction': transaction, 'expiry': expiry, 'left': left, 'right': right,
            'context': context, 'decoded': plain.hex()}


def decode_capture(data):
    if len(data) < HEADER.size:
        raise ValueError('truncated capture header')
    values = HEADER.unpack_from(data)
    magic, version, size, capacity, count, started, stopped = values[:7]
    counters = dict(zip(('entries', 'returns', 'dropped', 'over_cap', 'read_failure',
                         'invalid_return', 'concurrent', 'missed', 'inflight'), values[7:16]))
    if (magic != b'A16UART4' or version != 4 or size != 256 or capacity != 4096 or count > capacity
            or any(values[-1]) or not started or stopped <= started
            or len(data) != HEADER.size + count * size):
        raise ValueError('invalid capture header or length')
    if counters['entries'] != count or counters['returns'] != count or any(
            value for key, value in counters.items() if key not in ('entries', 'returns')):
        raise ValueError('capture loss, over-cap, invalid read/return, concurrency or missed return')
    frames, pending, seen, transactions = [], bytearray(), {}, {}
    first = previous_return = previous_tty = 0
    zero = errors = sync = 0
    for index in range(count):
        row = RECORD.unpack_from(data, HEADER.size + index * size)
        sequence, entry, end, tty, buffer, requested, result, tid, cpu, flags, copied, payload, reserved = row
        if (sequence != index + 1 or not started <= entry <= end <= stopped or entry < previous_return
                or not tty or not buffer or not tid or cpu > 1 or requested > 158 or any(reserved)
                or (previous_tty and previous_tty != tty)):
            raise ValueError('record ordering, target or shape mismatch')
        if flags != (4 if result < 0 else 0) or copied != max(0, result) or copied > requested:
            raise ValueError('invalid accepted-prefix accounting')
        if any(payload[copied:]):
            raise ValueError('bytes beyond accepted prefix')
        previous_return, previous_tty = end, tty
        zero += result == 0; errors += result < 0
        for byte in payload[:copied]:
            if byte:
                if not pending:
                    first = entry
                pending.append(byte)
                if len(pending) > 157:
                    raise ValueError('overlong or missing-delimiter frame')
                continue
            if not pending:
                sync += 1
                continue
            frame = frame_decode(pending)
            frame.update({'encoded': (pending + b'\0').hex(), 'first_entry_ns': first, 'completed_ns': end})
            epoch = (frame['device'], frame['boot'], frame['session'], frame['nonce'])
            key = (*epoch, frame['transaction'])
            if key in seen and seen[key] != frame['encoded']:
                raise ValueError('changed duplicate transaction')
            if key not in seen and frame['transaction'] <= transactions.get(epoch, 0):
                raise ValueError('transaction order regressed')
            seen[key] = frame['encoded']; transactions[epoch] = max(frame['transaction'], transactions.get(epoch, 0))
            frames.append(frame); pending.clear()
    if pending:
        raise ValueError('incomplete final frame; no dispatch inference')
    return {'counters': counters, 'frames': frames, 'zero_writes': zero,
            'error_writes': errors, 'sync_delimiters': sync, 'records': count,
            'started_ns': started, 'stopped_ns': stopped}


def correlate(capture, rows):
    epochs = {}
    requests = []
    calls = [row for row in rows if row['type'] == 'request']
    dispatch_calls = [row for row in calls if row['opcode'] in (7, 8, 9, 10)]
    rejected = [{key: row[key] for key in ('trial', 'opcode', 'rc', 'before_ns', 'after_ns')}
                | {'reason': 'REQUEST_REJECTED; not an accepted-dispatch latency sample'}
                for row in dispatch_calls if row['rc']]
    for row in rows:
        if row['type'] == 'event':
            data = bytes.fromhex(row['bytes'])
            if len(data) != 216 or struct.unpack_from('<I', data, 24)[0] != 1:
                raise ValueError('event ABI mismatch')
            boot, session = struct.unpack_from('<QQ', data, 72)
            if boot and session and struct.unpack_from('<I', data, 208)[0] & 1:
                key = (row['trial'], data[40:56].hex())
                epochs.setdefault(key, set()).add((data[56:72].hex(), boot, session))
        if row['type'] != 'request' or row['rc'] or row['opcode'] not in (7, 8, 9, 10):
            continue
        data = bytes.fromhex(row['bytes'])
        if len(data) != 192 or struct.unpack_from('<II', data) != (1, row['opcode']):
            raise ValueError('request ABI mismatch')
        grant = struct.unpack_from('<Q', data, 32)[0]
        operation, stream, sequence = struct.unpack_from('<QQQ', data, 48)
        key = (data[16:32].hex(), grant, operation, stream, sequence)
        requests.append({'trial': row['trial'], 'opcode': row['opcode'], 'identity': key,
                         'before_ns': row['before_ns'], 'after_ns': row['after_ns'],
                         'deadline_ns': struct.unpack_from('<Q', data, 80)[0],
                         'context': struct.unpack_from('<Q', data, 120)[0],
                         'duties': struct.unpack_from('<ii', data, 128)})
    output = []
    for request in requests:
        kind = {7: 5, 8: 7, 9: 9, 10: 9}[request['opcode']]
        key = request['identity']
        matches = [frame for frame in capture['frames'] if frame['kind'] == kind and
                   tuple(frame[name] for name in ('nonce', 'grant', 'operation', 'stream', 'sequence')) == key]
        known = epochs.get((request['trial'], key[0]), set())
        item = {**request, 'candidate_frames': len(matches), 'status': 'UNMATCHED'}
        if len(known) != 1:
            item['status'] = 'UNKNOWN_OR_AMBIGUOUS_EPOCH'
        elif sum(other['identity'] == key and other['opcode'] == request['opcode'] for other in requests) != 1:
            item['status'] = 'AMBIGUOUS_REQUESTS'
        elif len(matches) > 1:
            item['status'] = 'AMBIGUOUS_FRAMES'
        elif len(matches) == 1:
            frame = matches[0]
            if ((frame['device'], frame['boot'], frame['session']) not in known or
                    (frame['left'], frame['right']) != request['duties'] or
                    (kind != 9 and frame['context'] != request['context'])):
                item['status'] = 'IDENTITY_OR_PAYLOAD_MISMATCH'
            elif frame['first_entry_ns'] < request['before_ns'] or request['after_ns'] < request['before_ns']:
                item['status'] = 'REVERSED_OR_REUSED_IDENTITY_TIME'
            elif kind != 9 and frame['completed_ns'] >= request['deadline_ns']:
                item['status'] = 'AT_OR_AFTER_DEADLINE'
            else:
                item.update({'status': 'MATCHED', 'transaction': frame['transaction'],
                             'completed_ns': frame['completed_ns'],
                             'request_entry_to_complete_ns': frame['completed_ns'] - request['before_ns'],
                             'write_entry_to_complete_ns': frame['completed_ns'] - frame['first_entry_ns'],
                             'completed_before_call_return': frame['completed_ns'] < request['after_ns']})
        output.append(item)
    return {'revision': 4, 'issued_request_calls': len(calls),
            'issued_dispatch_command_calls': len(dispatch_calls),
            'non_dispatch_request_calls': len(calls) - len(dispatch_calls),
            'excluded_failed_dispatch_calls': rejected, 'eligible_successful_requests': len(output),
            'matched_requests': sum(item['status'] == 'MATCHED' for item in output), 'requests': output,
            'measurement': 'external request entry to complete frame accepted by Linux serial buffer',
            'exact_internal_admission_instant': 'NOT_MEASURED', 'physical_uart_drain': 'NOT_MEASURED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=pathlib.Path)
    parser.add_argument('events', type=pathlib.Path)
    args = parser.parse_args()
    decoded = decode_capture(args.capture.read_bytes())
    rows = [json.loads(line) for line in args.events.read_text().splitlines()]
    print(json.dumps({'capture': decoded, 'correlation': correlate(decoded, rows)}, indent=2))


if __name__ == '__main__':
    main()
