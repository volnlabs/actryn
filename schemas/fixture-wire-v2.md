# Actryn software fixture wire v2

This encoding implements the selected kernel/controller contract for the
non-actuating QEMU preview only. It is incompatible with Shrike v1. It supplies
no physical qualification. This file is the cross-language codec source of truth.

## Encoding

Every frame is exactly 156 decoded bytes: the following 152-byte little-endian
body followed by IEEE CRC-32 of that body (reflected polynomial 0xedb88320,
initial/final xor 0xffffffff), little-endian. COBS-encode all 156 bytes and append
one zero delimiter. The maximum valid encoded frame is 158 bytes including the
delimiter. A receiver discards an overlong/malformed frame until the next zero;
invalid frames never refresh liveness. No packed C struct casts or native-endian
serialization are permitted. Reserved bytes and unsupported kinds reject.

| Offset | Type | Field |
|---|---|---|
| 0 | u16 | version, exactly 2 |
| 2 | u16 | kind |
| 4 | u32 | flags, zero |
| 8 | 16 bytes | device identity |
| 24 | u64 | controller boot counter |
| 32 | u64 | controller session counter |
| 40 | 16 bytes | host runtime nonce |
| 56 | u64 | grant generation |
| 64 | u64 | operation ID |
| 72 | u64 | stream ID |
| 80 | u64 | sequence |
| 88 | u64 | transaction ID |
| 96 | u64 | absolute expiry, controller nanoseconds |
| 104 | u64 | controller time, nanoseconds |
| 112 | i32 | left duty permille |
| 116 | i32 | right duty permille |
| 120 | i64 | left encoder ticks, simulated |
| 128 | i64 | right encoder ticks, simulated |
| 136 | u64 | context revision |
| 144 | u32 | status |
| 148 | u32 | reserved, zero |
| 152 | u32 | CRC-32 |

Kinds: HELLO=1, HELLO_ACK=2, REARM=3, BASELINE=4, START=5,
STARTED=6, SAMPLE=7, SAMPLE_APPLIED=8, QUIESCE=9, QUIESCED=10,
FAULT=11, OBSERVATION=12. Status: OK=0, INHIBITED=1, EXPIRED=2,
STALE=3, LIMIT=4, BUSY=5, PROTOCOL=6, SINK_UNKNOWN=7, PERSISTENCE=8.
Unused fields are zero, never wildcards. Replies echo the relevant complete
epoch, operation and transaction identity. Command kind-specific zero/nonzero
rules must be checked by the endpoint state machine, not merely the codec.

## Handshake and lifecycle

- Fixture startup durably increments a nonwrapping boot counter before serving;
  persistence error inhibits. A fresh launch creates a fresh inhibited lifetime.
  One locked state file owns one device identity; concurrent instances reject.
- HELLO carries a nonzero host nonce and transaction ID. Other fields are zero.
  It never actuates. While inhibited, the fixture creates a nonwrapping session,
  returns HELLO_ACK with device/boot/session/nonce/transaction and controller time.
  An active endpoint rejects HELLO; replay cannot adopt an old session.
- Host records its send/receive boot-time bounds. The response controller time
  gives a conservative offset interval. Commands use the lower offset bound minus
  drift allowance. Invalid/expired mapping closes eligibility. Simulator timing
  limits are software policy, never hardware timing evidence.
- REARM consumes the current inhibited session once, with a unique transaction.
  BASELINE establishes disabled zero and its controller timestamp. Rearm does not
  create a grant or operation. FAULT requires a fresh inhibited handshake/rearm.
- START binds a strictly increasing nonzero operation/stream and grant generation,
  original absolute operation expiry and context revision. It never actuates.
  STARTED echoes this identity. Only one operation can occupy the endpoint.
- SAMPLE carries a strictly increasing nonzero sequence, bounded duty pair and
  expiry no later than the original START expiry. An identical retained duplicate
  returns its original receipt without applying again or renewing expiry;
  changed duplicates reject; older sequences reject as retired.
- SAMPLE_APPLIED is emitted only after the synthetic sink update, includes the
  applied pair/time and encoder state, and has status OK. A parsed-only receipt
  cannot establish application. The endpoint enforces numeric and slew ceilings.
- QUIESCE retires its named operation even if START was delayed. It drops pending
  task work, disables the synthetic sink and returns QUIESCED at zero. A barrier
  cannot acknowledge a different/broader close. Normal quiescence permits a new
  operation within the live grant; expiry/reset/unknown sink latches a fault.
- All effect-bearing commands must match device/boot/session/nonce. Grant
  generations cannot decrease; operation/stream/sequence/transaction counters
  never wrap. Deadline equality is expired. Unknown command application faults.
- After a partial frame, the host may finish only its immutable original suffix
  before QUIESCE, under the original expiry and recovery limit. It cannot splice
  protective bytes into that frame or refresh its authorization.
- OBSERVATION is read-only synthetic encoder telemetry with complete session,
  context, monotonic sequence and acquisition time. It cannot authorize output.

## Simulation and testing

Default plant: while enabled, each wheel integrates `duty * elapsed_ns / 1e9`
ticks with retained fractional remainder; disabled output adds no ticks. This is
a deterministic arithmetic fixture, not a motor model. Tests drive an explicit
clock; the socket service uses monotonic time and polls expiry independently of
guest progress. Fault controls are a separate local test interface, never agent RPC.

At least one independent Python/zlib golden vector and negative corpus verifies
the Rust and C codecs. Model agreement alone is insufficient. Kernel fixtures
add every-offset writes, callbacks, urgent closure, task lifetime and teardown.
