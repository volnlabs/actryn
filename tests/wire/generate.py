#!/usr/bin/env python3
"""Independent standard-library wire oracle. Run --check to verify checked-in corpus."""
import pathlib
import struct
import sys
import zlib

ROOT = pathlib.Path(__file__).parent

def cobs(data):
    out = bytearray([0])
    mark, code = 0, 1
    for value in data:
        if value == 0:
            out[mark] = code
            mark, code = len(out), 1
            out.append(0)
        else:
            out.append(value)
            code += 1
    out[mark] = code
    return bytes(out) + b'\0'

def frame():
    body = bytearray(152)
    struct.pack_into('<HHI', body, 0, 2, 7, 0)
    body[8:24] = bytes(range(16))
    for offset, value in [(24, 3), (32, 4), (56, 5), (64, 6), (72, 7),
                          (80, 8), (88, 9), (96, 123456789), (136, 1)]:
        struct.pack_into('<Q', body, offset, value)
    body[40:56] = bytes(range(16, 32))
    struct.pack_into('<iiqq', body, 112, -100, 200, -1234, 5678)
    return bytes(body)

def build():
    body = frame()
    good = body + struct.pack('<I', zlib.crc32(body))
    cases = {'sample.hex': cobs(good)}
    corrupt = bytearray(good)
    corrupt[112] ^= 1
    cases['bad-crc.hex'] = cobs(corrupt)
    for name, offset, value in [('bad-version', 0, 1), ('bad-kind', 2, 99),
                                ('bad-flags', 4, 1), ('bad-reserved', 148, 1),
                                ('bad-status', 144, 99)]:
        changed = bytearray(body)
        changed[offset] = value
        cases[name + '.hex'] = cobs(changed + struct.pack('<I', zlib.crc32(changed)))
    cases['short.hex'] = cobs(good[:-1])
    cases['bad-cobs.hex'] = b'\xff\x01\0'
    return {name: value.hex() + '\n' for name, value in cases.items()}

if __name__ == '__main__':
    for name, value in build().items():
        path = ROOT / name
        if '--check' in sys.argv:
            assert path.read_text() == value, name
        else:
            path.write_text(value)
    print('independent Python/zlib corpus verified' if '--check' in sys.argv else 'wrote corpus')
