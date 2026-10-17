# Implementation checkpoint — 2026-10-17

The user requested **continue** after the pushed pause checkpoint. Work resumed;
the full v0.0.1 release is incomplete. The goal tracker still reports `paused`
and exposes no resume action; this is a tracker limitation, not a new user pause.
The approved scope remains [the full plan](../superpowers/plans/2026-10-16-actryn-v0.0.1.md).
[Progress](progress.md) and [acceptance gaps](acceptance-gaps.md) retain the evidence.
Earlier checkpoints and failed attempts remain preserved.

## Repository and execution state

- Integration branch: `feat/v0.0.1`; implementation HEAD before this handoff:
  `f3953a0`. Remote `9db46cc` was verified on 2026-10-17. CI for the new
  checkpoint has not been checked. The user authorized pushing this branch to
  `origin`. Every task commit carries
  `Signed-off-by: Utkarsh Maurya <projects.utkarshMaurya@gmail.com>`.
- Three bounded agent lanes resumed. A16 native build01 finished and its VM is
  off; Server importer07 owns the sole VM window. No fixture process runs.
  `artifacts/server-a08-import-failure01/pause-result.json` verifies the original
  Server PID absent and its unit inactive/MainPID0 after one graceful poweroff.
  Receipt SHA256: `86e8eee0fe4d760c958627e8057c09d244f737acff51ea8507dc4b3d9451fe8d`.
- Fresh Server readback retains eight reaped attempts with zero open calls or
  Robot debits. No container tasks, child cgroups, fault shim or drop-in exist.
  Corrected read-only preflight03 passes. Source, failed import, disks, seed
  and SSH trust remain preserved. Raw artifacts
  and VM state are ignored local files; a Git push does not back them up.
- Host boot: `7f875223-b4cf-421e-b04d-81e3c1f19460`. Prior fixture processes did
  not survive the host reboot and none was restarted. No physical device used.
- All linked worktrees were inspected. Existing Cargo.lock changes remain
  untouched in `.worktrees/{fixture,observer-install,robot,server,source-gap}`.
  `.worktrees/{artifact-modes,artifact-registry-mode}` are clean and integrated;
  detached `.worktrees/server-importer-build01` freezes source `544c382`.
- Original userspace: Apache-2.0; kernel/BPF: GPL-2.0-only. No global Git identity
  or provider/signing credentials changed. Account quota telemetry is unavailable.

## Server pressure campaign: import passes; property collector fixed

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
`artifacts/server-a08-command-normalization-fix01`. Fresh run09 verification of
the existing instrumentation is being prepared; do not repeat install or rewrite
old setup.

Current VM: unit `actryn-server-importer07.service`, PID 388472/start 5541602,
invocation `821b6ac077fc4fb0932a5f482d2f43ae`, guest boot
`3138459f-e5b3-411c-ab6a-932418cf2f0a`. Boot/readiness passes. Revalidate this
lifetime before each guest action. Package update, quarantine, fresh import and
service-UID checks pass. Services are active (observer PID1794, launcher PID2244,
serverd PID2277); these observations require fresh verification. Run07 failed
before mutation; run08 failed after instrumentation but before any attempt.

Historical run06: unit `actryn-server-a08-pressure06.service`, PID 226766,
start ticks 686142, invocation `79c8a4c9216b49d698f50625a775b6d4`, guest boot
`73a11031-bf36-4858-8c97-38a0ff74a91f`. These identities are now dead.
The retained disk is `.cache/qemu/install-server03/disk.qcow2`, device 56,
inode 27349874, size 2126446592, mtime_ns 1792174467145588725. Its contents changed
through compiler installation and the failed import. The next boot's exact
prelaunch disk SHA256 was
`9fce904771986d618b52407bf4d6fb417d061a0207edd3e5494a5999651a7f91`;
this is historical now that the guest is running.

## A16: native diagnostic build passes; target diagnostic not run

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
The module was not loaded and no client or fixture ran. The single cold-case
plan `artifacts/a16-hello8-case-plan01` is frozen and root-reviewed, with seven
host checks and 21 independently verified inventory leaves. Inventory SHA256:
`d2074d172179cf1d4da17d11561cf02f3e05a51ebbf28b17a2f91b5e9d2f6dd6`.
It requires one retained-journal fixture startup, a fresh target boot and one
observed attempt, preserving any failure. No target window is allocated yet.

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
  it is installed by the new test package, but its Server execution is NOT_RUN.

## Remaining integration and external gates

`artifacts/robot-retained-debit-plan02` amendment03 remains prepared, NOT_RUN;
11 host checks previously passed. Its null template must not execute. Future
execution needs fresh boot/process/controller identities, post-A08 catalogs and
a new workload principal under the existing lifecycle03 issuer. The old principal
is revoked. Preserve namespaces/history; six preparations project 9 to 15 of 16.

Continue with this handoff and current ledgers, verifying branch/worktree state,
resources and retained evidence. Verify the existing instrumentation under the
corrected collector before the pressure campaign. Run only a reviewed,
numbered campaign with fresh identities and evidence paths. A16 has no allocated
window. Authorized live-provider credentials, a release signing custodian and
an independent developer remain external inputs. Final coherent qualification
is unfinished. Live motion stays inhibited; no result is physical qualification.
