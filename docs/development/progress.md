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
- CLI `462f4f8` exposes the server and robot workflows, immutable pre-send handles,
  pairing pins and explicit unknown outcomes. Nine initial CLI tests and strict
  Clippy pass. Actual server CLI guest run 03 launches the isolated attempt,
  inspects its offline result, cancels/reaps it and verifies export hashes and
  no-overwrite behavior. Earlier harness/state and preparation-timeout runs remain
  retained. ARM64 CLI doctor reports the real manager state; full robot CLI
  mutation/export acceptance remains open.
- Robot RPC and Python SDK use TLS 1.3, local certificate policy, canonical
  framing, gateway peer pidfd and immutable deadlines. The new manager/gateway
  implementation is under integration review. Host checks currently pass seven
  manager tests, eight RPC tests and ten CLI tests; the Python SDK has eight
  passing tests. These include retired-capture export bounds, path isolation,
  active-writer exclusion, output hashes and no-overwrite behavior. Actual export
  and full lifecycle acceptance are not yet established.
- Manager guest run 02 completed local enrollment, device pin verification and
  authenticated preparation, then inhibited before GRANT when recorder progress
  exceeded its two-second ceiling. Later diagnostic fsync calls measured 3.64 s
  and 2.24 s under shared host storage contention; exact failing-write latency
  was not traced. The ceiling remains unchanged and no operation was dispatched.
- Manager guest run 03 failed during recovery before enrollment or authorization.
  A separately traced regression established that the fixture rejected a fresh
  HELLO while disabled in READY, causing the kernel receipt timeout. Fixture fix
  `e28524f` reconfirms disabled-zero sink state before accepting that fresh session;
  ACTIVE remains non-replaceable. Eleven core tests pass, including the prior
  failure and sink uncertainty. Actual updated-fixture campaigns are in progress.
- Kernel snapshot 12 adds five diagnostic cases and closes authority upon valid
  evidence of a newer paired controller epoch. All 13 cases pass separately in
  plain KUnit, lockdep, KASAN and KCSAN; the prior failing newer-epoch case is
  retained. Snapshot 12 builds on the exact ARM kernel. Its actual transport
  campaign is pending integration; diagnostic passes do not substitute for it.
- The server lane's OCI artifact guest run 01 imports a SHA-256-pinned image,
  launches its static offline proposal agent, verifies a broker-attested result,
  rejects wrong image pins and post-preparation rootfs tampering, and checks
  cancellation/cleanup. Lane integration and explicit per-artifact tool-policy
  checks are still pending; this is not the combined server-to-robot demo.
- Kernel revision 13 is integrated as `18a9a62`. Four separate diagnostic kernels
  pass 14 cases each; the exact ARM64 module passes all 12 transport scenarios
  and six additional reload checks. The latter capture the same truncated old
  observation that caused revision 12's handshake failure, now followed by a
  successful fresh acknowledgement. Malformed active traffic still faults.
  [Campaign evidence and preserved failures](../../kernel/tests/ADVERSARIAL.md)
  record the exact module, fixture, source and archive hashes. This closes those
  component regressions, not all integrated acceptance or physical gates.
- Live artifact policy `5e96ebf` pins the provider, model, prompt/schema and
  transport limits separately from the offline profile. Its host checks pass
  34 server tests, three agent tests and two packaging tests. Actual server guest
  offline regression 02 and missing-credential live run 01 pass. No provider
  request succeeded or was attempted with a real credential. Trusted Robot
  delegation is being integrated and will require a new final policy digest.
- RPC publication `d17c470` prepares bounded ciphertext before the final
  synchronous publication fence. Eleven RPC tests and strict Clippy pass,
  including real mTLS, no application send before publication, pin/DNS rejection,
  lost/mismatched responses and non-retrying short/error writes.
- Manager guest run 04 failed before authorization on clock continuity/durability.
  Its journal also exposed a separate runtime recovery failure: historical
  cumulative kernel event loss prevented the new acknowledgement from establishing
  a mapping. The old harness mistook a kernel handshake flag for runtime recovery;
  its earlier recovery phases are not accepted as passes. `8b9e438` serializes
  clock sampling with validation, adds specific clock diagnostics, and establishes
  an explicit epoch-scoped event-loss baseline without erasing old loss/captures.
  The concurrent clock and event-loss regressions pass RED/GREEN host tests.
  The exact cause of run 04's clock fault was not captured by its generic error.
- Manager guest run 05 establishes healthy clock and matched runtime recovery
  while retaining cumulative loss 3862. It then times out before authorization
  because the harness awaited a globally empty recorder despite healthy ongoing
  observations and advancing durable frontiers. Preparation readiness now requires
  the durable initial records and namespace; queued new observations need not be
  empty. Full lifecycle, manager crash, rotation and CLI export remain pending.
- Manager guest run 06, binary SHA-256
  `99570ba5b4ccaa775b656ed2d599b9e849d3a737ab3867246bc6c8780b03c5c6`,
  completes two natural operations under one grant and verifies durable absent-key
  and CLI pre-send cancellation. It fails at gateway death: two grant-revocation
  transitions replace the pending quiescence transaction and the fixture reports
  stale work, causing TRANSPORT. The complete run is FAILED; manager crash,
  identity rotation and export phases were not reached. Raw records, decoded
  diagnostics, journal and source/binary provenance remain in
  `artifacts/robotd-guest06*`. Kernel revision 14 subsequently preserves the
  original quiescence transaction across duplicate/escalated grant revocation.
- Trusted server delegation `0ce363d` adds immutable fixed-peer bindings, actual
  Robot observations, separately charged remote requests and reserved closure
  transport. Initial host checks pass 43 server and three agent tests. Independent
  review found terminal-durability, closure-worker capacity, malformed report and
  operator key-exhaustion gaps; `d58dd10` corrects these with 46 server tests
  passing. Actual combined delegation acceptance remains pending.
  CLI integration `4d6cca8` passes 18 tests and strict Clippy, including identity
  substitution rejection and reserved cancellation routing. Updated finite profile
  SHA-256 is `6b9f174af8b018e0cf95bfd282ed52b5385d364ebe7e372d54ce6a91d1d99be8`;
  prior guest results retain their original profile and binary identities.
- Release tooling `52f3fbb` adds deterministic role bundles, external Ed25519
  verification, explicit qualification attestations and inhibited immutable
  installation/update/rollback. Eighteen isolated filesystem/cryptographic tests
  pass. `becd5d3` fixes installed-slot bytecode pollution and `cc1c7c1` adds the
  daemon's read-only configuration preflight and CLI install route. Twenty release
  tests and nineteen CLI tests pass. No actual
  role installation or release signing is established by these component tests.
- Kernel revision 14 (`2b2060a`) passes 15 cases in each of plain, lockdep,
  KASAN and KCSAN, plus the focused actual ARM duplicate-revocation tests.
  Its wider campaign retains a handshake setup failure and a controller-restart
  SAMPLE rejection; those failed cases are not accepted. `edb7e5a` adds exact
  restart request/deadline diagnostics for the next separately numbered run.
- Manager guest run 07 fails during initial recovery, before enrollment or
  authorization, with healthy clock/event state but kernel PROTOCOL. A later
  traced HELLO succeeds in 3.59 ms; it does not reproduce or explain run 07.
  A separate deterministic test establishes that the worker tail can postpone
  an already queued receive wakeup. Kernel revision 15 (`b6a8854`) preserves it
  without changing the 10 ms deadline. All 16 cases pass in four diagnostic
  configurations, and one actual ARM campaign passes selftest and Ready recovery.
  Hash-pinned archives are listed in the kernel diagnostic/adversarial documents.
- Manager guest run 08 passes the full actual-module/mTLS lifecycle in 94.7 s:
  two natural completions, absent-key and pre-send cancellation, gateway death,
  explicit retirement/recovery, manager death with retained unknown outcome and
  no resubmission, identity rotation, SDK/CLI capture export and principal
  revocation. Manager SHA-256 is
  `8a9be8f50a6a241dd63d3c05297450674090589a367bd85952276f1471efeb39`;
  module SHA-256 is
  `2405de617a09b4b3beec5eaec8f83ff6ee6c0cc0a1968d091b0c5634fcff8e1e`.
  `artifacts/robotd-guest08*` retain logs, journal, exports and provenance.
  `9b84c73` exposes retirement writer readiness; read-only polling does not
  initiate recovery. Sixteen runtime host tests and strict Clippy pass; the
  separately amended ignored Rust guest test has not been rerun.
- The updated server deployment retains the pinned offline artifact and imports
  live policy `f3939843c248ec6375b3f8cd217e91b656c321b7520c56f601d886400f844237`.
  Actual configuration validation leaves DB and socket/lock metadata unchanged.
  Missing-credential campaign 03 passes with a cancelled zero-debit tombstone;
  its predecessor's obsolete empty-call-list assertion remains a recorded failure.
  No real provider request has been made.
- Offline server campaign 03 fails on a cancellation reply while observer
  retirement persistence exceeds the 500 ms IPC deadline. Normal cleanup later
  converges with both stores reaped and no remaining task. A separate actual
  delayed-fsync/EIO observer campaign proves timed-out/failed retirement retains
  all eight registrations until durable recovery, then frees exactly one slot.
  The full amended standalone offline campaign remains pending. Combined run 02
  below independently exercises the same cleanup and strict final evidence checks.
- Combined workflow harness `28f1949` initially has eight passing host self-tests for
  lineage, retained grant semantics, writer readiness, serialized public-peer
  restoration and strict final evidence checks. Fresh-install harness `416ce85`
  has four passing host-only tests. Its actual fresh-guest workflow remains open.
- The combined harness now has 12 passing host checks. Actual run 01 stops before
  attempt creation because its preflight incorrectly requires a passwd entry for
  the valid numeric operator UID 1000. `d674ae4` uses the configured numeric identity.
  Separately, `d2a0743` accepts systemd's exact root-owned read-only credential ACL
  for the configured service UID; unrelated readers and writable/public access
  remain rejected. Its captured-ACL regression and all 47 server tests pass.
- Combined offline run 02 passes the real isolated-agent -> trusted Robot ->
  kernel/serdev/fixture -> reconciliation -> cleanup/export workflow. It also
  rejects wrong peer, certificate pin and configuration before start, and rejects
  late binding of an independently running unbound agent. The completed operation
  has a durable `TargetReached` result and zero outstanding debit. Final evidence
  has no omissions or observer loss, and preserves the agent output as untrusted.
  This run exercises one operation, not the separate two-operation grant test.
  Evidence is retained in `artifacts/combined-offline-guest02*`; server SHA-256
  `5a3b8f340a2ab6853042d58f4e3f9d12d44bac8a250cf83c817f5f2637b5108f`,
  manager SHA-256
  `8192f4a960608bc592b6af8280ded61700378745b0b07dcef907b95a7d173af9`,
  and the same revision-15 module above identify the actual executables.
- `b01a098` retains the first raw kernel continuity fault and previous/current
  sequence, epoch and loss metadata in reserved evidence space before closure.
  Recorder ordinals remain distinct from external source identities. Fifteen
  evidence and nineteen runtime host tests pass; actual fault injection for this
  new record remains open. The updated manager is exercised by combined run 02.
- Release bundles now require the actual observer BPF object, corresponding
  source/build recipe and exact executable/Python/OpenSSL shared-library package
  versions. Twenty-three release tests pass. Actual installed-service startup,
  reviewed complete third-party notices and a coherent final build remain open.
- Managed observer loading (`3623ce7`) verifies the installer's fixed link chain,
  immutable manifest slot and actual BPF bytes before loading the resolved object.
  Eight observer tests pass. The assembled fixture inputs retain exact upstream
  license texts and source/version linkage; these are still unqualified test
  bundles, with disposable signing keys distinct from the release identity.
- The idle manager later latches a 10-second clock-checkpoint timeout with no
  prepared operation, grant or nonzero output. Its diagnostics are preserved in
  `artifacts/pre-fresh-guests-shutdown01`; the cause remains unmeasured. Independent
  source review finds a different race: a late successful checkpoint can hide its
  missed interval if the watchdog was also delayed. `4fc5452` closes authority
  before publishing that new progress; eleven manager tests pass. This does not
  explain the historical timeouts, which did latch correctly.
- At `4fc5452`, the full locked workspace suite passes 168 tests; two tests remain
  explicitly ignored pending their actual ARM guest prerequisites. Workspace
  formatting and strict all-target Clippy also pass. These host checks do not
  substitute for installed-runtime or exact-final-artifact acceptance.
- Fresh server installation 01 verifies the exact guest identity and prerequisite
  versions, then passes negative tuple cases but fails before staging its first
  release: stopping nonexistent services returns an error. Its durable inhibition,
  disk and failed logs remain preserved in `artifacts/install-server-guest01` and
  `.cache/qemu/install-server`. `0eca2a5` skips only confirmed absent/inactive units;
  loaded stop failures, ambiguous state and still-active units continue to reject.
  The corrected fresh campaign and successful installed startup remain open.
- A16 comparison tooling `05a5ac0` has host sanitizer, socket-lifetime, analyzer
  and fixed-profile checks. Target baseline qualification and the frozen eight-run
  comparison remain NOT_RUN; no performance advantage is claimed.
- A separate fresh A16 guest now builds the unchanged revision-15 driver and
  baseline against the exact pinned ARM kernel. The original build and source
  archive remain retained. Premeasurement amendment 2 (`73e856b`) strengthens
  terminal/grant checks and lost-start cleanup without changing the workload or
  limits; its host suite passes 21 Python checks plus C predicates/sanitizers.
  The actual protected pilot passes the kernel selftest and controller-restart
  scenario. Module SHA-256 is
  `2ba895dbabf4f07daa6c830c3af7f427abc3ceb6323089b8310ccf6db69d0270`;
  this separately built artifact is not substituted for earlier module hashes.
  Raw records are in `.cache/qemu/a16/qualification/protected01`, build metadata
  in `artifacts/a16-provision01`. The earlier restart failure is not reproduced
  or explained by this success. Userspace pilot and comparison remain open.
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
