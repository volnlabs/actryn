# SPDX-License-Identifier: GPL-2.0-only
import copy
import struct
import unittest
import first_sample7

MS = 1_000_000


def records():
    rows = []
    for trial, scenario in enumerate(first_sample7.SCENARIOS):
        shift = trial * 2000 * MS
        def event(kind, sequence, captured, controller, active):
            data = bytearray(216)
            struct.pack_into('<QQIIIII', data, 0, sequence, captured, kind, 0, 1, 2 if active else 0, 2 if active else 0)
            data[40:56] = b'N' * 16; data[56:72] = b'D' * 16
            struct.pack_into('<6Q', data, 72, 3, 4, 5 if active else 0, 6 if active else 0, 7 if active else 0, 8 if active else 0)
            struct.pack_into('<Q', data, 168, controller)
            struct.pack_into('<I', data, 208, 9 if active else 1)
            return {'type': 'event', 'trial': trial, 'kind': kind, 'sequence': sequence,
                    'captured_ns': captured, 'bytes': data.hex()}
        h = event(0x20002, 1 + trial * 100, 1000 * MS + shift, 2000 * MS + shift, False)
        s = event(0x20006, 2 + trial * 100, 1200 * MS + shift, 2200 * MS + shift, True)
        at = 1301 * MS + shift
        raw = bytearray(192); struct.pack_into('<II', raw, 0, 1, 7); raw[16:32] = b'N' * 16
        struct.pack_into('<4Q', raw, 32, 5, 6, 7, 8)
        start = {'type': 'request', 'trial': trial, 'opcode': 7, 'rc': 0,
                 'before_ns': 1199 * MS + shift, 'bytes': raw.hex()}
        wait = {'type': 'first_sample_ready', 'trial': trial, 'eligible_at_ns': at,
                'hello_sequence': h['sequence'], 'started_sequence': s['sequence'],
                'hello_host_ns': h['captured_ns'], 'hello_controller_ns': 2000 * MS + shift,
                'started_host_ns': s['captured_ns'], 'started_controller_ns': 2200 * MS + shift,
                'controller_lower_ns': 2301 * MS + shift - 31100, 'settle_ns': 101 * MS}
        rows.extend((h, start, s, wait))
        count = 10 if scenario == 'normal' else 1 if scenario == 'delayed-applied' else 5
        for index in range(count):
            data = bytearray(raw); struct.pack_into('<I', data, 4, 8)
            struct.pack_into('<Q', data, 64, index + 1)
            rows.append({'type': 'request', 'trial': trial, 'opcode': 8, 'rc': 0,
                         'sequence': index + 1, 'before_ns': at + index * 100 * MS, 'bytes': data.hex()})
    return rows


class Eligibility7Tests(unittest.TestCase):
    def test_fixed_ten_trial_receipts_and_sample_schedule(self):
        first_sample7.qualify(records())

    def test_poll_or_missing_receipt_cannot_replace_started(self):
        for kind in (0x20002, 0x20006):
            rows = [r for r in records() if not (r['type'] == 'event' and r['trial'] == 0 and r['kind'] == kind)]
            with self.assertRaises(ValueError):
                first_sample7.qualify(rows)

    def test_wrong_epoch_operation_or_raw_request_shape_fails(self):
        for offset in (40, 56, 72, 80, 88, 96, 104, 112):
            rows = records(); receipt = rows[2]; data = bytearray.fromhex(receipt['bytes'])
            data[offset] ^= 1; receipt['bytes'] = data.hex()
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                first_sample7.qualify(rows)
        for offset in (0, 4, 16, 32, 48, 56, 64, 128):
            rows = records(); sample = rows[4]; data = bytearray.fromhex(sample['bytes'])
            data[offset] ^= 1; sample['bytes'] = data.hex()
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                first_sample7.qualify(rows)

    def test_host_100ms_sleep_does_not_establish_mapped_100ms_credit(self):
        rows = records(); wait = rows[3]
        wait.update(eligible_at_ns=1300 * MS, controller_lower_ns=2300 * MS - 31000, settle_ns=100 * MS)
        with self.assertRaises(ValueError):
            first_sample7.qualify(rows)

    def test_early_sample_extra_sample_missing_wait_and_forged_credit_fail(self):
        rows = records(); early = copy.deepcopy(rows); early[4]['before_ns'] -= 1
        extra = copy.deepcopy(rows); extra.append(dict(rows[4]))
        missing = [r for r in rows if not (r['type'] == 'first_sample_ready' and r['trial'] == 0)]
        forged = copy.deepcopy(rows); forged[3]['controller_lower_ns'] += 1
        for bad in (early, extra, missing, forged):
            with self.assertRaises(ValueError):
                first_sample7.qualify(bad)

    def test_regressed_controller_or_u64_overflow_cannot_create_credit(self):
        for hello_ctl, started_ctl in ((2400 * MS, 2200 * MS), ((1 << 64) - 100, (1 << 64) - 50)):
            rows = records()
            for index, controller in ((0, hello_ctl), (2, started_ctl)):
                data = bytearray.fromhex(rows[index]['bytes'])
                struct.pack_into('<Q', data, 168, controller); rows[index]['bytes'] = data.hex()
            rows[3].update(hello_controller_ns=hello_ctl, started_controller_ns=started_ctl,
                           controller_lower_ns=hello_ctl + 301 * MS - 31100)
            with self.subTest(hello=hello_ctl), self.assertRaises(ValueError):
                first_sample7.qualify(rows)


if __name__ == '__main__':
    unittest.main()
