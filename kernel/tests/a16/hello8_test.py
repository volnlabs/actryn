#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fixed diagnostic8 format and source-boundary checks; no guest contact."""
import json
import pathlib
import struct
import tempfile
import unittest
import zlib

import hello8
import hello8_client

HERE = pathlib.Path(__file__).resolve().parent
KERNEL = HERE.parent.parent


def ack(**changes):
    values = dict(status=1, boot=35, session=1, device=b'1' * 16,
                  grant=0, operation=0, stream=0, sequence=0, expiry=0,
                  left=0, right=0, context=0)
    values.update(changes)
    return values


class Predicates(unittest.TestCase):
    def test_exact_deadline_boundary_and_original_unsigned_arithmetic(self):
        self.assertEqual(hello8.predicate_mask(ack(), 11_000_000, 1_000_000), 0)
        self.assertEqual(hello8.predicate_mask(ack(), 11_000_001, 1_000_000), 1 << 12)
        self.assertEqual(hello8.predicate_mask(ack(), 0, 1), 1 << 12)

    def test_each_ack_predicate_has_distinct_bit(self):
        for bit, field in enumerate(('status', 'boot', 'session', 'device', 'grant',
                                      'operation', 'stream', 'sequence', 'expiry',
                                      'left', 'right', 'context')):
            bad = b'\0' * 16 if field == 'device' else (0 if bit < 3 else 1)
            self.assertEqual(hello8.predicate_mask(ack(**{field: bad}), 2, 1), 1 << bit)

    def test_all_failed_bits_are_retained(self):
        self.assertEqual(hello8.predicate_mask(ack(status=0, boot=0, grant=2),
                                               10_000_001, 0), 1 | 2 | 16 | 4096)


def dump(records=(), **header):
    fields = dict(version=8, record_size=208, capacity=8, count=len(records),
                  dropped=0, armed=1, finished=0, attempts=1)
    fields.update(header)
    head = struct.pack('<8s8I24s', b'A16HLO08', *fields.values(), bytes(24))
    return head + b''.join(records) + bytes((8 - len(records)) * 208)


def record(kind=2, payload=b'abc', **kw):
    values = dict(seq=1, kind=kind, at=100, first=90, other=110,
                  correlation=1, flags=0, aux=len(payload), length=len(payload))
    values.update(kw)
    return struct.pack('<II3QIIIi', *[values[k] for k in
                       ('seq', 'kind', 'at', 'first', 'other', 'correlation', 'flags', 'length', 'aux')]) + payload.ljust(160, b'\0')


def packed_ack():
    data = bytearray(156)
    struct.pack_into('<HH', data, 0, 2, 2)
    data[8:24] = b'1' * 16
    data[40:56] = b'2' * 16
    struct.pack_into('<QQ', data, 24, 35, 1)
    struct.pack_into('<Q', data, 88, 1)
    struct.pack_into('<I', data, 144, 1)
    struct.pack_into('<I', data, 152, zlib.crc32(data[:152]))
    return bytes(data)


def encoded(raw):
    output = bytearray([0]); code_at = 0; code = 1
    for byte in raw:
        if byte:
            output.append(byte); code += 1
        else:
            output[code_at] = code; code_at = len(output); output.append(0); code = 1
    output[code_at] = code
    return bytes(output)


def complete_case():
    ack_raw = packed_ack()
    request = bytearray(156)
    struct.pack_into('<HH', request, 0, 2, 1)
    request[40:56] = b'2' * 16
    struct.pack_into('<Q', request, 88, 1)
    struct.pack_into('<I', request, 152, zlib.crc32(request[:152]))
    tx = b'\0' + encoded(request) + b'\0'
    return hello8.decode(dump([
        record(kind=1, payload=b'', seq=1, at=1, first=0, other=0, correlation=0),
        record(kind=2, payload=tx, seq=2, at=10, first=10, other=20, correlation=1),
        record(kind=3, payload=encoded(ack_raw), seq=3, at=100, first=90, other=0, correlation=0, aux=0),
        record(kind=4, payload=ack_raw, seq=4, at=11_000_011, first=10, other=0, correlation=3, aux=0),
        record(kind=5, payload=ack_raw, seq=5, at=11_000_011, first=10, other=0, correlation=3, flags=4096, aux=1),
    ], finished=2))


class Case(unittest.TestCase):
    def test_partial_write_suffix_is_immutable_and_correlated(self):
        case = complete_case(); original = case['records'][1]
        suffix = dict(original, aux=79, length=79, flags=80,
                      payload_hex=original['payload_hex'][160:])
        original['aux'] = 80
        case['records'].insert(2, suffix)
        case['count'] += 1
        for index, row in enumerate(case['records']):
            row['sequence'] = index + 1
            if row['kind'] in (4, 5): row['correlation'] = 4
        self.assertEqual(hello8.qualify(case)['outcome'], 'REJECTED_ACK')
        changed = '02' if suffix['payload_hex'][:2] != '02' else '03'
        suffix['payload_hex'] = changed + suffix['payload_hex'][2:]
        with self.assertRaises(ValueError):
            hello8.qualify(case)

    def test_zero_and_negative_write_do_not_fabricate_complete_hello(self):
        for result in (0, -5, 160):
            case = complete_case(); case['records'][1]['aux'] = result
            with self.assertRaises(ValueError):
                hello8.qualify(case)

    def test_exact_rx_process_and_decision_correspondence(self):
        result = hello8.qualify(complete_case())
        self.assertEqual(result['outcome'], 'REJECTED_ACK')
        self.assertEqual(result['failed_predicates'], ['elapsed_over_10ms'])
        self.assertEqual(result['processing_minus_rx_ns'], 10_999_911)

    def test_wrong_rx_identity_and_clock_or_terminal_shape_rejected(self):
        for change in ('correlation', 'rx_bytes', 'clock', 'finished'):
            case = complete_case()
            if change == 'correlation': case['records'][4]['correlation'] = 2
            if change == 'rx_bytes': case['records'][2]['payload_hex'] = '01'
            if change == 'clock': case['records'][2]['at_ns'] = 20_000_000
            if change == 'finished': case['finished'] = 1
            with self.assertRaises(ValueError):
                hello8.qualify(case)

    def test_client_only_builds_three_exact_request_forms(self):
        for opcode in range(1, 15):
            for role in range(5):
                if (opcode, role) in ((1, 1), (1, 4), (12, 0)):
                    data = hello8_client.request_bytes(opcode, role)
                    self.assertEqual(len(data), 192)
                    self.assertEqual(struct.unpack_from('<4I', data), (1, opcode, 0, role))
                    self.assertFalse(any(data[16:]))
                else:
                    with self.assertRaises(ValueError):
                        hello8_client.request_bytes(opcode, role)


def status_bytes(**fields):
    data = bytearray(192)
    struct.pack_into('<I', data, 0, 1)
    offsets = {'version': 0, 'reserved0': 12, 'lost': 180, 'reserved1': 188}
    for name, value in fields.items():
        struct.pack_into('<I', data, offsets[name], value)
    return bytes(data)


def event_bytes(sequence=1, **fields):
    return struct.pack('<QQII', sequence, sequence * 100, 0x1000c, 0) + status_bytes(**fields)


class EventValidation(unittest.TestCase):
    def test_supported_zero_loss_contiguous_capture(self):
        result = hello8_client.validate_events(event_bytes() + event_bytes(2), status_bytes(), status_bytes())
        self.assertEqual(result['events'], 2)
        self.assertEqual(result['events_lost'], 0)

    def test_loss_in_before_event_or_after_status_rejects_success(self):
        for raw, before, after in ((event_bytes(), status_bytes(lost=1), status_bytes()),
                                    (event_bytes(lost=1), status_bytes(), status_bytes()),
                                    (event_bytes(), status_bytes(), status_bytes(lost=1))):
            with self.assertRaises(ValueError):
                hello8_client.validate_events(raw, before, after)

    def test_first_gap_interior_gap_duplicate_and_reordering_rejected(self):
        for raw in (event_bytes(2), event_bytes() + event_bytes(3),
                    event_bytes() + event_bytes(), event_bytes(2) + event_bytes()):
            with self.assertRaises(ValueError):
                hello8_client.validate_events(raw, status_bytes(), status_bytes())

    def test_status_version_and_reserved_fields_in_all_positions(self):
        for field in ('version', 'reserved0', 'reserved1'):
            bad = status_bytes(**{field: 2})
            for raw, before, after in ((event_bytes(), bad, status_bytes()),
                                        (event_bytes()[:24] + bad, status_bytes(), status_bytes()),
                                        (event_bytes(), status_bytes(), bad)):
                with self.assertRaises(ValueError):
                    hello8_client.validate_events(raw, before, after)

    def test_truncated_empty_excess_and_reserved_event_rejected(self):
        bad_reserved = bytearray(event_bytes()); struct.pack_into('<I', bad_reserved, 20, 1)
        for raw in (b'', event_bytes()[:-1], event_bytes() * 129, bytes(bad_reserved)):
            with self.assertRaises(ValueError):
                hello8_client.validate_events(raw, status_bytes(), status_bytes())
        with self.assertRaises(ValueError):
            hello8_client.validate_events(event_bytes(), status_bytes()[:-1], status_bytes())

    def test_terminal_snapshot_cannot_hide_failed_or_unknown_recover(self):
        good = dict(diagnostic='OTHER_CLOSURE', recover_outcome='RETURNED_ZERO',
                    recover_errno=0, event_validation={'events': 2, 'events_lost': 0})
        self.assertTrue(hello8_client.diagnostic_success(good))
        for bad in (good | {'recover_outcome': 'RETURNED_ERROR', 'recover_errno': 5},
                    good | {'recover_outcome': 'OUTCOME_UNKNOWN', 'recover_errno': None},
                    good | {'recover_outcome': 'NOT_ISSUED'},
                    good | {'recover_errno': None}, good | {'event_validation': None},
                    good | {'event_validation_error': 'gap'}):
            self.assertFalse(hello8_client.diagnostic_success(bad))


class Records(unittest.TestCase):
    def test_decision_mask_must_match_retained_ack_and_original_time(self):
        payload = packed_ack()
        good = record(kind=5, payload=payload, at=10_000_002, first=1, flags=4096, aux=1)
        result = hello8.decode(dump([good], finished=2))
        self.assertEqual(result['records'][0]['failed_predicates'], ['elapsed_over_10ms'])
        for bad in (record(kind=5, payload=payload, flags=4096, aux=1),
                    record(kind=5, payload=payload, flags=0, aux=1),
                    record(kind=5, payload=payload[:-1] + b'x', flags=0, aux=0)):
            with self.assertRaises(ValueError):
                hello8.decode(dump([bad], finished=2))

    def test_complete_bounded_snapshot_and_bytes(self):
        result = hello8.decode(dump([record()]))
        self.assertEqual(len(result['records']), 1)
        self.assertEqual(result['records'][0]['payload_hex'], '616263')
        self.assertEqual(result['count'], 1)

    def test_loss_and_capacity_are_not_silently_accepted(self):
        for data in (dump(dropped=1), dump(capacity=9), dump(count=9), dump(record_size=209)):
            with self.assertRaises(ValueError):
                hello8.decode(data)

    def test_truncation_unused_bytes_and_reserved_fields(self):
        valid = dump([record()])
        for data in (valid[:-1], valid + b'x', valid[:40] + b'x' + valid[41:],
                     valid[:-1] + b'x', dump([record(length=161)])):
            with self.assertRaises(ValueError):
                hello8.decode(data)

    def test_wrong_record_order_and_kind(self):
        for data in (dump([record(seq=2)]), dump([record(kind=99)])):
            with self.assertRaises(ValueError):
                hello8.decode(data)

    def test_repeated_recover_counter_disqualifies_snapshot(self):
        with self.assertRaises(ValueError):
            hello8.decode(dump(attempts=2))


class Source(unittest.TestCase):
    def test_diagnostic_denies_urgent_and_effect_paths_before_execution(self):
        result = hello8.transform_driver((KERNEL / 'actryn_driver.c').read_text())
        gate = 'if(r.opcode!=ACTRYN_BIND && r.opcode!=ACTRYN_RECOVER) return -EPERM;'
        self.assertLess(result.index(gate), result.index('ret=urgent_request(f,&r)'))
        self.assertIn('if(r->role!=ACTRYN_ADMIN && r->role!=ACTRYN_EVENTS) return -EPERM;', result)
        self.assertLess(result.index('if(h8_begin(now)) return -EALREADY;'), result.index('ret=handshake(e);'))

    def test_original_predicate_and_decision_clock_are_retained(self):
        source = (KERNEL / 'actryn_driver.c').read_text()
        result = hello8.transform_driver(source)
        self.assertTrue(hello8.HELLO_PREDICATE in result, 'original HELLO predicate absent')
        self.assertEqual(result.count('u64 now=now_ns(); unsigned long flags; const struct actryn_frame *a=&e->awaited;'), 1)
        for anchor in ('h8_decision(e,f,now,true)', 'h8_decision(e,f,now,false)',
                       'h8_rx_id[e->rx_head]', 'h8_process(e,f,now)'):
            self.assertTrue(anchor in result, anchor)

    def test_changed_base_rejected_and_no_output_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / 'derived'
            with self.assertRaises(ValueError):
                hello8.derive(KERNEL, output, override_driver=b'changed')
            self.assertFalse(output.exists())

    def test_fresh_tree_preserves_original_and_denies_existing_output(self):
        original = (KERNEL / 'actryn_driver.c').read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / 'derived'
            manifest = hello8.derive(KERNEL, output)
            self.assertEqual((KERNEL / 'actryn_driver.c').read_bytes(), original)
            self.assertIn('base_driver_sha256', manifest)
            self.assertEqual(manifest['base_driver_sha256'], hello8.DRIVER_SHA)
            self.assertTrue((output / 'DIFF8.patch').read_text().startswith('--- module16'))
            self.assertEqual(json.loads((output / 'DERIVATION8.json').read_text()), manifest)
            with self.assertRaises(FileExistsError):
                hello8.derive(KERNEL, output)


if __name__ == '__main__':
    unittest.main()
