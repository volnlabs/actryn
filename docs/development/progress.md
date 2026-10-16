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

### Subsequent installation and evidence checks

- Fresh server installation 02 preserves all 27 payload hashes but fails exact
  mode verification: the caller's umask 0077 produces 0600/0700 payload entries.
  Its disk and partial slot remain retained. `0a7c96f` explicitly sets modes only
  on new entries, with 0700/0600 installer state and unchanged existing private
  configuration. All 25 release tests pass. The actual 69,898,240-byte payload
  also passes stage, activation, interrupted pointer update, recovery, rollback,
  resume and preflight under umask 0077 in an isolated host directory using the
  existing fake platform. `artifacts/install-server-host03` records this filesystem
  check; guest startup and platform behavior are not established by it.
- Raw A16 boot 01 fails before console/SSH. The original padded device tree is
  1,048,576 bytes; QEMU's source-defined expansion exceeds ARM64's 2 MiB limit.
  The failed input, empty console and QMP diagnostics remain retained. Environment
  amendment 3 (`0ef8dca`) pins a separately compacted, semantically identical
  8,268-byte tree and a new boot command; original source/build pins are unchanged.
  Raw boot 02 succeeds on the exact kernel with `/dev/ttyAMA1` available and no
  authority device. `ec3a1fe` checks systemd's resolved executable path while
  preserving the remaining frozen arguments exactly; six guard tests pass.
- The actual userspace A16 correctness pilot passes all ten fixed scenarios with
  zero new event loss. Separate ownership checks cover inherited/SCM_RIGHTS FDs
  and owner exit. Both pilot and environment guard pass; evidence remains under
  `.cache/qemu/a16/qualification/{userspace01,environment3-userspace01}` for boot
  `508df926-66e8-4fd0-a7ee-830d37017571`. The eight-run comparison and common UART
  tracing remain NOT_RUN. No performance or physical claim follows from this pilot.
- `45910e4` adds an opt-in actual source-omission harness and a read-only adapter
  to the production checkpoint/MCAP reader. It uses a bounded manager pause and
  exactly one existing EVENTS read, without granting or activating authority.
  Seven Python and twelve manager/all-target Rust checks pass. Actual omission,
  durable fault retention and replay rejection remain pending the scheduled guest
  run; manager revision 10 is built but has not yet been exercised in a guest.
- Fresh server installation 03 passes actual mismatch rejection, staging,
  activation, interruption after the durable pointer update, recovery and
  rollback. Configuration/state/evidence sentinels remain intact; the harness
  finishes inhibited without starting services. Raw records are in
  `artifacts/install-server-guest03`. A separate positive bootstrap imports the
  shipped offline OCI artifact through the installed CLI, verifies configuration
  and explicitly resumes while services remain inactive; installed execution
  is still being tested separately.
- Manager revision 10 is now deployed on the original ARM guest, SHA-256
  `c198a0f61a9c6c8709b013555cef522982a6f75b45d3efb44be6387dd31f9eb7`,
  with the unchanged revision-15 module. Source omission 01 pauses its threads
  for 39,884,911 ns and consumes exactly event 81. The manager detects 80 -> 82,
  inhibits authority and durably records the raw fault with zero FIFO loss.
  Clock health remains valid; no grant or operation is issued. Retirement and
  explicit recovery complete. The harness then fails before any export RPC
  because its SDK-only handle lacks CLI-local fields; that failure is retained.
- A separately recorded read-only export amendment preserves the same attempt,
  namespace and key, supplies the CLI fields, and exports the original capture
  without repeating the omission or a Robot mutation. The production reader
  validates all 66 records, the original sequence gap at recorder ordinal 32,
  source gap count 1, contiguous recorder ordinals, no checkpoint/remnant errors
  and execution replay ineligibility. Evidence is retained in
  `artifacts/robot-source-gap-01-export-amendment2`; the original campaign remains
  a harness failure. The corrected harness creates handles through the production
  CLI and preserves failed command output; nine host tests pass. This establishes
  the actual omission path, not every A11 case or FIFO-overflow behavior.
- Common UART trace helper `a97b093` has six passing host guard/restoration tests.
  Its pointer/count trace has no immutable-frame correlation and remains target
  NOT_RUN. Full dispatch measurement and the frozen A16 comparison remain open.

### Installed runtime and allocated-key campaign checks

- Fresh server 03 now passes installed-slot offline execution, independent sandbox
  inspection, cancellation and six-artifact export validation. Explicit service
  stop/start preserves both reaped attempt histories and the original single
  stdout record, with no observed reexecution. The earlier read-only restart
  precheck failure remains retained. Evidence is in
  `artifacts/install-server-positive03`; the fixture signing identity is not a
  publication identity. `6860bd4` ships the corresponding fresh-server recipe;
  its shell/Python syntax and resume-parser checks pass without executing host
  commands. The earlier immutable installed slot contains its original guide.
- A documentation-editing heredoc error sent trailing example commands to the
  development host shell. The attempted Actryn service start failed polkit
  authentication; inspected Actryn binary, service, configuration and state
  paths are absent. Exact command/output, interval and read-only metadata checks
  are retained under `artifacts/install-server-positive03/host-command-incident`
  and `artifacts/host-doc-edit-audit01`. No full preincident filesystem snapshot
  exists; the audit does not claim byte identity of the whole host. Subsequent
  documentation edits use structured patches and nonexecuting syntax checks.
- `aced594` adds separate bounded A02 reply-loss and A09 SQLite writer-contention
  campaigns using the production CLI/SDK and a production capture-reader adapter.
  Fourteen focused Python checks pass after integration. The agent also ran the
  native reader test and strict Clippy. Actual A09 remains NOT_RUN.
- Actual A02 reply-loss 01 fails before allocation: recorder PendingAge and
  WriterStopped inhibit the runtime, the query has no request snapshot, and the
  kernel has no operation. The relay withholds 133 ciphertext bytes and the sole
  SDK proposal returns OutcomeUnknown without resend. A separate cleanup revoke
  is recorded. Explicit postfailure retirement/recovery then exports 177 durable
  records with no missing record ordinals or raw remnants; this does not turn the
  original campaign into a pass. Raw evidence and hashes are in
  `artifacts/robot-a02-replyloss-01` and its `-retirement`/`-diagnostic` directories.
  A prior host-only launch assertion selected the wrong worktree CLI and stopped
  before guest access; its separate prelaunch record is retained.
- A bounded idle-guest durability diagnostic writes twelve new 4 KiB files and
  measures file fsync at approximately 49–61 ms. These later samples and PSI
  readbacks do not explain the earlier two-second pending-data breach. Recorder
  and clock limits remain unchanged; no failed mutation is automatically retried.
- `83128e1` freezes a test-only UART accepted-prefix capture module and strict
  frame correlation for A16. All 42 host Python checks plus sanitizer/native
  helper checks pass; the module builds against the exact ARM kernel headers.
  Target loading remains NOT_RUN. A passive preflight rejects the kernel's
  legitimate `7 (expanded: 1408)` trace-buffer format; a separately numbered
  preexecution amendment is required before the instrumentation pilot. No
  software latency, physical drain or timing-bound claim follows from the build.

- Installed-server capacity 01 passes on fresh server 03. With one agent running,
  rejected preparations and a rejected second launch preserve its PID/start time
  and original attested stdout. Cancelling the staged attempt frees preparation
  capacity. All three accepted attempts finish cancelled/reaped in both stores,
  with no cgroup or extra denied-request accounting. Root independently verifies
  three complete exports and all eighteen artifact hashes. `a34dc2d` adds the
  harness and nine passing host checks, including hash-valid semantic corruption
  counterexamples. Evidence: `artifacts/server-installed-capacity01`. This does
  not cover delayed retirement or broker-call pressure. The guest is then
  gracefully powered off with its disk preserved and every attempt reaped.
- Closer inspection of A02 failure 01 finds PendingAge before the proposal: the
  writer's durable frontier stalls while batch 23 contains records more than
  2.6 seconds old. WriterStopped follows final draining and retirement. The
  capture does not distinguish fsync delay from writer descheduling. `2ec9da0`
  adds pre-send clock/runtime/source-health and binding checks; sixteen focused
  Python checks pass. No production timeout or limit changes.
- Actual A09 writer-contention 01 acquires and releases the production SQLite
  exclusive lock in 37,901,744 ns without modifying rows. Its existing SDK
  observation connection closes during SSH helper setup, before any proposal is
  sent. The campaign remains FAIL, with a separate revoke, retirement/recovery
  and production-reader export in `artifacts/robot-a09-contention-01-retirement`.
  This is a harness transport failure, not evidence of successful allocated-key
  cancellation under storage contention. Reuse of a separately owned SSH
  connection is being reviewed before a separately numbered campaign.
- Instrumentation amendment 5 (`506720b`) preserves all frozen A16 module and
  decoder inputs, replacing only the passive tracefs guard. Five host regression
  tests pass, including the exact lazy-buffer display and foreign-trace rejection.
  Both amendment hashes are retained before module loading; target pilots remain
  NOT_RUN.

- `c04146e` gives failure campaigns one owned SSH transport and disables silent
  network fallback if its control socket disappears. Three new host checks pass,
  including a real OpenSSH no-master refusal. A09 failure 01's recorded interval
  from the prior SDK reply to lock acquisition is 2.046980352 seconds, exceeding
  the unchanged two-second next-frame deadline. The transport amendment changes
  setup, not the lease, recorder, RPC or clock limits.
- Separately numbered A09 runs 02 and 03 stop during their initial Recover with
  `OutcomeUnknown: clock checkpoint pending`, before preparation or fault injection.
  Run 03 follows an explicit read-only check of run 02's zero authority, absent
  operation/preparation and absent pending recovery; neither run resends an
  uncertain proposal. Both failures remain retained. Later thread/clock readbacks
  show a healthy updating clock and sleeping background threads, without a panic;
  they do not establish the exact lock holder at either failure. Further failure
  campaigns are deferred until selection of the next kernel artifact.
- `e7d322b` freezes the four-boot/eight-run A16 runner with separate instrumentation
  pilots, full failed/unstarted denominators, exact helper/binary pins and fenced
  cleanup. Nine integrated host tests pass. The complete lane check reports 56
  Python tests plus sanitizer/native helper checks passing. A thirteen-file
  instrumentation package is staged in `artifacts/a16-instrumentation-deploy05`;
  nothing is loaded in a guest yet.
- Fresh Robot preparation (`21c20ab`, `75dd98b`) records explicit installed-slot
  startup/enrollment/evidence steps. A locked/offline ARM CLI build and a native
  controller-fixture build pass from source `2ec9da0`; raw build and transform
  hashes are retained in `artifacts/install-robot-inputs-02`. The rebuilt fixture
  differs from the older prepared executable, so a separate command amendment
  selects it only for the new guest. Original cache inputs and running fixtures
  remain unchanged. The module15 input is explicitly intermediate; no new Robot
  payload or guest installation has been performed.
- An A06 source audit finds the native serdev shutdown callback absent. Linux
  calls that callback separately from removal. A narrow shared shutdown/removal
  closure fix is now test-first work in `feat/kernel-shutdown`; it must prevent
  additional dispatch, preserve uncertain operation/last-applied state and avoid
  duplicate transport closure/reference release. It cannot invent a zero-output
  receipt. Final module selection, targeted diagnostics, fresh Robot packaging
  and any necessary A16 source/artifact amendment remain pending this fix.

### Selected module 16 and next installation candidate

- `8802e97` integrates native serdev shutdown closure. Independent review of the
  exported JSON confirms the missing callback is the only behavioral RED failure;
  plain, lockdep, KASAN and KCSAN each then pass all seventeen cases. The earlier
  designated-initializer setup failure remains separate. No shutdown test claims
  a physical disable receipt or a real ARM reboot/poweroff sequence.
- Exact ARM build 02 passes with module SHA-256
  `a49fd1a48bbdc39447a78fc0b0714e2e713c34f4fe25c11e989a790778291112`.
  Fourteen actual fixture regressions pass in
  `artifacts/kernel-module16-lifecycle01` and `artifacts/kernel-module16-closure01`,
  covering ownership, transferred descriptors, removal/rebinding, capacity,
  delayed/replayed receipts, partial-write closure, controller restart and
  recovery. Original source, compiler/header/configuration pins, build logs and
  binary hashes are retained in `artifacts/kernel-module16-build02`. Build 01
  stopped at a host archive-path guard before SSH because the root directory
  entry lacked a trailing slash; that setup failure is preserved separately.
- `7e01aa4` adds two bounded owner-lifetime cases. Both pass on the selected ARM
  module in `artifacts/kernel-module16-owner01`: a surviving sibling loses
  authority after its leader exits, and genuine numeric PID reuse cannot regain
  authority through the old runtime descriptor. The original operation remains
  UNKNOWN. Host predicate checks include fourteen counterexamples.
- Gateway campaign sources `0d7fb40`, `29c84d9` and `496bf60` cover bounded hostile
  traffic, encrypted delay/replay, reserved cancellation under decoder pressure,
  and retention of the installed gateway's descriptors across replacement.
  Review corrected a lifetime predicate that confused cancellation and revocation
  event kinds. Target campaigns remain NOT_RUN; host mechanism checks are not
  acceptance evidence for the actual manager/gateway lifetime path.
- Fresh Robot candidate 03 selects module16, manager10 and the separately built
  ARM CLI/fixture. Its new payload is 34,263,040 bytes, SHA-256
  `e3df7b2eeb8f638cb43300095c03a3c8e6e48ac68bbbdc6bd175dec8e3932a88`;
  base manifest SHA-256 is
  `dec2aa32b660c3abef80688a903551022e8d811862f04fb236e6f24ce1a5365c`.
  An actual payload installation into a disposable filesystem with the test
  platform adapter and umask0077 passes all file hashes/modes and preserves a
  private sentinel. This does not execute guest binaries or touch host services.
  The new source archive retains the compiled kernel source bytes and adds GPL
  text/build provenance. Evidence lives in `artifacts/install-robot-inputs-03`;
  original prepared inputs remain unchanged. Fresh guest installation is NOT_RUN,
  and the disposable signing key is not a release identity.

- Manager10 starts healthy/inhibited with the selected module16; loaded build-id
  note SHA-256 is
  `25ff476c455cbf45558abec5e2e3d1ecd95d599a5befa532f16b2e578901ab48`.
  Actual A02 reply-loss02 passes: the relay withholds 625 bytes, forwards no
  response after arming, and the sole SDK proposal returns OutcomeUnknown without
  a retry. Independent observation establishes RUNNING; cancellation by the
  stable saved key produces a durable, reconciled terminal result. The production
  reader accepts the retired capture with no source gaps or recovery issues.
  Root independently verifies all 89 retained artifact hashes. This does not
  erase reply-loss01's earlier recorder failure.
- Actual A09 contention04 also passes. The production SQLite exclusive lock is
  held for 611,123,327 ns within its unchanged three-second lease; no rows are
  modified by the helper. Allocation and urgent cancellation both occur inside
  that interval, before any START or nonzero output. After release, the durable
  cancellation and reconciliation are verified, then explicit retirement/recovery
  and production-reader export complete. All 89 artifact hashes verify. This
  establishes SQLite writer contention, not fsync stalls, EIO or media failure.
  Earlier A09 setup failures remain distinct; no uncertain mutation is resent.
- The selected module's aggregate record is
  `artifacts/kernel-module16-acceptance01/manifest.json`, SHA-256
  `00120810d6e385e32fe4d915852fbed819b9182cbf013aee668538dcb8d9a298`.
  It binds the sixteen actual cases and four seventeen-case diagnostic runs,
  with physical qualification and the A16 comparison explicitly unverified.

- Actual A10 traffic01 stops on a harness assumption: the valid first proposal
  reply is PendingIntent without an operation ID. No malicious replay is sent.
  Separate retirement/recovery exports 228 records with no reader issues or raw
  remnants; 67 original and 48 retirement artifact hashes verify. `d638dd6`
  accepts that asynchronous reply and confirms the original handle/full RUNNING
  identity through bounded read-only queries, without another proposal. All
  twenty-three focused gateway host checks pass.
- Separately numbered traffic02 reaches protocol rejection, delayed-key terminal
  handling and encrypted replay rejection. Its reserved Cancel arrives after
  the operation reaches its target, so the combined campaign remains FAIL.
  Recorded guest-helper startup costs about 0.67 s while holders remain open for
  0.73–0.77s. Preparation of that helper before the operation is being reviewed;
  target, operation and ordinary-request deadlines remain unchanged.
- Before traffic02 retirement can contact the guest, the host QEMU process
  aborts. Host kernel and QEMU records identify a rejected thread creation at
  the launcher cgroup's TasksMax64; the core metadata reports 64 threads and
  SIGABRT. The cause of thread growth remains unverified. This is not a guest
  shutdown receipt. Private local metadata and the original disk are retained in
  `artifacts/robot-qemu-crash01`; no core memory is exported. A separately recorded
  recovery boot uses the same resource bounds and disk, with new serial/QMP paths
  in `artifacts/robot-crash-recovery01`. No original operation is replayed.
- `f82a04d` adds explicit A16 module16 amendment6 while preserving every frozen
  original helper. Seventeen wrapper/runner host checks and actual provenance
  verification pass. The new wrapper requires the sixteen-case aggregate and
  compares the loaded GNU build-id note with the selected module before testing.
  Target instrumentation pilots, staging and comparison remain NOT_RUN.

- Recovery boot `f8c8c92b-f208-4132-a1de-296f9e2ac51e` initially has both Robot
  services stopped and no authority module. Read-only SQLite integrity is OK;
  traffic02's exact key remains terminal Completed in its retired namespace.
  After explicit module16/manager10 startup and one recovery, a fresh pairing
  exports the original handle without any proposal resend. The production reader
  accepts 735 retained records, with no issues, raw remnants or source gaps and
  equal read/durable frontiers (runtime 200, kernel 724). Evidence remains
  metadata-only and the original traffic02 failure is unchanged. Records live in
  `artifacts/robot-a10-traffic-02-recovery-export01`.
- `f7a8d34` preloads the existing cancellation helper before Propose, with a
  bounded READY/one-trigger exchange; 32 focused gateway host tests pass.
  Fresh traffic03 reaches durable cancellation and reconciliation under decoder
  pressure, then retires, recovers and exports. Its final validator fails because
  Runtime Execution contains one accepted proposal tuple plus four ordinary
  SAMPLE request objects. This classification correction is pending separate
  analysis of the unchanged export; the campaign is not relabeled as PASS.
  All 136 original artifact hashes verify. No target or runtime deadline changed.
- `e73a82e` and `8b30678` prepare an opt-in actual Server/Robot retained-debit
  campaign: cancellation, explicit guest crash, four outstanding debits and
  matching historical settlement. Independent review caught an unbounded stdin
  read and premature success before gate cleanup; both are fixed before any
  target execution. All 24 focused host tests pass. Actual execution is NOT_RUN.
- Fresh Robot execution preparation in `artifacts/install-robot-execution-plan01`
  has eight passing host checks. Its seven stages separately cover first boot,
  identity, pinned prerequisites, installer transitions, installed bootstrap,
  manager lifecycle and final quiescence. Fresh QEMU explicitly uses TasksMax256
  and MemoryMax3G with the unchanged 2 GiB guest RAM; these test-host settings
  do not change preview limits or establish the cause of the older QEMU crash.
  No fresh guest stage has run. A16 amendment6 host inputs are now staged and
  byte-verified; guest deployment, instrumentation pilots and comparison remain
  NOT_RUN.

### Gateway campaigns and preserved crash evidence

- `313dbb8` corrects the traffic03 offline validator: one proposal tuple and
  four canonical SAMPLE requests are distinct Runtime Execution records. The
  unchanged capture passes independent reanalysis with 313 selected records,
  durable frontiers runtime 91/kernel 307, no reader issues, raw remnants or
  source gaps, and one allocation/START/cancellation closure. All 136 original
  hashes remain unchanged. The original campaign failure remains retained;
  `artifacts/robot-a10-traffic-03-reanalysis01` records the amended analysis.
- `a12060f` prepares the actual gateway descriptor helper before observation and
  proposal. Lifetime01 confirms one gateway SIGKILL while its three original
  descriptors remain held, followed by kernel quiescence and zero output. The
  campaign then stops because its harness rejects WriterStopped after completed
  namespace retirement. `b32fc26` accepts that state only when retirement is
  complete; all 39 focused gateway checks pass. Separate retirement02 exports
  128 records with no reader issues or raw remnants and verified hashes. The
  historical runtime outcome remains uncertain; replacement-while-held phases
  were not reached, so the full lifetime case is still incomplete.
- Lifetime02 loses the VM during the Activate reply, before Propose. Host
  evidence again records QEMU thread creation rejected at TasksMax64 and SIGABRT;
  the cause of thread growth remains unverified. Original disk and private core
  metadata remain preserved, with no core memory exported. Recovery02 fails
  before boot due to an incorrect serial-path argument. Explicit recovery03 uses
  the original successful argv with only new serial/QMP paths and TasksMax256;
  guest RAM and production limits are unchanged. The retained namespace has no
  operation records, and no uncertain Activate or Propose is resent.
- Lifetime02's raw recovery export succeeds, but the read-only evidence reader
  rejects its hot SQLite journal with extended error 776 (READONLY_ROLLBACK).
  The original export remains immutable. A narrow scratch-copy rollback fix
  and real SQLite crash regression are in progress; capture decoding is not
  claimed successful. Evidence is under
  `artifacts/robot-a10-lifetime-02-recovery-export01`.
- Lifetime03 is refused at Prepare because the original installation has reached
  its fixed 16 retained namespaces. No grant, proposal or intended fault is sent.
  Final explicit recovery leaves it healthy and inhibited; read-only SQLite
  integrity is OK, all 16 namespaces are retired and all 21 records remain.
  Both services stop, then the owned QEMU shuts down with inactive/MainPID0.
  `artifacts/robot-original-quiescence01` retains this final state. Its disk and
  history are preserved; remaining campaigns use the separately prepared fresh
  installation rather than deleting history or widening capacity.

### Read-only recovery and installed Robot startup

- `8a2e36a` fixes the actual SQLite hot-journal reader failure. Only extended
  error 776 permits validated rollback in a private scratch copy; source files
  remain read-only. The supported DELETE-journal layout is deliberately bounded,
  unsupported input fails, and recovery records hashes/unknown-tail provenance.
  All 23 evidence tests pass on the integration branch (one subprocess helper is
  intentionally ignored as a standalone test); lane strict Clippy and formatting
  also pass. Real child-process crash RED/GREEN and malformed-input regressions
  are retained in `artifacts/evidence-hot-journal01`.
- Final offline reanalysis of lifetime02 recovers 30 committed records with
  durable frontiers 16/14. Batch 9 remains an uncommitted raw remnant; volatile
  tail is unknown and execution replay is ineligible. Root verifies final source,
  reader and report hashes plus all 27 unchanged original artifact files,
  including the failed reader result. The new report is
  `artifacts/robot-a10-lifetime-02-recovery-reanalysis01/report02.json`, SHA-256
  `830265fe5dfbf112524230d4bed1d89cf35300a2c5f97571923c02f2cc77109f`.
- `ab74251` prepares the installed Server observer-failure campaign: refused
  launch without observer readiness, actual reader death during an attempt and
  a fixed workload producing diagnostic loss. Root's 13 focused and nine reused
  capacity checks pass. Actual execution remains NOT_RUN; observer loss does
  not imply an unknown application outcome or automatic termination.
- Fresh Robot run01 passes launch/identity, exact package prerequisites,
  installer transitions and installed-slot bootstrap. It verifies module16,
  manager10, stripped gateway, ARM CLI, device/socket ownership, no TTY bypass,
  gateway privilege removal and retained installation sentinels. Boot is
  `bc149601-0fc7-4bbf-b7d9-46a4d8f8e0fb`; machine ID is
  `edba875c58c24048918291d46afbcce4`. Test signing remains disposable.
- The unchanged installed lifecycle completes two natural operations under one
  grant, absent-key cancellation and CLI pre-send cancellation. It then fails
  during Observe before the planned gateway signal or new proposal because the
  kernel is faulted. The whole lifecycle remains FAIL. Subsequent read-only
  diagnostics find no live authority/output, fully durable frontiers 89/172,
  one retired namespace and four terminal records; the two known completions
  remain known. A separately authorized, guarded one-shot recovery succeeds;
  the original namespace is exported without resubmission. First-fault analysis
  remains in progress; the later EXPIRED status alone is not its established
  cause. Original failure, read-only export refusal, recovery and export records
  remain separately numbered under `artifacts/install-robot-run01*`.
- Capture analysis confirms the first fault is EXPIRED, 4.052596976 seconds
  after grant and 1.065219906 seconds after operation 2 reconciles; the grant
  still has 25.945266803 seconds remaining. The 60-second mapping cutoff falls
  inside bootstrap's recorded Recover exchange, and both later Recover calls
  reuse that mapping through the runtime's Ready fast path. Source and timing
  therefore identify the aging mapping as the explanation; no branch trace was
  captured. The namespace exports 261 records with no issues, raw remnants or
  source gaps. Root verifies both reconciled allocations, no third allocation
  and the retained failure/capture/recovery hashes. A narrow runtime change is
  in progress: fresh explicit recovery refreshes the inhibited mapping, pending
  recovery only polls, and grants cannot exceed its conservative remaining
  lifetime. No expiry threshold is widened.
- The fresh Robot is explicitly stopped and powered off after recovery, with
  no prepared/live authority, one retired namespace and four preserved records.
  Root verifies inactive/MainPID0 and the quiescence artifact hashes in
  `artifacts/install-robot-quiescence02`. A16 now has the sole owned VM window;
  its exact first boot and guarded deployment pass, with instrumentation pilots
  and comparison still pending actual results.

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
