# SPDX-License-Identifier: GPL-2.0-only
import struct
import unittest
import zlib

import dispatch


def wire(sequence=1, transaction=4, duty=0):
    body = bytearray(152)
    struct.pack_into('<H', body, 0, 2); struct.pack_into('<H', body, 2, 7)
    body[8:24] = b'D' * 16; body[40:56] = b'N' * 16
    struct.pack_into('<QQ', body, 24, 11, 12)
    struct.pack_into('<QQQQQQ', body, 56, 13, 14, 15, sequence, transaction, 9999)
    struct.pack_into('<i', body, 112, duty); struct.pack_into('<Q', body, 136, 1)
    plain = bytes(body) + struct.pack('<I', zlib.crc32(body))
    # Independent encoder: each zero-separated run has a length byte.
    return b''.join(bytes([len(part) + 1]) + part for part in plain.split(b'\0')) + b'\0'


def blob(chunks, *, dropped=0, missed=0):
    records = []
    for index, item in enumerate(chunks, 1):
        data, result = item if isinstance(item, tuple) else (item, len(item))
        accepted = data[:max(0, result)]
        records.append(struct.pack('<6Qq4I158s26s', index, index * 10, index * 10 + 5,
                                   0x1234, 0x8888, len(data), result, 22, 0,
                                   4 if result < 0 else 0, len(accepted), accepted, b''))
    count = len(records)
    header = struct.pack('<8s4I11Q16s', b'A16UART4', 4, 256, 4096, count,
                         1, 10000, count, count, dropped, 0, 0, 0, 0, missed, 0, b'')
    return header + b''.join(records)


def workload():
    request = bytearray(192)
    struct.pack_into('<II', request, 0, 1, 8); request[16:32] = b'N' * 16
    struct.pack_into('<Q', request, 32, 13)
    struct.pack_into('<QQQ', request, 48, 14, 15, 1)
    struct.pack_into('<Q', request, 80, 5000); struct.pack_into('<Q', request, 120, 1)
    event = bytearray(216)
    struct.pack_into('<I', event, 24, 1); event[40:56] = b'N' * 16
    event[56:72] = b'D' * 16; struct.pack_into('<QQ', event, 72, 11, 12)
    struct.pack_into('<I', event, 208, 1)
    return [{'type': 'request', 'trial': 0, 'opcode': 8, 'rc': 0, 'before_ns': 2,
             'after_ns': 30, 'bytes': request.hex()},
            {'type': 'event', 'trial': 0, 'bytes': event.hex()}]


class DispatchTests(unittest.TestCase):
    def test_every_fragment_boundary_reconstructs_exact_frame(self):
        frame = wire()
        self.assertEqual(len(frame), 158)
        for cut in range(1, len(frame)):
            with self.subTest(cut=cut):
                decoded = dispatch.decode_capture(blob([frame[:cut], frame[cut:]]))
                self.assertEqual(decoded['frames'][0]['encoded'], frame.hex())
                self.assertEqual(decoded['frames'][0]['completed_ns'], 25)

    def test_only_accepted_prefix_short_zero_error_and_resync(self):
        frame = wire()
        data = blob([b'\0', (frame, 3), (frame[3:], 0), (frame[3:], -5), frame[3:]])
        decoded = dispatch.decode_capture(data)
        self.assertEqual(len(decoded['frames']), 1)
        self.assertEqual(decoded['frames'][0]['completed_ns'], 55)
        self.assertEqual((decoded['zero_writes'], decoded['error_writes'], decoded['sync_delimiters']), (1, 1, 1))

    def test_loss_missed_or_bad_crc_cannot_yield_dispatch(self):
        for data in (blob([wire()], dropped=1), blob([wire()], missed=1),
                     blob([wire()[:-2] + b'\x01\0']), blob([wire()[:-1]])):
            with self.subTest(data=data[:24]), self.assertRaises(ValueError):
                dispatch.decode_capture(data)

    def test_full_epoch_match_and_external_request_entry_latency(self):
        decoded = dispatch.decode_capture(blob([wire()]))
        result = dispatch.correlate(decoded, workload())
        self.assertEqual(result['matched_requests'], 1)
        self.assertEqual(result['requests'][0]['request_entry_to_complete_ns'], 13)
        self.assertTrue(result['requests'][0]['completed_before_call_return'])
        changed = workload(); event = bytearray.fromhex(changed[1]['bytes'])
        struct.pack_into('<Q', event, 80, 99); changed[1]['bytes'] = event.hex()
        self.assertEqual(dispatch.correlate(decoded, changed)['matched_requests'], 0)

    def test_duplicate_frames_or_requests_are_not_fastest_sample_selection(self):
        decoded = dispatch.decode_capture(blob([wire(), wire()]))
        result = dispatch.correlate(decoded, workload())
        self.assertEqual(result['matched_requests'], 0)
        self.assertEqual(result['requests'][0]['status'], 'AMBIGUOUS_FRAMES')
        rows = workload(); rows.append(dict(rows[0]))
        result = dispatch.correlate(dispatch.decode_capture(blob([wire()])), rows)
        self.assertEqual(result['matched_requests'], 0)
        self.assertEqual(len(result['requests']), 2)

    def test_changed_duplicate_and_deadline_equality_reject(self):
        with self.assertRaises(ValueError):
            dispatch.decode_capture(blob([wire(), wire(duty=1)]))
        rows = workload(); request = bytearray.fromhex(rows[0]['bytes'])
        struct.pack_into('<Q', request, 80, 15); rows[0]['bytes'] = request.hex()
        result = dispatch.correlate(dispatch.decode_capture(blob([wire()])), rows)
        self.assertEqual(result['requests'][0]['status'], 'AT_OR_AFTER_DEADLINE')

    def test_rejected_and_non_dispatch_calls_remain_in_cohort(self):
        rows = workload()
        rows.append({**rows[0], 'rc': -116})
        rows.append({**rows[0], 'opcode': 13})
        result = dispatch.correlate(dispatch.decode_capture(blob([wire()])), rows)
        self.assertEqual(result['issued_request_calls'], 3)
        self.assertEqual(result['issued_dispatch_command_calls'], 2)
        self.assertEqual(result['non_dispatch_request_calls'], 1)
        self.assertEqual(result['eligible_successful_requests'], 1)
        self.assertEqual(result['excluded_failed_dispatch_calls'][0]['rc'], -116)


if __name__ == '__main__':
    unittest.main()
