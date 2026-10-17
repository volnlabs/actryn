# Implementation checkpoint — 2026-10-17

The user requested **continue** after the pushed pause checkpoint. Work resumed;
the full v0.0.1 release is incomplete. The goal tracker still reports `paused`
and exposes no resume action; this is a tracker limitation, not a new user pause.
The approved scope remains [the full plan](../superpowers/plans/2026-10-16-actryn-v0.0.1.md).
[Progress](progress.md) and [acceptance gaps](acceptance-gaps.md) retain the evidence.
Earlier checkpoints and failed attempts remain preserved.

## Repository and execution state

- Integration branch: `feat/v0.0.1`; implementation HEAD before this handoff:
  `8d6e71d`. Preceding remote `874525f` was verified on 2026-10-17. CI for the new
  checkpoint has not been checked. The user authorized pushing this branch to
  `origin`. Every task commit carries
  `Signed-off-by: Utkarsh Maurya <projects.utkarshMaurya@gmail.com>`.
- All test guests and fixtures are now off. Retained-debit campaign01 performed
  one crash and reboot, then failed its coordinator readiness deadline. Both
  original FAILED records, the abort-revoke and pre/post-crash evidence remain.
  Robot cleanup recovered its already-retired context once, exported both original
  captures, stopped both services and unloaded the module. Both guests then
  powered off gracefully once and the exact fixture stopped once. Receipt:
  `artifacts/robot-retained-debit-cleanup01/result.json`.
- The stopped Server retains 17 launcher/16 broker rows and exactly two outstanding
  Robot charges. Its services never started after the crash; the crashed attempt
  is still `running/pending` on disk pending supported recovery. Peer/key/drop-in
  stay installed. The Robot retains 11 namespaces/18 records and every old
  identity generation/tombstone. Disks, seed and SSH trust remain preserved. Raw artifacts
  and VM state are ignored local files; a Git push does not back them up.
- Host boot: `7f875223-b4cf-421e-b04d-81e3c1f19460`. The A16 fixture was restored
  once using its retained journal, advancing boot35 to36, then shut down after
  the diagnostic. No physical device used.
- All linked worktrees were inspected. Existing Cargo.lock changes remain
  untouched in `.worktrees/{fixture,observer-install,robot,server,source-gap}`.
  `.worktrees/{artifact-modes,artifact-registry-mode}` are clean and integrated;
  detached `.worktrees/server-importer-build01` freezes source `544c382`.
- Original userspace: Apache-2.0; kernel/BPF: GPL-2.0-only. No global Git identity
  or provider/signing credentials changed. Account quota telemetry is unavailable.

## Server pressure: instrumented campaign verified, VM off

`cd9d551` contains the pressure harness; 43 integration host checks passed.
`1293676` corrects the installed command to `actryn server import`. Plans01–05
and their failures remain preserved. Plan06 passes seven host checks, then actual
boot, staging, preflight and toolchain simulation against all 14 runtime pins.

Toolchain install01 failed because the preparation helper's inherited 8 MiB file
limit interrupted an apt download; all 328 installed package rows stayed unchanged.
Reviewed plan02 caps output without limiting downloaded files. Six host checks pass,
including reproduction of the earlier failure. Actual install02 passes with exactly
35 additions, no change to existing packages/runtime pins, and clean dpkg audit.
Evidence: `artifacts/server-a08-toolchain-{plan,install}02`.

Native pressure-agent and fault-library compilation and OCI assembly then pass.
Actual import fails with `rootfs file mode changed`: process umask 077 filtered
requested file modes to 0500/0400. The invalid sealed artifact remains at
`/var/lib/actryn-artifacts/443737b73904317b1ca87741eee2582997dcd1ab9c9fef4f833de7a06b647110`.
It was not allowlisted, and no pressure attempt, shim or campaign was launched.
The original approved artifact/configuration remains unchanged. Raw build/import,
capture and shutdown evidence is under `artifacts/server-a08-pressure-run06` and
`artifacts/server-a08-import-failure01`.

`ec2dfde` integrates the shared writer fix: apply the requested permissions on the
exclusively created descriptor after writing and before syncing. RED reproduced
artifact verification and config-mode failures; all ten Server library tests,
strict all-target Server Clippy and formatting pass. Subprocess regressions cover
umasks 027/077 and retain existing-file/symlink rejection. Logs:
`artifacts/artifact-modes01`. This fix neither repairs nor overwrites an existing
invalid sealed slot.

`544c382` also fixes fresh registry creation under umasks 027/077, using descriptor
permissions and parent fsync; existing registries must already be 0755 and remain
unchanged on refusal. Nine artifact tests and strict Server Clippy pass.
The CLI builds from frozen `544c382`; two CLI tests, strict CLI Clippy, allocated
ELF-section equality after stripping and help smoke pass. New CLI SHA256:
`f5840d33b5ffff7b9de58cf32581299fb25289c186ba38f1ede69a1f9c42443c`.
The incomplete unsigned bundle in `artifacts/server-importer-package01` builds
and inspects; manifest SHA256 is
`60e35e538562c610091f0d70d4873b433a5f61292c6c444035332caea791e535`.
All 138 versioned imports match the four exact captured target libraries,
including `pow@GLIBC_2.29` from `libm`. This is static compatibility evidence.

Read-only preflight02 confirms the unchanged eight-attempt stores, two charged
registry entries and exact failed-slot files. It then fails because its harness
expects `current` to target the release directory instead of its `payload`
subdirectory. A separate guarded readback confirms the installed pointer matches
the installer contract and two release slots remain. Preflight03 corrects only
that harness assumption and passes; all raw state/config/registry records equal
the earlier readback. The failure remains in
`artifacts/server-importer-preflight-execution01`; success and exact runtime
libraries are in `artifacts/server-importer-preflight-execution02`.

The separate disposable test variant uses the existing Server03 test key/SPKI.
Its explicit NOT-A-RELEASE assertion supplies synthetic installer-required
qualification fields; actual qualification remains incomplete. The genuine
unsigned reference is unchanged. Actual installed CLI inspect, stage, activate
and resume all pass in `artifacts/server-importer-update-execution01`. Installed
test manifest:
`98a87977f05b0128023a7018650eb70cc1f6566d09d874e671117671e66b4ae6`.
All three retained slots occupy 420,652,930 bytes. Old slots, raw databases,
configuration and registry remain unchanged; services remain inactive and the
installation gate is cleared. No agent attempt starts during this update.

The guarded same-parent NOREPLACE rename also passes in
`artifacts/server-importer-quarantine-execution01`: the failed slot is now
`.quarantine-443737b73904317b1ca87741eee2582997dcd1ab9c9fef4f833de7a06b647110-import06`.
All nine files, thirteen directories, invalid modes and inodes are preserved;
only the moved-root ctime and registry-parent timestamps may change. The parent
is synced and both entries remain charged. The quarantine step performs no repair,
deletion or new approval.

The subsequent single import of that same OCI under umask 077 passes in
`artifacts/server-importer-reimport-execution01`: nine files and thirteen
directories have the required modes, the quarantine/source layout remain exact,
and both stores retain their eight rows and raw database bytes. Registry occupancy
is now three and approvals two. New configuration SHA256:
`b03fe8c8f53e534339c71218ec36f19f50070afc662050aa4b1673d5a9aea461`.
The actual service UID/GID 987 with no supplemental groups passes `--check-config`.

Run07 then starts the three installed services but fails during the pressure
helper's initial property read, before setup or instrumentation. Systemd's text
output omits the empty `DeviceAllow` array even with `--all`; the typed D-Bus getter
returns `{"type":"a(ss)","data":[]}`. Readback confirms eight unchanged rows per
store, zero outstanding work and no shim/drop-in/setup directory. Evidence:
`artifacts/server-a08-pressure-run07`, `server-a08-property-diagnosis01` and
`server-a08-deviceallow-diagnosis01`. `fabd894` fixes only the test helper to read
the typed array, including all nonempty entries; RED reproduces the failure and
48 host tests pass. Run08 preparation uses a fresh output/source directory and the
retained native agent, fault library and OCI. No campaign has run yet.

Run08's actual ready check then passes. Setup installs the shim and restarts
launcher/serverd, but its inherited-property check fails because the descriptor
regex leaves alternating volatile fields, including the pre-start completion
timestamp. `artifacts/server-a08-instrumentation-diagnosis01` preserves exact
before/after records and current observations: only the intended launcher command
differs after correct timestamp normalization; eight original rows per store and
zero outstanding work remain. The shim contains only the pinned library, mapped
by launcher PID2244/start308811; no control/events or campaign exists. Preserve
run08 FAILED. Parser fix `f3953a0` passes both exact-input regressions and all
50 host checks, with raw RED/GREEN logs retained in
`artifacts/server-a08-command-normalization-fix01`.

Run09 verifies the existing instrumentation without reinstalling or restarting.
Its first pressure attempt then fails the harness's four-record assertion:
`Inspection.calls` includes durable rejection tombstones as well as approved
calls. Retained inspection and raw broker accounting confirm four settled
digest-bearing base reservations plus four closed, cancelled burst tombstones
with NULL digests/output and zero reservation/token/deadline fields. Four other
burst replies remain uncertain. The harness sends one cancellation and both
stores reap attempt `f6d7570800dc4710190a1e0755e5b9a0`; the original eight full
rows remain unchanged. No fault control was armed and allocation/reclaim phases
were not run. Run09 remains FAILED. Evidence:
`artifacts/server-a08-pressure-run09` and
`artifacts/server-a08-call-accounting-diagnosis02` (capture SHA256
`a9abf15dd6cc5557cf088b9b7f4504dd5715397fac474b20a91312c5b23c7c26`).
The first read-only capture rejected the expected uppercase FAILED filename;
that capture error is retained separately. Validator fix `6eac6ab` keeps the
four admitted reservations distinct from zero-reservation tombstones, correlates
status with read-only SQL and records accounting before validation. RED reproduces
the mismatch; all 55 host tests pass. Logs:
`artifacts/server-a08-pressure-accounting-fix01`.

Run10 passes verification and the active approved-call checks, then fails because
the allocation expected to return ENOSPC instead succeeds. Its active attempt
`805a43bd1d63fcf9dc0abfa4a19080ea` is cancelled once by the harness. Unexpected
preparation `a42015500419533e44ac1d10a5e29fde` later retires automatically;
readback finds it reaped/cancelled and sends no additional Cancel. Both stores
retain eleven rows, no outstanding work or tasks; the unexpected preparation's
stdout/stderr are empty. Run10 remains FAILED and reclaim was not run.

Read-only diagnosis shows `/run` and `/run/actryn` mounted `noexec` in the
launcher namespace. The pinned library has no executable mapping; four bounded
relocation-pointer reads resolve `mkdir`/`rmdir` to libc. Thus the earlier
mapping-only setup check did not prove interposition. Evidence:
`artifacts/server-a08-{allocation-diagnosis01,shim-visibility01,loader-diagnosis01}`
and `server-a08-unexpected-preparation-cleanup01`. Loader capture SHA256:
`944f7a08c98266e14a294f5eaba4b44fe8583fe4823b740e8bfdcbb553b3c672`.
Fix `343572e` places the test library in protected `/opt` storage while keeping
controls under `/run`. Setup requires an executable mapping of the exact file,
one launcher user and no legacy mapping. RED reproduces the false acceptance;
58 host tests pass in `artifacts/server-a08-executable-shim-fix01`. No native
code, mount or production policy changes. Corrected target execution follows below.

Separate failure finalization now passes all seven steps: read-only readiness,
both final exports, old-override restoration, restored-state verification, one
service stop, quiescence marker and capture. Final evidence confirms four
approved calls, four budget refusals, four closed zero-reservation tombstones
and four uncertain burst replies. The original failure remains FAILED. Host
verification covers all 91 archive files (858159 bytes), both raw SQLite
databases with eleven exact reaped rows each, no outstanding calls/debits, all
22 run10 and 15 run09 records, both attempts' logs and observer trace/summary.
Evidence: `artifacts/server-a08-failure-finalization-{plan,run}01`; capture
SHA256 `3c0b3c594d2bd73b693a7dfce569b9138902ba7581013fabdd2b999523a17649`.
The old control directory is now retained by one verified non-overwriting rename
to `/run/actryn/a08-pressure-retained-through-run10`; its inode and bytes match.

Run11 passes all three phases with the corrected executable-mapping check:
four approved calls with durable cancellation and four uncertain burst replies;
one ENOSPC allocation failure; and EBUSY retirement pressure that preserves
active identity/output, refuses another preparation and converges without a
second Cancel. A replacement preparation then succeeds. All eleven earlier
full rows remain unchanged. Final exports, restoration, stop and capture pass.
Root verifies 213 files/1538917 bytes, all 88 prior custody files, both libraries,
raw SQLite integrity, fifteen launcher/fourteen broker histories and zero
outstanding work. Evidence: `artifacts/server-a08-pressure-run11`; capture
SHA256 `a67d3402ce7eeec656289958653990bcc254562b86c5c6a1a7d8cb20147816c0`.
This is instrumented directory-fault/call-pressure evidence, not heap OOM,
unchanged-unit qualification, complete A08 or physical acceptance.

One installed controller-fixture process also starts, reports inhibited boot1,
zero duties/encoders/queue and exits after one supported shutdown. The smoke
validator incorrectly expected empty stderr; the source's normal startup banner
causes its retained failure. Separate read-only reanalysis verifies that banner,
the boot journal, dead process and unchanged Server databases without restarting
the fixture. Evidence: `artifacts/server-installed-fixture-smoke01` and
`server-installed-fixture-smoke-diagnosis02`; the first read-only validator error
is also retained. No wire commands or full protocol campaign ran in this smoke.

Closed VM: unit `actryn-server-importer07.service`, PID 388472/start 5541602,
invocation `821b6ac077fc4fb0932a5f482d2f43ae`, guest boot
`3138459f-e5b3-411c-ab6a-932418cf2f0a`. One guarded poweroff verifies the original
lifetime dead and unit inactive/MainPID0; see `server-a08-pressure-run11/poweroff`.
Seed and strict SSH trust are unchanged. The retained disk now has device56,
inode27349874, size2542731264, mtime_ns1792229032069201011. Fresh identities are
required for the next window. Package update, quarantine, fresh import and
service-UID checks pass. Original properties were restored before shutdown.
Run07 failed
before mutation; run08 failed after instrumentation but before any attempt;
run09 failed after one pressure attempt; run10 failed after an active attempt
and unexpected successful preparation. Those failures remain unchanged.

Historical run06: unit `actryn-server-a08-pressure06.service`, PID 226766,
start ticks 686142, invocation `79c8a4c9216b49d698f50625a775b6d4`, guest boot
`73a11031-bf36-4858-8c97-38a0ff74a91f`. These identities are now dead.
The retained disk is `.cache/qemu/install-server03/disk.qcow2`, device 56,
inode 27349874, size 2126446592, mtime_ns 1792174467145588725. Its contents changed
through compiler installation and the failed import. The next boot's exact
prelaunch disk SHA256 was
`9fce904771986d618b52407bf4d6fb417d061a0207edd3e5494a5999651a7f91`;
this predates subsequent guest writes.

## A16: cold diagnostic accepted; production comparison remains open

Excluded pilot07 remains FAILED: the first HELLO faults before grant/START/SAMPLE;
nine other trials pass. Exact rejected predicate and cause remain unproven.
No repeat pilot, userspace pilot or comparison ran. Original evidence remains in
`artifacts/a16-execution07/tracekernel07`.

`e9b2bd8` integrates five diagnostic files; all 24 focused host checks passed.
The unchanged HELLO predicate and timestamp sample remain authoritative. Event
loss, gaps and nonzero/unknown RECOVER results prevent diagnostic success.
This admin-only diagnostic cannot replace production module 16 or qualify release.

`artifacts/a16-hello8-native-plan01` is now complete and reviewed for compile-only
execution. Its 24-file inventory SHA256 is
`8c94877a1aef432c048b6d48f2db6474073e17f141ef36418db30b9c661fc47b`;
source archive SHA256 is
`9cad135e205f0eea39f6e2c3a1573119b04f615ab02d8e2115f3f12927f5a0d7`.
Syntax, eleven source members, ten package pins and five tool pins were checked.
It used a disconnected second UART and one bounded native build. All ten stages
pass in `artifacts/a16-hello8-native-build01`; compilation took 40.85 s and the VM
shut down cleanly. Module SHA256:
`e701dcd825d8101eed58cb96bb87029d293ccdfa616ef13fcf0d3e5e68f6aede`.
Root independently verifies 124 inventory entries, source/ELF/kernel input pins
and the dead VM lifetime in `artifacts/a16-hello8-root-review01`.
That compile-only window loaded no module and ran no client or fixture. The single cold-case
plan `artifacts/a16-hello8-case-plan01` is frozen and root-reviewed, with seven
host checks and 21 independently verified inventory leaves. Inventory SHA256:
`d2074d172179cf1d4da17d11561cf02f3e05a51ebbf28b17a2f91b5e9d2f6dd6`.
Its actual execution is now complete in `artifacts/a16-hello8-case01`.
One fixture startup appends exactly boot36 to the same journal inode; one fresh
ARM guest boot loads the selected diagnostic module with an empty snapshot.
The sole cold RECOVER returns zero and receives ACCEPTED_ACK from the matching
device, boot36/session1. Root independently checks all raw bytes, CRC/COBS,
nonce/transaction, two contiguous loss-free events, five snapshot records and
the unchanged predicate arithmetic: 3266542 ns from original send timestamp to
processing. Capture SHA256:
`9706979ad89dd3c6c8790ade52ad1670485533fa3f025489bcbfccc4b9c91f9e`.

Guarded status/readback, normal unload, guest poweroff and supported fixture
shutdown each run once. Both recorded process lifetimes are dead; the744-byte
journal is unchanged after startup. Final case inventory (112 files) SHA256:
`04f3a0b5243ca46ce72c2c4f88d1a8a9071268ecd1819a0a08229c51e908c3a4`;
fixture restoration inventory (13 files) SHA256:
`2f796193c349aed2aa4e5e402c7c0f6eba9ca2264ab2189eba1f90937b757e4c`.
Host observation/display failures are retained and resolved by read-only checks;
no target action was repeated. Final collected-unit resource counters are
unavailable. This instrumented acceptance is a non-reproduction, not a production
fix, benchmark result or attribution of pilot07. A16 still requires qualified
production pilots and the frozen kernel/userspace comparison. A separately
numbered production qualification attempt is being prepared without warm-up,
new instrumentation or changed limits.

## Source, notices and unsigned candidates

- `artifacts/release-cohort01` remains unchanged, unsigned, qualification incomplete
  and `promotable=false`. Root independently verifies all 55 inventory files
  (115,773,094 bytes) and all 44 payload entries/modes. Manifests:
  Server `f3018c58da0f2687cfaf54d52244589078ae24d8bd1d83263a141e20feaeb484`;
  Robot `878732d88c534a87388c35aff7a6e2b35ef9192fb50210d045b77cd053536800`.
  Source revision is `cc530d2`; component origins are separately recorded.
  This candidate predates the importer fix. No candidate was installed or signed.
- `artifacts/release-source-materials01` binds 250 files/86,498,309 bytes to those
  manifests, including ten Git archives and 234 public source/receipt copies.
  Root independently verifies every file and 2691 Git leaves, including symlinks
  and executable bits. Material manifest SHA256:
  `9b3edb584823732c5d8760b02bb818d17441fe8d1ada82d9e14b1e1ff5b65581`.
  Receipts: `artifacts/release-cohort-root-review01/{source-materials-result,git-source-result}.json`.
- Exact offline agent/OCI bytes were reproduced in `offline-oci-matching-build03`.
  Complete exact glibc source and all 74 inventory entries were verified in
  `glibc-source-complete01`; all 16 selected notice slices pass independent review
  in `release-notices02`. These are retained `artifacts/` directories.
  Full GCC source and broader dependency/toolchain source closure remain explicit
  gaps; no hermetic-build or legal-completeness claim follows from these checks.
- Replacement fixture ELF imports match the actual Server runtime libraries;
  installed startup/admin-status/shutdown is now verified by separate read-only
  reanalysis of the retained smoke. This is not a full installed protocol test.
- `artifacts/cohort-reconciliation-audit01` identifies only importer product
  source drift since the original cohort. The x64 CLI already includes both
  fixes. One targeted ARM CLI build at `544c382` passes in 70.450 seconds;
  all 28 allocated sections survive strip-debug unchanged. New CLI SHA256:
  `4102e793c48fc43767680ed3c9cf4ffd2f8512171271e3340ab2632090fd1fc5`.
  Its 136 versioned imports add only `fchmod@GLIBC_2.17`. Exact Debian ARM
  provider ELF verification passes: all 136 versioned requirements match four
  libraries collected once from the exact installed Robot boot. Capture SHA256:
  `156af09f19eda3c92009f6e544981cbb79ca61e86c122858d03c3f8e806dead8`.
  `artifacts/arm-cli-runtime-collection01` preserves the capture/static matcher
  and a host reporting error after its successful run; no checker retry occurred.
  Installed-path validation of the rebuilt ARM CLI remains pending.
  `artifacts/arm-cli-importer-build01` retains build/native/link receipts and
  both corrected metadata-analysis failures. No manager/module rebuild or
  candidate/cohort replacement occurred. Final source/evidence association
  must use new manifests and preserve the older per-component source origins.

## Remaining integration and external gates

Retained-debit campaign01 is **FAILED**, not NOT_RUN or passed. Publication01
installs the exact peer/key/drop-in and starts the three packaged Server services
once with checked socket peers, credential ACL and unchanged old rows. Campaign01
then executes its cancel and crash cases, retaining both downstream charges.
One pidfd-checked SIGKILL and one reboot occur; the next readiness probe exceeds
its five-second outer deadline, equal to SSH's connect timeout. No automatic
reboot/campaign retry occurs. Coordinator EOF triggers the harness's bounded
abort-revoke. Preserve `robot-retained-debit-{run01,coordinator01}` unchanged.

`artifacts/robot-retained-debit-reboot-inspection01` verifies the new Server boot
before any services start: all earlier 15/14 full rows remain, plus exactly two
new attempts and two outstanding Robot charges. The cold archive is
`0a644db3a830e70c9748c46c2a8ca3a25ecfed2bedf71830a2b3484d7eeab70e`.
Robot raw inspection retains 11 namespaces/18 records. Its one old unfinished
namespace/record undergo the documented startup retirement/OutcomeUnknown
transition; all other old rows and immutable payloads remain unchanged. This
corrects the overly broad initial assertion that every old Robot row was unchanged.

The original debit handles are:

| Case | Attempt | Namespace | Request key |
|---|---|---|---|
| Cancel | `667300134db5fed6e7a11ca8c422e917` | `60e6830b3c9db771d174952cd1247264` | `7c7bf5f0eee45efc1d4037656c7b0febf3f9f028b2c4b9ca9b41bc4f5bf31d8c` |
| Crash | `dde8e543f0c0847a077bc37fd6d96910` | `b655bc4f99e638743cb88eb86f09074c` | `bb95c1c356d0493bd5ed0c3dd3631414b016fbd960ee02203034d13e1ea4a2a7` |

Both operations durably completed. The second live response establishes matched
reconciliation before cleanup; after retirement the old manager projects an
unknown task verdict with `reconciled=false`. That exposed the product gap fixed
by `3c8dae7` and `c4acb14`: derive historical reconciliation from durable proof,
then settle resource accounting without claiming task success. Allocated
cancellations gain an atomic revision/full-operation-bound marker; legacy
cancellation without proof remains charged. `8d6e71d` tests the actual historical
service/closure-worker path, including late-publication suppression and slot
retention until worker exit. The phase and closure protocol remain unchanged.
Focused lane tests and strict Clippy pass. Root integration passes 135 Rust tests
with three target-only tests ignored, all 26 debit-harness checks and formatting;
receipts are under `artifacts/reconciliation-integration-checks01`. No replacement target binary has
been installed or exercised yet.

Cleanup uses one explicit Recover because the second context was already retired
with stopped writers. Both original captures then export, with every leaf hash
checked: 39 files/250084 bytes and 84 files/590166 bytes. Manifests are
`d23b7a48c3f94ed8e26c2af87b38a707f51abacfc8b45c73c34a342cfd905686` and
`943a75aabc9f8a6d5c311e0b6fd192db0d1fb5cacfacee99dfc601a779e0a47c` in
`artifacts/robot-retained-debit-robot-export03`. These metadata exports retain
unknown volatile tails and are not execution-replay eligible. The two earlier
export failures remain preserved. Module unload, independent disabled-zero
fixture status, both one-shot graceful poweroffs and one fixture shutdown pass.
The Robot registry remains byte-identical at
`0a8d736fb748970af5078bbb7865fc8c83e8c2e37643695cb82dd29c1bc8bba3`.
Stopped disk hashes and identities are in
`artifacts/robot-retained-debit-cleanup01/result.json`; revalidate them before boot.
Server peer/key/drop-in MUST remain while its two charges are unresolved. No
record, identity generation, revocation tombstone or fixture journal was deleted.

Next: rebuild the changed Server daemon and Robot manager with exact source/native
receipts, prepare new immutable candidates, and qualify retained-history settlement
through the authenticated installed path. Both installations already have three
release slots; resolve supported reversible archival of an inactive slot before
staging another, preserving every byte and the current pointer. Do not raise the
slot quota. New Robot startup must use the supported inhibited maintenance path.
The test generation `3de5e81b8a630567c2652760914e62ef` and principal
`debit01-14987a9409d60281` remain installed; test private keys stay local mode 0600
inside a 0700 directory and outside evidence hashes/inventories.

Use a separately numbered continuation amendment and the two original handles;
do not replay their proposals or crash the Server again merely to rerun setup.
The original six-preparation campaign would take 11 retained namespaces to 17,
exceeding 16. Its four unrun preparations fit at 15 if explicitly planned against
the upgraded products. Readiness probes need an SSH timeout shorter than their
outer deadline and narrowly typed timeout handling within the original overall
budget; identity/output failures remain fatal, and reboot is never retried.

`48ac40d` adds the bounded existing-device 1:7 refusal and actual 256 MiB cgroup OOM
diagnostic. All 67 root host checks pass; target execution must follow charge
settlement. A16 production pilots and the required comparison remain pending.
The new reconciliation changes supersede the earlier importer-only source-drift
audit: final component manifests and source/evidence associations need updating.

Authorized live-provider credentials, a release signing custodian and
an independent developer remain external inputs. Final coherent qualification
is unfinished. Live motion stays inhibited; no result is physical qualification.
