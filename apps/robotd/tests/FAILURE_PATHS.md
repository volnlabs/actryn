# Allocated-key cancellation campaigns

`failure_paths.py` provides two separate, opt-in software campaigns against an
already installed, idle, non-actuating ARM preview guest. These are source
preparation until a separately numbered actual campaign is scheduled. Neither
campaign qualifies physical outputs or closes all of A02/A09 by itself.

The caller supplies an enrolled principal, CA/client certificate/private-key
paths, the explicit Robot leaf pin/DNS name, and the exact running manager and
loaded-module note hashes. The harness does not enroll, rotate identity, install
software, restart services, or find credentials. The existing identity and
evidence remain intact. It requires QEMU `linux,dummy-virt`, AArch64 and the pinned
`6.12.111+deb13-arm64` kernel, with live actuation and physical acceptance false.

Both modes create a production CLI SavedHandle before sending and reuse its
attempt, namespace and key in the SDK. They explicitly recover, rearm, prepare,
wait for durable preparation, grant 30 seconds and activate. The sole proposal
uses the reviewed fixed skill with targets +100/-100 ticks, a 10-second absolute
operation bound and one actual observation. Observation freshness is unchanged.
The target keeps a running fixture operation available for interruption; no
physical output claim is made.

Each mode retains an authenticated pre-fault Describe and another immediately
before its one proposal. Both must show healthy clock/runtime/event evidence,
the exact prepared binding, an active grant and no existing operation or output.
A pre-existing fault prevents gate arming/proposal submission and remains a
failed campaign. These snapshots do not guarantee that later health stays good.

## A02: first proposal reply withheld

`--mode a02` connects through `reply_gate.py`, a one-connection loopback TCP relay
with end-to-end mTLS. It forwards the handshake, Describe and Observe, then arms
the gate immediately before one SDK Propose. It forwards at most 73,728 bytes of
subsequent client ciphertext and discards at most 65,536 bytes of server
ciphertext. The whole relay is limited to 262,144 forwarded bytes and 20 seconds.
No TLS termination, reconnect, decrypted payload inspection or withheld-byte
replay occurs. It records byte counts, ciphertext hash and host timestamps.

An independent authenticated connection must observe the exact allocated
operation identity and kernel RUNNING while the original caller is still
waiting and ciphertext has been withheld. One local key Cancel uses the reserved
closure socket. The kernel must enter CLOSING/RECONCILED with CANCELLED reason
while that original call remains pending. Closing the relay must then produce
SDK `OutcomeUnknown`, with exactly one proposal invocation and no returned
proposal reply. The opaque withheld response is described as the **first
proposal reply**, not as a decoded operation-ID response; the production
protocol may initially report PendingIntent without a durable ID. The separate
query proves an actual allocation was cancelled before the original caller
received any proposal acknowledgement.

## A09: SQLite writer contention

`--mode a09` starts `sqlite_contention.py` only inside that guarded disposable
guest. The root helper verifies the fixed production `intent.sqlite`, its
ownership/mode and DELETE journal, pins the verified manager PID and helper PID
with pidfds, and takes `BEGIN EXCLUSIVE` without modifying rows. A socketpair and
host stdin control a single release. Its maximum lease is three seconds;
disconnect, exception, signal and timeout paths close/rollback, with bounded
pidfd termination if the helper does not exit. A stuck task remains explicitly
unknown. Lock and release timestamps use the kernel events' CLOCK_BOOTTIME
domain. This is **SQLite writer contention**, not a simulated fsync stall, EIO,
allocation failure or media failure.

After acquiring the lock, the SDK takes one observation and sends once. A
separate query must show PendingIntent with durable revision zero and no public
operation ID, while trusted manager kernel status shows ALLOCATED (UAPI value 6)
with the full operation identity. One reserved local Cancel must close that
same allocation while the tombstone is still non-durable. The helper releases
once before waiting for ordinary persistence. The exact terminal revision must
then be durable and reconciled. Kernel capture must contain allocation and
CANCELLED closure inside the actual lock interval, and no START or nonzero
output for that operation. Recorder two-second and clock ten-second limits are
not changed; any independent fault fails this narrow case.

## Evidence and execution

Both campaigns require CancelledDurable, matching full identity, equal terminal
and durable revisions, and actual kernel reconciliation. Then they retire once,
recover once and use production CLI export. `failure_capture.rs` is a small
read-only adapter to `evidence::Recorder::recover`; it reports bounded trusted
Kernel Transition and Runtime Execution metadata, source frontiers, gaps and
replay limitations. It rejects more than 4,096 records or a report over 4 MiB.
The harness checks one accepted proposal and one allocation for the saved key,
external sequence continuity, unchanged source loss and no missing durable
record ordinals. MetadataOnly capture remains ineligible for full execution
replay and retains `volatile_tail_unknown`; no complete replay is invented.

Build the reader before the timing window:

```sh
cargo test --locked -p actryn-robotd --test failure_capture --no-run -j 1
```

Use the emitted native `target/debug/deps/failure_capture-...` test executable as
`--reader`. The harness invokes only its ignored read-only
`decode_retired_campaign_capture` test, with explicit exported input/output
paths. Running the normal test suite never starts or mutates a guest.

The scheduled invocation is `python3 apps/robotd/tests/failure_paths.py` with
`--mode a02` or `--mode a09`, a new `--output` directory, `--cli`, `--reader`,
`--ssh-key`, `--known-hosts`, `--ca`, `--cert`, `--key`, `--principal`, `--dns`,
`--pin`, `--manager-sha256`, and `--module-note-sha256`. The disposable preview
defaults are SSH 26221 and forwarded Robot TCP 27443; both ports are explicit
options. Review the exact pinned tuple and current guest ownership before any
invocation. Do not run examples against an unscheduled guest.

Artifacts include source/binary hashes, guest boot/PID/module pins, all local
request intents and replies, CLI output even on error, the single SDK result,
read-only polling history, fault-helper details, terminal snapshot, exported
capture, production-reader output and final artifact hashes. Explicit rejections
stay distinct from unknown outcomes. Unknown mutation replies are never retried;
read-only polling may establish the resulting state. On failure, one separate
reserved Revoke attempts teardown and is recorded independently; failure and
unknown cleanup remain visible. No failed campaign is silently repeated or
converted to success.

Host checks:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/robotd/tests -p test_failure_paths.py -v
cargo test --locked -p actryn-robotd --test failure_capture -j 1
cargo clippy --locked -p actryn-robotd --test failure_capture -j 1 -- -D warnings
```
