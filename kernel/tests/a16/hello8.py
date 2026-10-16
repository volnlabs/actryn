#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Derive and decode one fixed cold-HELLO diagnostic; no build or guest actions."""
import argparse
import difflib
import hashlib
import json
import pathlib
import struct
import zlib

HERE = pathlib.Path(__file__).resolve().parent
DRIVER_SHA = '0b63292e70ed1874cfd6cd178bea4178fca33e82970cc20550cf72e535550e28'
BASE = {
    'actryn_driver.c': DRIVER_SHA,
    'actryn_wire.c': '8873973e17c4fa8bd3a9a7875fb037faabbf391fadcfcc65159824cdc57362ca',
    'actryn_wire.h': '74956048d120c7b45726202a58701f8507c17f220a87cf6c958fd4c0421aa018',
    'actryn_control.h': '813b753af6f5dd2f23e9f255cce6b34bfd71b548a000ceb52db8d4b17b062133',
    'include/uapi/linux/actryn_authority.h': 'bab4e0b968193bef83b6e082c656cb8c2b101ccd04239729c48c731394d81261',
}
HELLO_PREDICATE = '''  if(f->status!=1 || !f->boot || !f->session || is_zero(f->device,16) ||
     f->grant || f->operation || f->stream || f->sequence || f->expiry ||
     f->left || f->right || f->context || now-e->hello_sent>10*MS) {'''
HEADER = struct.Struct('<8s8I24s')
RECORD = struct.Struct('<II3QIIIi160s')
PREDICATES = ('status_not_one', 'boot_zero', 'session_zero', 'device_zero',
              'grant_nonzero', 'operation_nonzero', 'stream_nonzero',
              'sequence_nonzero', 'expiry_nonzero', 'left_nonzero',
              'right_nonzero', 'context_nonzero', 'elapsed_over_10ms')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('exact source anchor changed: ' + repr(old))
    return text.replace(old, new)


def transform_driver(source):
    if sha(source.encode()) != DRIVER_SHA:
        raise ValueError('module16 driver source changed')
    out = replace(source, ' unsigned int rx_head, rx_tail, rx_count;',
                  ' unsigned int rx_head, rx_tail, rx_count;\n u32 h8_rx_id[RX_COUNT],h8_processing_id;')
    out = replace(out, 'static bool admin(void)', '#include "actryn_hello8.h"\nstatic bool admin(void)')
    out = replace(out, ' spin_unlock_irqrestore(&e->control_lock,flags);\n return ret;\n}',
                  ' spin_unlock_irqrestore(&e->control_lock,flags);\n h8_close(rank,reason,ret);\n return ret;\n}')
    out = replace(out, ' lockdep_assert_held(&e->authority);\n if(f->kind==AW_HELLO_ACK',
                  ' lockdep_assert_held(&e->authority);\n h8_process(e,f,now);\n if(f->kind==AW_HELLO_ACK')
    out = replace(out, HELLO_PREDICATE + '\n   fault(e,ACTRYN_PROTOCOL); return;\n  }',
                  HELLO_PREDICATE + '\n   h8_decision(e,f,now,true);\n   fault(e,ACTRYN_PROTOCOL); return;\n  }\n  h8_decision(e,f,now,false);')
    out = replace(out, ' n=serdev_device_write_buf(e->serdev,e->tx+e->tx_off,e->tx_len-e->tx_off);',
                  ' n=serdev_device_write_buf(e->serdev,e->tx+e->tx_off,e->tx_len-e->tx_off);\n h8_tx(e,now,n);')
    out = replace(out, 'if(e->rx_count) { f=e->rx[e->rx_tail];',
                  'if(e->rx_count) { e->h8_processing_id=e->h8_rx_id[e->rx_tail]; f=e->rx[e->rx_tail];')
    out = replace(out, ' unsigned long flags; size_t i; bool bad=false;',
                  ' unsigned long flags; size_t i; bool bad=false; u64 h8_now=0; int h8_decoded=0;')
    out = replace(out, '    if(e->rx_count==RX_COUNT) bad=true;\n    else if(now_ns()-e->parser_started>=500*MS ||\n       actryn_decode(e->parser,e->parser_len,&e->rx[e->rx_head])) {\n     if(now_ns()>=e->parser_sync_deadline) bad=true;\n    }\n    else { e->rx_head=(e->rx_head+1)%RX_COUNT; e->rx_count++; }',
                  '    h8_now=0; h8_decoded=0;\n'
                  '    if(e->rx_count==RX_COUNT) { bad=true; h8_rx(e,0,-ENOSPC); }\n'
                  '    else if((h8_now=now_ns())-e->parser_started>=500*MS ||\n'
                  '       (h8_decoded=actryn_decode(e->parser,e->parser_len,&e->rx[e->rx_head]))) {\n'
                  '     if(now_ns()>=e->parser_sync_deadline) bad=true;\n'
                  '     h8_rx(e,h8_now,h8_decoded);\n'
                  '    }\n'
                  '    else { e->h8_rx_id[e->rx_head]=h8_rx(e,h8_now,0);\n'
                  '     e->rx_head=(e->rx_head+1)%RX_COUNT; e->rx_count++; }')
    out = replace(out, ' if(r->opcode==ACTRYN_BIND) {\n',
                  ' if(r->opcode==ACTRYN_BIND) {\n  if(r->role!=ACTRYN_ADMIN && r->role!=ACTRYN_EVENTS) return -EPERM;\n')
    out = replace(out, ' switch(r->opcode) {\n case ACTRYN_HANDSHAKE: case ACTRYN_RECOVER:',
                  ' if(r->opcode!=ACTRYN_RECOVER) return -EPERM; /* Diagnostic8: no authority issuance. */\n'
                  ' switch(r->opcode) {\n case ACTRYN_HANDSHAKE: case ACTRYN_RECOVER:')
    out = replace(out, '  ret=handshake(e); break;',
                  '  if(h8_begin(now)) return -EALREADY;\n  ret=handshake(e); break;')
    # Urgent commands otherwise execute before do_request's whitelist.
    out = replace(out, ' ret=urgent_request(f,&r); if(ret) return ret;',
                  ' if(r.opcode!=ACTRYN_BIND && r.opcode!=ACTRYN_RECOVER) return -EPERM;\n'
                  ' ret=urgent_request(f,&r); if(ret) return ret;')
    out = replace(out, 'MODULE_DESCRIPTION("Actryn software fixture typed authority and serdev backend");',
                  'MODULE_DESCRIPTION("Actryn diagnostic8 cold HELLO only; not production module16");')
    return out


def predicate_mask(frame, now, sent):
    failed = [frame['status'] != 1, not frame['boot'], not frame['session'],
              not any(frame['device'])]
    failed += [bool(frame[key]) for key in ('grant', 'operation', 'stream',
                                           'sequence', 'expiry', 'left', 'right', 'context')]
    failed.append(((now - sent) & ((1 << 64) - 1)) > 10_000_000)
    return sum(int(value) << bit for bit, value in enumerate(failed))


def unpack_frame(data):
    if len(data) != 156 or zlib.crc32(data[:152]) != struct.unpack_from('<I', data, 152)[0]:
        raise ValueError('decoded frame size/CRC')
    version, kind, flags = struct.unpack_from('<HHI', data)
    if version != 2 or kind not in range(1, 13) or flags or any(data[148:152]):
        raise ValueError('decoded frame canonical header')
    values = {'kind': kind, 'device': data[8:24], 'nonce': data[40:56]}
    values.update(zip(('boot', 'session'), struct.unpack_from('<QQ', data, 24)))
    values.update(zip(('grant', 'operation', 'stream', 'sequence', 'transaction',
                       'expiry', 'controller_ns'), struct.unpack_from('<7Q', data, 56)))
    values.update(zip(('left', 'right', 'left_encoder', 'right_encoder', 'context',
                       'status'), struct.unpack_from('<iiqqQI', data, 112)))
    return values


def decode(data):
    if len(data) != 1728:
        raise ValueError('diagnostic snapshot size')
    magic, version, size, capacity, count, dropped, armed, finished, attempts, reserved = HEADER.unpack_from(data)
    if (magic != b'A16HLO08' or version != 8 or size != 208 or capacity != 8 or count > 8
            or dropped or armed > 1 or finished > 3 or attempts > 1 or any(reserved)
            or any(data[HEADER.size + count * size:])):
        raise ValueError('diagnostic format, loss, retry, or unused bytes')
    rows = []
    for index in range(count):
        seq, kind, at, first, other, correlation, flags, length, aux, payload = RECORD.unpack_from(data, HEADER.size + index * size)
        if seq != index + 1 or kind not in range(1, 7) or length > 160 or any(payload[length:]):
            raise ValueError('record sequence, type or bounded payload')
        row = dict(sequence=seq, kind=kind, at_ns=at, first_ns=first, other_ns=other,
                   correlation=correlation, flags=flags, aux=aux, length=length,
                   payload_hex=payload[:length].hex())
        if kind == 5:
            frame = unpack_frame(payload[:length])
            mask = predicate_mask(frame, at, first)
            if frame['kind'] != 2 or flags != mask or aux not in (0, 1) or bool(mask) != bool(aux):
                raise ValueError('decision disagrees with original predicate fields/time')
            row['failed_predicates'] = [name for bit, name in enumerate(PREDICATES) if mask & (1 << bit)]
        rows.append(row)
    return dict(version=version, count=count, armed=armed, finished=finished,
                attempts=attempts, dropped=dropped, records=rows)


def qualify(decoded):
    rows = decoded['records']
    if (decoded['armed'] != 1 or decoded['attempts'] != 1 or not rows
            or rows[0]['kind'] != 1 or sum(row['kind'] == 1 for row in rows) != 1):
        raise ValueError('one recorded RECOVER required')
    if not decoded['finished']:
        return {'outcome': 'INCOMPLETE_NO_TERMINAL_RECORD'}
    last = rows[-1]
    if decoded['finished'] == 3:
        if last['kind'] != 6:
            raise ValueError('closure terminal shape')
        return {'outcome': 'OTHER_CLOSURE', 'rank': last['correlation'], 'reason': last['flags']}
    if last['kind'] != 5 or last['aux'] != decoded['finished'] - 1:
        raise ValueError('decision terminal shape')
    if sum(row['kind'] == 5 for row in rows) != 1:
        raise ValueError('exactly one terminal decision required')
    rx = [row for row in rows if row['kind'] == 3 and row['sequence'] == last['correlation']]
    process = [row for row in rows if row['kind'] == 4 and row['correlation'] == last['correlation']]
    if len(rx) != 1 or len(process) != 1:
        raise ValueError('unambiguous RX/processing correlation required')
    rx, process = rx[0], process[0]
    if (rx['flags'] or rx['aux'] or process['flags'] or process['aux']
            or not rx['sequence'] < process['sequence'] < last['sequence']
            or not 0 < rx['first_ns'] <= rx['at_ns'] <= process['at_ns']
            or any(process[key] != last[key] for key in ('at_ns', 'first_ns', 'payload_hex'))):
        raise ValueError('RX, matching predicate, processing or decision disagreement')
    raw = unstuff(bytes.fromhex(rx['payload_hex']))
    if raw.hex() != last['payload_hex']:
        raise ValueError('raw RX is not the exact processed ACK')
    ack = unpack_frame(raw)
    tx = [row for row in rows if row['kind'] == 2]
    if not tx or any(row['aux'] < 0 or row['aux'] > row['length'] for row in tx):
        raise ValueError('HELLO transmit not fully observed')
    progress = 0
    immutable = bytes.fromhex(tx[0]['payload_hex'])
    for row in tx:
        if (row['flags'] != progress or row['correlation'] != 1
                or row['other_ns'] < row['at_ns']
                or bytes.fromhex(row['payload_hex']) != immutable[progress:]):
            raise ValueError('HELLO partial-write identity/progress mismatch')
        progress += row['aux']
    accepted = b''.join(bytes.fromhex(row['payload_hex'])[:row['aux']] for row in tx)
    if not accepted.startswith(b'\0') or not accepted.endswith(b'\0') or b'\0' in accepted[1:-1]:
        raise ValueError('one synchronized immutable HELLO required')
    hello = unpack_frame(unstuff(accepted[1:-1]))
    if (hello['kind'] != 1 or hello['nonce'] != ack['nonce']
            or hello['transaction'] != ack['transaction']
            or last['first_ns'] != tx[-1]['first_ns']):
        raise ValueError('HELLO/ACK identity or original send timestamp mismatch')
    if not any(hello['nonce']) or any(hello['device']) or any(hello[key] for key in
            ('boot', 'session', 'grant', 'operation', 'stream', 'sequence', 'expiry',
             'controller_ns', 'left', 'right', 'left_encoder', 'right_encoder', 'context', 'status')):
        raise ValueError('noncanonical HELLO')
    return {'outcome': 'REJECTED_ACK' if last['aux'] else 'ACCEPTED_ACK',
            'failed_predicates': last['failed_predicates'], 'hello_sent_ns': last['first_ns'],
            'rx_first_ns': rx['first_ns'], 'rx_delimiter_ns': rx['at_ns'],
            'processing_ns': last['at_ns'],
            'processing_minus_hello_sent_ns': (last['at_ns'] - last['first_ns']) & ((1 << 64) - 1),
            'processing_minus_rx_ns': last['at_ns'] - rx['at_ns'],
            'claim': 'This derived diagnostic case only; not an attribution of uninstrumented pilot07.'}


def unstuff(data):
    if not 0 < len(data) < 158:
        raise ValueError('bounded COBS record required')
    plain = bytearray(); index = 0
    while index < len(data):
        code = data[index]; index += 1
        if not code or index + code - 1 > len(data) or 0 in data[index:index + code - 1]:
            raise ValueError('invalid COBS record')
        plain += data[index:index + code - 1]; index += code - 1
        if code < 255 and index < len(data):
            plain.append(0)
    unpack_frame(plain)
    return bytes(plain)


def derive(kernel, output, override_driver=None):
    inputs = {}
    for name, expected in BASE.items():
        path = kernel / name
        if path.is_symlink():
            raise ValueError('symlink source')
        data = override_driver if name == 'actryn_driver.c' and override_driver is not None else path.read_bytes()
        if sha(data) != expected:
            raise ValueError('pinned module16 input changed: ' + name)
        inputs[name] = data
    driver = transform_driver(inputs['actryn_driver.c'].decode()).encode()
    files = inputs | {'actryn_driver.c': driver, 'actryn_hello8.h': (HERE / 'actryn_hello8.h').read_bytes(),
                     'tools/hello8.py': pathlib.Path(__file__).read_bytes(),
                     'tools/hello8_client.py': (HERE / 'hello8_client.py').read_bytes(),
                     'Makefile': b'obj-m += actryn_authority.o\nactryn_authority-y := actryn_driver.o actryn_wire.o\nccflags-y += -I$(src)/include/uapi\n'}
    patch = ''.join(difflib.unified_diff(inputs['actryn_driver.c'].decode().splitlines(True),
                    driver.decode().splitlines(True), fromfile='module16/actryn_driver.c', tofile='diagnostic8/actryn_driver.c'))
    manifest = {'diagnostic': 8, 'production_module_changed': False, 'base_driver_sha256': DRIVER_SHA,
                'original_inputs': BASE, 'outputs': {k: sha(v) for k, v in files.items()},
                'transform_sha256': sha(pathlib.Path(__file__).read_bytes()), 'diff_sha256': sha(patch.encode()),
                'native_compile': 'NOT_RUN', 'target_case': 'NOT_RUN'}
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        path = output / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
    (output / 'DIFF8.patch').write_text(patch)
    (output / 'DERIVATION8.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    derive_args = commands.add_parser('derive'); derive_args.add_argument('output', type=pathlib.Path)
    decode_args = commands.add_parser('decode'); decode_args.add_argument('snapshot', type=pathlib.Path)
    args = parser.parse_args()
    result = derive(HERE.parent.parent, args.output) if args.command == 'derive' else decode(args.snapshot.read_bytes())
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
