# Deterministic non-actuating controller fixture

This is the native socket peer for the QEMU PL011/serdev software profile. It
updates only an in-memory synthetic sink and integer encoders. It exposes no
physical motor/device interface. Controller facts and software timing are not
physical measurements, production kernel authority, or independent safety proof.

Build and start from the repository root (Rust 1.92):

```sh
cargo build -p controller-fixture
mkdir -p /tmp/actryn-fixture
./target/debug/controller-fixture \
  --socket /tmp/actryn-fixture/wire.sock \
  --state /tmp/actryn-fixture/state \
  --admin /tmp/actryn-fixture/admin.sock
```

QEMU connects as the socket client, for example with its selected second-PL011
chardev configured as `socket,id=controller,path=/tmp/actryn-fixture/wire.sock,server=off`.
The target's machine/device-tree setup must actually bind that UART to serdev;
this process alone does not prove the QEMU/kernel path works. Only one wire
connection is retained; additional connections are immediately closed.

All wire encoders are labeled simulated by the software target and this service's
startup diagnostic. `controller_ns` counts nanoseconds from this process's
monotonic `Instant`; process restart changes durable boot before resetting that
clock. Administrative restart also increments durable boot, retains this clock's
origin, and resets to inhibited. Handshakes never arm output. REARM establishes
zero/disable, START never actuates, and SAMPLE_APPLIED follows a successful sink
update. Exact retained START/SAMPLE/QUIESCE duplicates preserve the original
receipt; changed/stale duplicates reject. Every other transaction must strictly
increase within its session. Expiry equality faults. Normal QUIESCE returns to
ready; faults and disconnect require a fresh inhibited handshake and rearm.

Command canonicalization follows wire v2. In addition, REARM, START, SAMPLE and
QUIESCE require `context=1`; HELLO has `context=0`. Only SAMPLE carries nonzero
sequence/duties. Only START/SAMPLE carry expiry. Commands carry zero controller
time, encoder values and status. REARM carries zero grant/operation/stream;
START/SAMPLE/QUIESCE require all three nonzero. HELLO carries only nonzero nonce
and transaction. Identity fields on effect-bearing commands match the full epoch.

The service polls the explicit-clock reducer independently of guest reads/writes,
nominally every 1 ms. Scheduling is host-controlled and has no hard timing bound.
Integration stops at expiry even on a late poll. The policy constants match target
revision 1: duty 200 permille, slew 1000/second with 100 ms credit cap, operation
10 seconds and sample 500 ms. At most 32 encoded output frames, one 512-byte read,
one parser frame and one 128-byte admin command are retained per loop. Overflow
faults/disconnects; partial frames time out after 500 ms and discard through the
original delimiter. Invalid frames never change authority or extend expiry.

## Persistent identity and recovery

First launch generates a random `SIM` namespace identity and durably appends boot
1. An exclusive OS file lock remains held for the process lifetime. Each restart
appends its next checked boot record and fsyncs it before serving. The original
file is never replaced. New-file directory durability is synchronized too. A
partial/invalid record, empty existing file, failed write/sync/lock, or exhaustion
refuses service. The append-only journal is capped at 65,536 bytes (3,275 boots),
so eventual servicing is explicit rather than silently reusing counters.

Preserve this state file across process/image restarts. Never copy it to a second
fixture, truncate it, or delete it to clear a fault: that would reuse identity.
Persistence recovery requires explicit operator servicing/identity replacement;
there is no automatic repair. This assumes a local filesystem honoring its lock
and fsync contracts. Actual power-cut/storage-fault qualification is outstanding.

Sockets are mode 0600 and are removed on clean shutdown. Startup refuses existing
socket paths. After an abrupt process death, confirm the former process is gone
before the operator removes its known stale socket paths; retain the state file.

## Local test controls

The separate mode-0600 Unix **datagram** admin socket is for the local test
operator only; never mount it into the agent or relay. Bind a local client socket
to receive `OK`, `ERROR`, or status. Send plain UTF-8 commands:

| Command | Effect |
|---|---|
| `status` | State, boot/session, current commanded duty, simulated ticks, queue and clock. |
| `delay N` | Delay subsequently queued output by N ns, 0..2,000,000,000. |
| `drop N` | Drop the next N command/fault receipts, 0..32; telemetry is excluded. |
| `replay` | Enqueue the last command/fault receipt unchanged; telemetry is excluded. |
| `pause-rx N` | Pause wire input for up to 2 seconds while controller expiry still polls. |
| `sink-fail` | Fail the next synthetic sink update; emits no successful applied receipt. |
| `restart` | Disable, durably increment boot and return inhibited; retire queued bytes/parser and emit a synchronization delimiter. |
| `shutdown` | Disable and exit cleanly. |

Controls introduce no agent wire kinds or RPC authority. Delay zero affects new
queue entries only. Replay adds no controller effect. Restart is an injected
controller reset, so an already partially transmitted receipt can become a
malformed frame. Reset emits an immediate zero delimiter, and each fresh HELLO_ACK
starts with another zero delimiter. Short writes preserve delimiter progress.
Already transmitted bytes cannot be retracted; the host must discard malformed
prefixes only during inhibited nonce-bound handshake recovery. Active parser
errors still fail closed. This is stream synchronization, not an epoch bypass.

## Verification

```sh
cargo test -p fixture-wire -p actryn-core -p controller-fixture
cargo clippy -p fixture-wire -p actryn-core -p controller-fixture --all-targets -- -D warnings
python3 tests/wire/generate.py --check
cargo build -p controller-fixture
python3 tests/wire/socket_fixture.py
```

Python uses its own framing/field code and standard-library `zlib` CRC, including
checked-in negative vectors. The socket suite launches the actual executable and
checks delayed receipts after independent expiry, complete-epoch replay rejection,
retirement before START, drop/replay, malformed input, partial timeout, bounded
queue overflow, administrative negatives, lock exclusion, durable boot increments
and corrupt-state refusal. It does not exercise QEMU, the kernel driver, physical
hardware, actual torn storage writes, or Linux scheduling bounds.
