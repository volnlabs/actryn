# SPDX-License-Identifier: GPL-2.0-only
"""Independent standard-library encoding of the normative fixed wire vector."""
import struct
import subprocess
import sys
import zlib

raw = bytearray(156)
struct.pack_into("<HHI", raw, 0, 2, 7, 0)
raw[8] = 1
struct.pack_into("<QQ", raw, 24, 2, 3)
raw[40] = 2
struct.pack_into("<QQQQQQQ", raw, 56, 4, 5, 6, 7, 8, 1000, 0)
struct.pack_into("<iiqqQII", raw, 112, -100, 100, 0, 0, 1, 0, 0)
struct.pack_into("<I", raw, 152, zlib.crc32(raw[:152]))
encoded = bytearray()
for run in raw.split(b"\0"):
    encoded.append(len(run) + 1)
    encoded.extend(run)
encoded.append(0)
actual = bytes.fromhex(subprocess.check_output([sys.argv[1], "--vector"], text=True))
assert actual == encoded, (actual.hex(), encoded.hex())
print("wire: independent Python struct/zlib/COBS golden vector passed")
