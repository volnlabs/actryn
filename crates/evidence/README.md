# Bounded evidence recorder

This crate implements the recorder portion of platform contract section 3. It
records software/controller facts; it does not make control decisions, implement
the operation-intent registry, prove physical behavior, or qualify storage media.
It exports no device, command-service or live-credential replay route.

The embedding manager is trusted. During preparation it supplies an immutable
`CaptureSpec` with attempt/profile/configuration identity, retention/redaction
policy and at most 32 authenticated `ProducerSpec`s. Producer identities include
session and clock domain/error bounds. The manager authenticates the source
channel **before** issuing its indexed `Producer` capability; it must never expose
the `Recorder` capability factory to an agent. Payloads contain no trusted origin
selector. An agent capability accepts only `AgentPayload`, cannot produce an
activation or completeness seal, and is never a required replay source.

`CapturePolicy::default()` is metadata-only: payload bytes are replaced by a
SHA-256 digest and original length. Trusted non-agent capabilities can call `read_metadata` for bounded structural
activation/configuration/execution/observation/intervention facts. These retained
bytes carry an explicit metadata flag; input, model output and agent payload kinds
cannot use this API. They are reported separately from retained raw payloads and
never make metadata-only captures eligible for execution replay. Full payload retention requires explicit
`FullPayload`. Hashes establish content identity, not authorship or missing state.
A supplied input is bounded by the volatile-byte policy even in metadata mode.

## Integration API

1. Call `Recorder::create(new_directory, spec, limits)` during preparation. This
   synchronously creates/syncs the immutable SQLite capture manifest and returns
   a `Recorder` plus its sole `Writer`. Existing directories reject; there is no
   automatic resume, reuse of source sessions, repair or authority restoration.
2. Bind trusted channels with `recorder.producer(index)`. Call
   `producer.read(sequence, source_time_ns, kind, payload)` to copy one record.
   This advances only that producer's `read` frontier. Sequences must increase
   without wrapping; missing sequence ranges remain explicit source gaps.
3. Call `recorder.queue_read()` to move copied records into the bounded writer
   batch. This advances `queued`; these records remain volatile.
4. Move the writer to a dedicated storage thread and call `writer.run(stop)`, or
   periodically call `writer.flush()` on such a thread. Storage never runs while
   holding the queue mutex. Neither reading, queuing, heartbeats nor health checks
   touch storage. Do not call `flush`, stop/join, or recorder creation from an
   admission, urgent cancel/revoke, or kernel closure path.
5. Independently poll `recorder.health()` at least every `limits.heartbeat`.
   `revoke_required` means close new experimental admission **and** trigger the
   existing urgent revoke path for active streams. This crate reports the need;
   the manager must actually perform closure. No continuation after detected
   health loss is authorized. Host scheduling still has no hard latency bound.

`Health.frontiers` separates `read`, `queued`, `durable` and source `gap_count` for
every producer. Reader and writer heartbeat timestamps are separate. While
records are pending, their original age expires even if readers heartbeat or
some writer batches make progress. A health loss latches until a new capture is
prepared; later disk progress cannot silently restore eligibility. Required-source
gaps also latch. A dropped/failed writer reports a fault rather than draining or
blocking a cancellation caller.

Declare `Transition` or `Intervention` on the trusted emitter used for closure
evidence. These event kinds may use reserved capacity after health loss. Reserved
capacity is finite too: overflow returns an error, increments `overflow_count`,
and remains visible without requiring a final marker to reach disk.

## Finite policy and persistence order

Defaults match the software recorder profile: 1,048,576 charged volatile bytes,
4,096 pending records, 2 seconds maximum pending age, 100 ms heartbeat. The default
transition reserve is 16,384 bytes/64 records within those totals. Records remain
charged while staged, queued **or held by a stalled writer**, until their durable
checkpoint commits. Byte accounting covers copied payload/metadata plus the
record header; allocator capacity and fixed MCAP/SQLite bookkeeping add bounded
implementation overhead. This is not an exact process-RSS ceiling.

Disk defaults are 67,108,864 bytes total reservation and 2,097,152 bytes per MCAP
batch. A batch pre-reserves its encoded/header/channel allowance before creating
a file, and a bounded file wrapper enforces that ceiling during writes. SQLite's
main-file page quota is one eighth of the disk budget; three such quotas are
reserved for the main DB and conservative rollback-journal space. SQLite uses
4 KiB pages, DELETE journaling, FULL synchronization and in-memory temp storage.
Committed MCAP file sizes consume the remaining recording budget. Exhaustion
latches `DiskCapacity`; no unfunded next file is created. These are application
logical-file reservations, not a filesystem quota or a bound on filesystem
metadata/allocator overhead. The selected filesystem must still be qualified.

Recording format 2 (manifest `ACTRYN-EVIDENCE-2`, envelope `EVR2`) adds the
explicit metadata flag. Older manifests are rejected as unsupported, never
silently interpreted with the new meaning.

Each flush writes one complete, uncompressed, unchunked MCAP batch using maintained
[`mcap` 0.25.0](https://docs.rs/mcap/0.25.0/mcap/write/struct.Writer.html), with
compression features disabled. Channels carry caller-assigned origin, producer
identity/session and clock metadata. MCAP's optional 32-bit message sequence is
zero; the recorder envelope retains the actual nonwrapping 64-bit source sequence.
The writer finishes/flushes the file, calls `sync_all`, and syncs the containing
directory **before** committing its file hash, length, record count and per-source
frontiers to SQLite. It uses pinned `rusqlite` 0.40.2 with bundled native SQLite.
There is no per-sample fsync in the control path.

## Recovery, manifest and replay

`Recorder::recover(path)` is read-only. It validates each checkpoint's complete
MCAP hash/length, decoded records, channel identity and durable source frontiers.
The first unsupported/missing/corrupt batch and all subsequent batches are
excluded from authoritative results. Uncommitted/unsupported `.mcap` files remain
untouched in `raw_remnants`, with explicit issues. A synced file without a SQLite
checkpoint is never promoted. Recovery cannot know the lost volatile read/queued
tail, so `volatile_tail_unknown` remains true; recovered frontiers assert only
what the supported durable prefix contains.

`Recovery.manifest` and `limits` retain requested streams, source identities,
clock bounds, digests, payload policy and retention/redaction. `source_summary()`
reports actually retained metadata/payload streams, durable sequence ranges and
exact source gaps separately from recorder frontiers. Typed intervention records
remain available in `records`. Remote exports must preserve each recorder's
origin and authoritative portion.

Inspection/event playback can show a partial prefix with explicit gaps and
unknown reconstructed state. `execution_replay(through_recorder_ns)` is stricter:

- A retained runtime activation boundary and retained configuration matching the
  immutable configuration digest must exist.
- Input, model output, execution and intervention prefixes must contain actual
  retained payloads. Use a retained explicit empty ledger if no intervention
  occurred; absent content cannot be replaced by its hash.
- Every declared required producer must have contiguous sequences and a trusted
  `seal_prefix(sequence, through_ns)` covering the requested interval, with all
  its requested streams actually retained. A seal is the authenticated producer's
  completeness assertion, not an independent oracle for its truth.
- Missing payloads/seals, gaps, metadata-only policy or unsupported recording
  tails make execution replay ineligible, with explicit missing reasons.

The crate only returns eligibility/data. A separate replay runner must enforce
no-device/no-live-credential execution and keep fresh inference reproduction a
separate experiment. It must never attach an eligible capture to a command route.

## Checks

```sh
cargo test -p evidence
cargo clippy -p evidence --all-targets -- -D warnings
cargo fmt -p evidence -- --check
```

Tests use real temporary SQLite and MCAP files: distinct frontiers, synced-file
loss before checkpoint, corrupt checkpoint-tail exclusion without deletion,
writer blocking while health/reader heartbeat continue, record/byte reserves,
disk/batch exhaustion, source gaps, forged agent origin and strict replay-prefix
eligibility. The stale-writer predicate was observed failing before implementation
and passes with these integration tests. No QEMU/manager closure integration,
actual power-cut test, arbitrary-media guarantee, or physical acceptance is claimed.
