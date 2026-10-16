# SPDX-License-Identifier: GPL-2.0-only
import pathlib
import struct
import types
import unittest
import zlib
import amendment7
from dispatch_test import wire, workload


def load_decoder():
    module = types.ModuleType('dispatch7')
    path = amendment7.HERE / 'dispatch.py'
    exec(compile(amendment7.transform('dispatch.py', path.read_bytes()), str(path), 'exec'), module.__dict__)
    return module


def hello():
    raw = bytearray(152)
    struct.pack_into('<HH', raw, 0, 2, 1); raw[40:56] = b'N' * 16
    struct.pack_into('<Q', raw, 88, 1)
    raw += struct.pack('<I', zlib.crc32(raw))
    return b''.join(bytes([len(part) + 1]) + part for part in raw.split(b'\0')) + b'\0'


def blob(chunks, *, magic=b'A16UART7', version=7, counter=None):
    records = []
    for index, item in enumerate(chunks, 1):
        data, result = item if isinstance(item, tuple) else (item, len(item))
        accepted = data[:max(result, 0)]
        records.append(struct.pack('<6Qq4I159s25s', index, index * 10, index * 10 + 5,
                       123, 456, len(data), result, 22, 0, 4 if result < 0 else 0,
                       len(accepted), accepted, b''))
    counters = [len(records), len(records), 0, 0, 0, 0, 0, 0, 0]
    if counter is not None:
        counters[counter] = 1
    return struct.pack('<8s4I11Q16s', magic, version, 256, 4096, len(records),
                       1, 10000, *counters, b'') + b''.join(records)


class Dispatch7Tests(unittest.TestCase):
    def setUp(self):
        self.decoder = load_decoder()

    def test_full159_and_every_short_split_preserve_hello(self):
        frame = hello(); transmitted = b'\0' + frame
        self.assertEqual((len(frame), len(transmitted)), (158, 159))
        for chunks in ([transmitted], *[[transmitted[:i], transmitted[i:]] for i in range(1, 159)]):
            with self.subTest(lengths=list(map(len, chunks))):
                result = self.decoder.decode_capture(blob(chunks))
                self.assertEqual(result['sync_delimiters'], 1)
                self.assertEqual(result['frames'][0]['encoded'], frame.hex())
                self.assertEqual(result['frames'][0]['kind'], 1)

    def test_zero_error_short_returns_do_not_invent_bytes(self):
        data = b'\0' + hello()
        result = self.decoder.decode_capture(blob([(data, 3), (data[3:], 0),
                                                   (data[3:], -5), data[3:]]))
        self.assertEqual((result['zero_writes'], result['error_writes']), (1, 1))
        self.assertEqual(result['frames'][0]['encoded'], hello().hex())

    def test_old_version_and_all_loss_counters_fail(self):
        invalid = [blob([b'\0' + hello()], magic=b'A16UART4', version=4)]
        invalid += [blob([b'\0' + hello()], counter=index) for index in range(2, 9)]
        for data in invalid:
            with self.subTest(header=data[:128]), self.assertRaises(ValueError):
                self.decoder.decode_capture(data)

    def test_overcap_malformed_crc_missing_delimiter_and_padding_fail(self):
        data = b'\0' + hello()
        invalid = [blob([b'\0' + data]), blob([data[:-1]]),
                   blob([b'\xff\x01\0']), blob([data[:-2] + b'\x01\0'])]
        padding = bytearray(blob([data])); padding[-1] = 1; invalid.append(bytes(padding))
        for candidate in invalid:
            with self.subTest(candidate=candidate[:128]), self.assertRaises(ValueError):
                self.decoder.decode_capture(candidate)

    def test_exact_duplicates_retained_changed_duplicates_rejected(self):
        frame = hello(); duplicate = self.decoder.decode_capture(blob([frame, frame]))
        self.assertEqual(len(duplicate['frames']), 2)
        # A changed nonce is a different epoch, so alter transaction's command fields instead:
        # malformed HELLO duty must never be accepted as an immutable duplicate.
        raw = bytearray(152); struct.pack_into('<HH', raw, 0, 2, 1)
        raw[40:56] = b'N' * 16; struct.pack_into('<Q', raw, 88, 1); raw[112] = 1
        raw += struct.pack('<I', zlib.crc32(raw))
        changed = b''.join(bytes([len(p) + 1]) + p for p in raw.split(b'\0')) + b'\0'
        with self.assertRaises(ValueError):
            self.decoder.decode_capture(blob([frame, changed]))

    def test_matching_denominators_ambiguity_and_deadlines_stay_strict(self):
        decoded = self.decoder.decode_capture(blob([wire()]))
        result = self.decoder.correlate(decoded, workload())
        self.assertEqual((result['revision'], result['matched_requests']), (7, 1))
        duplicate = self.decoder.decode_capture(blob([wire(), wire()]))
        self.assertEqual(self.decoder.correlate(duplicate, workload())['requests'][0]['status'], 'AMBIGUOUS_FRAMES')
        rows = workload(); rows.append(dict(rows[0]))
        result = self.decoder.correlate(decoded, rows)
        self.assertEqual((result['matched_requests'], len(result['requests'])), (0, 2))
        rows = workload(); rows += [{**rows[0], 'rc': -116}, {**rows[0], 'opcode': 13}]
        result = self.decoder.correlate(decoded, rows)
        self.assertEqual((result['issued_request_calls'], result['eligible_successful_requests']), (3, 1))
        self.assertEqual(result['excluded_failed_dispatch_calls'][0]['rc'], -116)
        with self.assertRaises(ValueError):
            self.decoder.decode_capture(blob([wire(), wire(duty=1)]))
        rows = workload(); data = bytearray.fromhex(rows[0]['bytes'])
        struct.pack_into('<Q', data, 80, 15); rows[0]['bytes'] = data.hex()
        self.assertEqual(self.decoder.correlate(decoded, rows)['requests'][0]['status'], 'AT_OR_AFTER_DEADLINE')


if __name__ == '__main__':
    unittest.main()
