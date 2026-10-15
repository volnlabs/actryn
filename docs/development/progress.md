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
  `1.1.15+ds1-2+b4`. Runtime launch/isolation acceptance is still pending.
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
