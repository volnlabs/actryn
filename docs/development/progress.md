# Implementation ledger: Actryn v0.0.1

Plan: [approved execution plan](../superpowers/plans/2026-10-16-actryn-v0.0.1.md).

## Current state

- Baseline: `65a45a6`, 19 supplied files preserved; SHA-256 snapshot retained locally.
- Integration branch: `feat/v0.0.1`; remote HEAD absent at preflight.
- M0 scope/contracts are committed; exact Debian kernel/build inputs selected.
  M1 and M2 are in implementation. M3/M4 remain incomplete. No A01-A16 row
  has a complete integrated acceptance pass.
- Host: Omarchy x86-64 kernel 7.2.5; Rust 1.92.0; QEMU, cross GCC,
  containerd/ctr/runc and protobuf compiler present. Host is not the supported
  Debian release tuple. No host kernel module or physical device will be used.
- Account quota telemetry unavailable; no quota percentage inferred.

## Component evidence (not release acceptance)

- Fixture integrated through `7861eda`: wire v2, explicit-clock controller reducer,
  persistent boot identity and bounded socket process with fault controls.
  `cargo test -p fixture-wire -p actryn-core -p controller-fixture`: 10 tests pass.
  `python3 tests/wire/generate.py --check` and `python3 tests/wire/socket_fixture.py`
  pass independently on the host. The process suite covers expiry, delayed/replayed
  receipts, retirement before START, queue exhaustion, malformed framing, restart,
  identity locking and corrupt-state refusal. This does not test the kernel path.
- Real fixed BPF observer implemented with libbpf-rs 0.27.2. Two unit tests and
  Clippy pass. `tests/observer/guest.py` passes on the Debian x86-64 guest:
  actual process/syscall tracepoints, allowed and failed access, identity rejection,
  bounded retention and reported loss. A storage-delayed unregister response was
  observed; identical retries complete, and failed durability retains the registration.
  The initial restricted unit failed attachment under Debian's
  `perf_event_paranoid=3`; SYS_ADMIN is required during attachment and both threads
  now drop all capabilities before serving. The actual guest suite also passes
  with `--service`; both threads report zero permitted/effective capabilities
  and `NoNewPrivs=1`, and authenticated registration returns ready.
  Logs remain diagnostic metadata,
  with no complete-episode or policy-attributed denial claim.
- Both QEMU guests boot Debian 13.7, cloud image `20261015-2632`, kernel package
  `6.12.111-1`. Image SHA-512 values match the Debian published manifest.
  ARM64 image/headers are `6.12.111+deb13-arm64`; x86-64 is
  `6.12.111+deb13-amd64`. This image verification used HTTPS and published hashes;
  detached-signature verification is not yet recorded.
- Server guest has containerd `1.7.24~ds1-6+deb13u1` and runc
  `1.1.15+ds1-2+b4`. Actual stopped-sandbox verification, OCI launch, broker identity/isolation and packaged-service crash recovery pass on this tuple. The guest device for io.max is the whole block device `254:0`; `254:1` was rejected by the kernel. These component runs do not close the integrated release gates.
- Evidence recorder integrated through `1f511e6`; 12 real-file tests pass on
  the integration branch. MCAP batches precede SQLite durable checkpoints;
  read/queued/durable frontiers, stalled-writer health, reserved transition
  capacity, finite disk/batch limits, source gaps and strict replay eligibility
  are covered. Manager-triggered revocation and power-cut validation remain open.
- Actual authority module revision 07 (`cc3aeb3`) builds/loads on ARM64
  `6.12.111+deb13-arm64`, exclusively bound to the second PL011 serdev child;
  `/dev/ttyAMA1` is absent. Its clean guest C selftest passes two completions
  under one grant, allocated cancellation, stale START rejection, duplicate
  checks, forked-FD rejection, exec denial, malformed requests, expiry and
  non-resurrection. Plain, lockdep, KASAN and KCSAN campaigns each pass seven
  cases. These diagnostic guests exercise production code with a mocked serdev;
  the ARM guest selftest exercises actual UART/module/fixture transport.
- Kernel archive 11 fixes a separately reproduced zero-grant REVOKE bypass of
  inhibited baseline state. The direct ARM regression now passes. Its plain,
  lockdep and KASAN campaigns pass eight cases. Initial incremental KCSAN reused
  a stale object and the eight-case validator rejected it; preserved campaign
  `11b` rebuilds the authority sources and passes all eight cases under KCSAN.
  The earlier logs, configs and binaries remain separately hash-verified.
  Adversarial dup/rights/owner-exit tests have component passes; remaining 11
  runs and broader teardown/PM/capacity coverage are still open. One fresh
  rights test failed during initial handshake with PROTOCOL, before exercising
  rights; it is retained as a setup failure, not a pass or established cause.
- Robot intent registry has 17 passing host tests, including a real SQLite
  exclusive-writer stall while cancellation remains nonblocking. Its read-only
  historical inspector cannot resume unfinished work. The authority client
  passed real UAPI layout/role checks and process-wide exec denial tests.
- Fixed native skill runtime (`5a60d9f`) has 12 passing host tests. Guest run 04
  passes on actual kernel revision 07: two target-reaching operations under one
  grant, key tombstones before proposal, duplicate/digest rejection, no
  reactivation after revoke and principal-checked history. Earlier guest runs
  are retained: the first exposed test-directory permissions; the next two
  exposed premature slew credit relative to STARTED. Runtime now waits from
  the actual STARTED receipt using a conservative controller-clock estimate.
  This validates simulated encoder behavior, not physical position accuracy.
- Server evidence/supervision (`5a99dd8`) has 29 passing host tests and strict
  Clippy. Packaged guest run 05 passes real daemon SIGKILL recovery, resource
  collection, bounded export with verified hashes, operator access and cleanup.
  Retained exports explicitly preserve unknown broker work after server death
  and unknown attempt outcome after launcher death. Service setup failures
  (account allocation and required NET_ADMIN for BPF_PROG_QUERY) remain retained.
- Robot RPC and Python SDK foundations are committed. TLS 1.3, certificate
  policy, canonical framing, gateway peer pidfd and deadline/unknown-outcome
  tests pass. The manager, gateway integration, enrollment, CLI, immutable
  packaging and end-to-end workflow are being implemented and are not accepted.
- No host kernel module was loaded and no physical interface was attached.

## Decisions

- 2026-10-16: Preserve the original root before editing normative documents.
- 2026-10-16: Use ignored worktrees for independent implementation lanes; commit
  integration changes with command-scoped identity and the requested sign-off.
- 2026-10-16: Keep runtime artifacts, credentials and raw local test recordings
  outside tracked source. Published evidence manifests may reference retained hashes.
- 2026-10-16: User selected Apache-2.0 for original userspace code; kernel GPL-2.0-only.
- 2026-10-16: Containerd Create/Start must be separate RPCs. The `ctr tasks start`
  command combines them and cannot satisfy policy verification before application start.
- 2026-10-16: Wire body layout and finite simulation budgets are frozen for initial
  cross-language implementation. They remain subject to tested corrections, with
  simultaneous codec/vector updates; they are not physical measurements.

## Required external inputs

- Authorized live-provider credentials for A13; do not inspect or reuse unrelated secrets.
- Release signing identity/material before signed artifact promotion.
- An independent developer for the human A14 acceptance run.

These do not block implementation or offline tests. They do block full release acceptance.
