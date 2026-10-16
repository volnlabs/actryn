# SPDX-License-Identifier: GPL-2.0-only
"""Independent eligibility evidence check for the common amendment-7 workload."""
import struct

MS = 1_000_000
SCENARIOS = ('normal', 'cancel', 'delayed-applied', 'owner-exit', 'normal',
             'cancel', 'delayed-applied', 'owner-exit', 'normal', 'normal')


def event_status(row):
    data = bytes.fromhex(row['bytes'])
    if len(data) != 216 or struct.unpack_from('<I', data, 24)[0] != 1:
        raise ValueError('complete canonical event required')
    sequence, captured, kind = struct.unpack_from('<QQI', data)
    if (sequence, captured, kind) != (row['sequence'], row['captured_ns'], row['kind']):
        raise ValueError('event summary disagrees with raw record')
    epoch = data[40:88]  # nonce, device, controller boot/session
    grant, instance, operation, stream = struct.unpack_from('<4Q', data, 88)
    return {'epoch': epoch, 'identity': (grant, instance, operation, stream),
            'controller': struct.unpack_from('<Q', data, 168)[0],
            'state': struct.unpack_from('<I', data, 28)[0],
            'operation_state': struct.unpack_from('<I', data, 32)[0],
            'flags': struct.unpack_from('<I', data, 208)[0]}


def qualify(rows):
    waits = [r for r in rows if r['type'] == 'first_sample_ready']
    if [r['trial'] for r in waits] != list(range(10)):
        raise ValueError('one first-sample eligibility record per trial required')
    for trial, wait in enumerate(waits):
        events = [r for r in rows if r['type'] == 'event' and r['trial'] == trial]
        hello = [r for r in events if r['kind'] == 0x20002]
        started = [r for r in events if r['kind'] == 0x20006]
        if len(hello) != 1 or len(started) != 1:
            raise ValueError('one actual HELLO_ACK and STARTED required')
        h, s = hello[0], started[0]; hs, ss = event_status(h), event_status(s)
        at = wait['eligible_at_ns']; host = h['captured_ns']; sent = host - 10 * MS
        if (host < 10 * MS or not host <= s['captured_ns'] <= at
                or at - sent >= 60000 * MS or hs['epoch'] != ss['epoch']
                or ss['controller'] < hs['controller']
                or hs['controller'] + at - host > (1 << 64) - 1
                or hs['state'] != 0 or hs['flags'] & 1 != 1
                or ss['state'] != 2 or ss['operation_state'] != 2 or ss['flags'] & 9 != 9):
            raise ValueError('ineligible epoch, lifecycle or clock interval')
        lower = hs['controller'] + at - host - ((at - sent + 9999) // 10000)
        expected = {'hello_sequence': h['sequence'], 'started_sequence': s['sequence'],
                    'hello_host_ns': host, 'hello_controller_ns': hs['controller'],
                    'started_host_ns': s['captured_ns'], 'started_controller_ns': ss['controller'],
                    'controller_lower_ns': lower, 'settle_ns': at - s['captured_ns']}
        if any(wait.get(key) != value for key, value in expected.items()) or lower - ss['controller'] < 100 * MS:
            raise ValueError('first sample lacks actual conservative 100ms credit')
        starts = [r for r in rows if r['type'] == 'request' and r['trial'] == trial and r['opcode'] == 7]
        if len(starts) != 1 or starts[0]['rc'] or starts[0]['before_ns'] > s['captured_ns']:
            raise ValueError('one accepted START before STARTED required')
        raw_start = bytes.fromhex(starts[0]['bytes'])
        if (len(raw_start) != 192 or struct.unpack_from('<II', raw_start) != (1, 7)
                or struct.unpack_from('<4Q', raw_start, 32) != ss['identity']
                or raw_start[16:32] != ss['epoch'][:16]):
            raise ValueError('STARTED does not match submitted operation')
        samples = [r for r in rows if r['type'] == 'request' and r['trial'] == trial and r['opcode'] == 8]
        count = 10 if SCENARIOS[trial] == 'normal' else 1 if SCENARIOS[trial] == 'delayed-applied' else 5
        if len(samples) != count or [r['sequence'] for r in samples] != list(range(1, count + 1)):
            raise ValueError('fixed sample count or order changed')
        for index, sample in enumerate(samples):
            data = bytes.fromhex(sample['bytes'])
            if (len(data) != 192 or sample['rc'] or sample['before_ns'] < at + index * 100 * MS
                    or struct.unpack_from('<II', data) != (1, 8)
                    or struct.unpack_from('<Q', data, 64)[0] != index + 1):
                raise ValueError('sample preceded eligibility/schedule or was rejected')
            identity = (struct.unpack_from('<Q', data, 32)[0],
                        struct.unpack_from('<Q', data, 48)[0], struct.unpack_from('<Q', data, 56)[0])
            if (identity != (ss['identity'][0], ss['identity'][2], ss['identity'][3])
                    or data[16:32] != ss['epoch'][:16] or struct.unpack_from('<ii', data, 128) != (0, 0)):
                raise ValueError('sample identity or fixed zero duty changed')
